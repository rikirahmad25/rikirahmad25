from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.keyboards.admin import users_admin_keyboard
from app.bot.states.admin import AdminManageStates
from app.core.permissions import MANAGE_ADMINS, MANAGE_PAYMENTS, VIEW_REPORTS
from app.db.models import User
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.text import money

router = Router(name='admin_users')


def _user_line(user) -> str:
    name = ' '.join(part for part in [user.first_name, user.last_name] if part) or '—'
    username = f'@{user.username}' if user.username else '—'
    blocked = 'مسدود' if user.is_blocked else 'فعال'
    bot_blocked = 'بله' if (user.metadata_json or {}).get('bot_blocked') else 'خیر'
    return (
        f'#{user.id} | {name} | {username} | TelegramID: {user.telegram_id} | '
        f'Phone: {user.phone_number or "—"} | Wallet: {money(user.wallet_balance or 0)} | '
        f'وضعیت: {blocked} | ربات را بلاک کرده: {bot_blocked} | Ref: {user.referral_code}'
    )


async def _has(telegram_id: int, permission: str) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, permission)


@router.callback_query(F.data == 'admin:users')
async def users_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if not (await _has(callback.from_user.id, VIEW_REPORTS) or await _has(callback.from_user.id, MANAGE_ADMINS)):
        await callback.message.answer('دسترسی نداری.')
        return
    await callback.message.answer('👥 مدیریت کاربران ربات:', reply_markup=users_admin_keyboard())


@router.callback_query(F.data == 'admin:users:export')
async def users_export(callback: CallbackQuery) -> None:
    await callback.answer('در حال ساخت خروجی')
    if not await _has(callback.from_user.id, VIEW_REPORTS):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        users = await UserService(session).list_all()
    lines = ['خروجی کاربران ربات', '=' * 60, f'تعداد کل: {len(users)}', '']
    lines.extend(_user_line(user) for user in users)
    content = '\n'.join(lines)
    if len(content) < 3500:
        await callback.message.answer(content)
    file = BufferedInputFile(content.encode('utf-8'), filename='bot_users.txt')
    await callback.message.answer_document(file, caption='📄 خروجی لیست کاربران')


@router.callback_query(F.data.in_({'admin:users:block', 'admin:users:unblock'}))
async def users_block_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has(callback.from_user.id, MANAGE_ADMINS):
        await callback.message.answer('دسترسی نداری.')
        return
    action = 'block' if callback.data.endswith(':block') else 'unblock'
    await state.set_state(AdminManageStates.waiting_user_identifier)
    await state.update_data(user_action=action)
    await callback.message.answer('آیدی عددی تلگرام، یوزرنیم یا شماره تلفن کاربر را بفرست:')


@router.message(AdminManageStates.waiting_user_identifier)
async def users_block_apply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get('user_action')
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(message.from_user.id, MANAGE_ADMINS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        service = UserService(session)
        user = await service.find(message.text or '')
        if not user:
            await message.answer('کاربر پیدا نشد.')
            return
        blocked = action == 'block'
        user = await service.set_blocked(user, blocked)
        await AdminService(session).log(message.from_user.id, 'block_user' if blocked else 'unblock_user', 'user', str(user.id))
    await state.clear()
    await message.answer(('کاربر مسدود شد ✅' if blocked else 'مسدودی کاربر رفع شد ✅') + f'\n{_user_line(user)}')


@router.callback_query(F.data == 'admin:users:wallet_charge')
async def wallet_charge_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has(callback.from_user.id, MANAGE_PAYMENTS):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.set_state(AdminManageStates.waiting_wallet_user_identifier)
    await callback.message.answer('برای شارژ دستی کیف پول، آیدی عددی تلگرام، یوزرنیم یا شماره تلفن کاربر را بفرست:')


@router.message(AdminManageStates.waiting_wallet_user_identifier)
async def wallet_charge_user(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(message.from_user.id, MANAGE_PAYMENTS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        user = await UserService(session).find(message.text or '')
        if not user:
            await message.answer('کاربر پیدا نشد.')
            return
    await state.update_data(wallet_user_identifier=message.text or '', wallet_user_id=user.id)
    await state.set_state(AdminManageStates.waiting_wallet_amount)
    await message.answer(f'کاربر پیدا شد:\n{_user_line(user)}\n\nمبلغ شارژ کیف پول را به تومان بفرست:')


@router.message(AdminManageStates.waiting_wallet_amount)
async def wallet_charge_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = Decimal((message.text or '').replace(',', '').strip())
        if amount <= 0:
            raise InvalidOperation
    except Exception:
        await message.answer('مبلغ معتبر نیست. فقط عدد مثبت بفرست.')
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(message.from_user.id, MANAGE_PAYMENTS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        user = await session.get(User, int(data['wallet_user_id']))
        if not user:
            await message.answer('کاربر پیدا نشد.')
            await state.clear()
            return
        user = await UserService(session).add_wallet(user, amount)
        texts = await SettingsService(session).get('texts')
        await AdminService(session).log(message.from_user.id, 'manual_wallet_charge', 'user', str(user.id), {'amount': str(amount)})
        notify_text = (texts.get('manual_wallet_charge') or 'کیف پول شما شارژ شد: {amount}').format(amount=money(amount), balance=money(user.wallet_balance or 0))
    try:
        await message.bot.send_message(user.telegram_id, notify_text)
    except Exception:
        pass
    await state.clear()
    await message.answer(f'کیف پول کاربر شارژ شد ✅\n{_user_line(user)}')
