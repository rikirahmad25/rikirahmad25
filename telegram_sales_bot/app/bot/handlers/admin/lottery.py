from __future__ import annotations

import random
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards.admin import lottery_keyboard
from app.bot.states.admin import AdminLotteryStates
from app.core.permissions import MANAGE_LOTTERIES
from app.db.models import User
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.text import money

router = Router(name='admin_lottery')


async def _guard(telegram_id: int) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, MANAGE_LOTTERIES)


def _winner_line(user: User, amount: Decimal) -> str:
    name = ' '.join(part for part in [user.first_name, user.last_name] if part) or '—'
    return f'{name} | @{user.username or "—"} | {user.telegram_id} | هدیه کیف پول: {money(amount)}'


@router.callback_query(F.data == 'admin:lottery')
async def lottery_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        features = await SettingsService(session).get('features')
    await callback.message.answer(
        '🎁 قرعه‌کشی\n\nمی‌توانی از بین کاربران فعال ربات برنده انتخاب کنی و در صورت نیاز کیف پولشان را شارژ کنی.',
        reply_markup=lottery_keyboard(bool(features.get('lottery_enabled', True))),
    )


@router.callback_query(F.data == 'admin:lottery:toggle')
async def lottery_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        features = await service.get('features')
        features['lottery_enabled'] = not bool(features.get('lottery_enabled', True))
        await service.set('features', features)
        await AdminService(session).log(callback.from_user.id, 'toggle_lottery', 'settings', 'features')
    await callback.message.answer('وضعیت قرعه‌کشی ذخیره شد ✅', reply_markup=lottery_keyboard(bool(features.get('lottery_enabled', True))))


@router.callback_query(F.data == 'admin:lottery:draw')
async def lottery_draw_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        features = await SettingsService(session).get('features')
    if not features.get('lottery_enabled', True):
        await callback.message.answer('قرعه‌کشی غیرفعال است. اول فعالش کن.')
        return
    await state.set_state(AdminLotteryStates.waiting_draw)
    await callback.message.answer(
        'اطلاعات قرعه‌کشی را با این فرمت بفرست:\n'
        'تعداد_برنده مبلغ_هدیه_کیف_پول متن_هدیه\n\n'
        'مثال:\n3 50000 هدیه قرعه‌کشی فروشگاه\n\n'
        'اگر نمی‌خواهی کیف پول شارژ شود، مبلغ را 0 بگذار.'
    )


@router.message(AdminLotteryStates.waiting_draw)
async def lottery_draw(message: Message, state: FSMContext) -> None:
    parts = (message.text or '').split(maxsplit=2)
    if len(parts) < 2:
        await message.answer('فرمت درست نیست.')
        return
    try:
        winners_count = int(parts[0])
        amount = Decimal(parts[1].replace(',', ''))
        if winners_count <= 0 or amount < 0:
            raise InvalidOperation
    except Exception:
        await message.answer('تعداد یا مبلغ معتبر نیست.')
        return
    prize_text = parts[2] if len(parts) >= 3 else 'هدیه قرعه‌کشی'
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(message.from_user.id, MANAGE_LOTTERIES):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        result = await session.execute(select(User).where(User.is_blocked.is_(False)))
        users = [u for u in result.scalars().all() if not (u.metadata_json or {}).get('bot_blocked')]
        if not users:
            await message.answer('کاربر فعالی برای قرعه‌کشی وجود ندارد.')
            return
        winners = random.sample(users, k=min(winners_count, len(users)))
        texts = await SettingsService(session).get('texts')
        for user in winners:
            if amount > 0:
                await UserService(session).add_wallet(user, amount)
            notify = (texts.get('lottery_win') or 'شما برنده قرعه‌کشی شدید.').format(
                prize_text=prize_text,
                amount=money(amount),
            )
            try:
                await message.bot.send_message(user.telegram_id, notify)
            except Exception:
                pass
        await AdminService(session).log(message.from_user.id, 'lottery_draw', 'users', str(len(winners)), {'amount': str(amount), 'prize_text': prize_text})
    await state.clear()
    lines = ['برندگان قرعه‌کشی', '=' * 40, f'متن هدیه: {prize_text}', f'مبلغ کیف پول: {money(amount)}', '']
    lines.extend(_winner_line(user, amount) for user in winners)
    content = '\n'.join(lines)
    file = BufferedInputFile(content.encode('utf-8'), filename='lottery_winners.txt')
    await message.answer('قرعه‌کشی انجام شد ✅\n' + '\n'.join(lines[:8]))
    await message.answer_document(file, caption='📄 خروجی برندگان قرعه‌کشی')
