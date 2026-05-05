from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.keyboards.admin import broadcast_menu_keyboard
from app.bot.states.admin import AdminBroadcastStates
from app.core.permissions import MANAGE_BROADCASTS
from app.db.models import User
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService

router = Router(name='admin_broadcasts')


async def _notify_bot_blocked(bot, session, user: User) -> None:
    meta = dict(user.metadata_json or {})
    meta['bot_blocked'] = True
    if meta.get('bot_blocked_notified'):
        user.metadata_json = meta
        await session.commit()
        return
    notifications = await SettingsService(session).get('notifications')
    if not notifications.get('user_blocked_bot_enabled', True):
        meta['bot_blocked_notified'] = True
        user.metadata_json = meta
        await session.commit()
        return
    texts = await SettingsService(session).get('texts')
    name = ' '.join(part for part in [user.first_name, user.last_name] if part) or '—'
    text = (texts.get('user_blocked_bot_admin_notification') or 'کاربر ربات را بلاک کرد: {telegram_id}').format(
        name=name,
        username=f'@{user.username}' if user.username else '—',
        telegram_id=user.telegram_id,
    )
    meta['bot_blocked_notified'] = True
    user.metadata_json = meta
    await session.commit()
    await NotificationService(session).notify_admins(bot, text)


@router.callback_query(F.data == 'admin:broadcasts')
async def broadcast_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_BROADCASTS):
            await callback.message.answer('دسترسی نداری.')
            return
    await state.clear()
    await callback.message.answer('📣 بخش ارسال پیام\n\nنوع ارسال را انتخاب کن:', reply_markup=broadcast_menu_keyboard())


@router.callback_query(F.data == 'admin:broadcasts:all')
async def broadcast_all_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_BROADCASTS):
            await callback.message.answer('دسترسی نداری.')
            return
    await state.set_state(AdminBroadcastStates.waiting_content)
    await callback.message.answer('پیام همگانی را بفرست. می‌تواند متن، عکس با کپشن یا ویدیو با کپشن باشد. برای همه کاربران ثبت‌شده ارسال می‌شود.')


@router.callback_query(F.data == 'admin:broadcasts:direct')
async def direct_message_target_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_BROADCASTS):
            await callback.message.answer('دسترسی نداری.')
            return
    await state.set_state(AdminBroadcastStates.waiting_direct_target)
    await callback.message.answer('آیدی عددی تلگرام، یوزرنیم یا شماره تلفن عضوی که می‌خواهی پیام بگیرد را بفرست:')


@router.message(AdminBroadcastStates.waiting_content)
async def send_broadcast(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(message.from_user.id, MANAGE_BROADCASTS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        result = await session.execute(select(User).order_by(User.id.asc()))
        users = [user for user in result.scalars().all() if not user.is_blocked]
        sent = 0
        failed = 0
        blocked = 0
        text = message.text or message.caption or ''
        photo_id = message.photo[-1].file_id if message.photo else None
        video_id = message.video.file_id if message.video else None
        for user in users:
            try:
                if photo_id:
                    await message.bot.send_photo(user.telegram_id, photo=photo_id, caption=text[:1024] if text else None)
                elif video_id:
                    await message.bot.send_video(user.telegram_id, video=video_id, caption=text[:1024] if text else None)
                else:
                    await message.bot.send_message(user.telegram_id, text or ' ')
                sent += 1
            except TelegramForbiddenError:
                blocked += 1
                failed += 1
                await _notify_bot_blocked(message.bot, session, user)
            except Exception:
                failed += 1
        await admin_service.log(message.from_user.id, 'broadcast', 'users', str(sent), {'text': text[:100], 'failed': failed, 'blocked': blocked})
    await state.clear()
    await message.answer(f'ارسال همگانی انجام شد.\nارسال موفق: {sent}\nناموفق: {failed}\nبلاک/حذف ربات: {blocked}')



def _direct_user_line(user: User) -> str:
    name = ' '.join(part for part in [user.first_name, user.last_name] if part) or '—'
    username = f'@{user.username}' if user.username else '—'
    return f'{name} | {username} | TelegramID: {user.telegram_id} | Phone: {user.phone_number or "—"}'


@router.message(AdminBroadcastStates.waiting_direct_target)
async def direct_message_target(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(message.from_user.id, MANAGE_BROADCASTS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        user = await UserService(session).find(message.text or '')
        if not user or user.is_blocked:
            await message.answer('کاربر پیدا نشد یا در ربات مسدود است. دوباره شناسه معتبر بفرست:')
            return
    await state.update_data(direct_user_id=user.id, direct_user_telegram_id=user.telegram_id)
    await state.set_state(AdminBroadcastStates.waiting_direct_content)
    await message.answer(f'کاربر انتخاب شد:\n{_direct_user_line(user)}\n\nحالا پیامی که باید فقط برای همین عضو ارسال شود را بفرست. متن، عکس، ویدیو یا فایل پشتیبانی می‌شود.')


@router.message(AdminBroadcastStates.waiting_direct_content)
async def send_direct_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user_id = int(data.get('direct_user_id') or 0)
    telegram_id = int(data.get('direct_user_telegram_id') or 0)
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(message.from_user.id, MANAGE_BROADCASTS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        user = await session.get(User, user_id)
        if not user or user.telegram_id != telegram_id:
            await message.answer('کاربر مقصد پیدا نشد. ارسال لغو شد.')
            await state.clear()
            return
        text = message.text or message.caption or ''
        photo_id = message.photo[-1].file_id if message.photo else None
        video_id = message.video.file_id if message.video else None
        document_id = message.document.file_id if message.document else None
        try:
            if photo_id:
                await message.bot.send_photo(user.telegram_id, photo=photo_id, caption=text[:1024] if text else None)
            elif video_id:
                await message.bot.send_video(user.telegram_id, video=video_id, caption=text[:1024] if text else None)
            elif document_id:
                await message.bot.send_document(user.telegram_id, document=document_id, caption=text[:1024] if text else None)
            else:
                await message.bot.send_message(user.telegram_id, text or ' ')
            await admin_service.log(message.from_user.id, 'direct_message', 'user', str(user.id), {'text': text[:100]})
            await state.clear()
            await message.answer(f'پیام فقط برای این عضو ارسال شد ✅\n{_direct_user_line(user)}')
        except TelegramForbiddenError:
            await _notify_bot_blocked(message.bot, session, user)
            await state.clear()
            await message.answer('ارسال انجام نشد؛ این کاربر ربات را بلاک کرده یا چت در دسترس نیست.')
        except Exception as exc:
            await state.clear()
            await message.answer(f'ارسال انجام نشد: {exc}')
