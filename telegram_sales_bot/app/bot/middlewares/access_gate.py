from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.helpers import is_user_joined, should_require_phone
from app.bot.keyboards.user import join_channels_keyboard, phone_request_keyboard
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService


class AccessGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, 'from_user', None)
        if not from_user:
            return await handler(event, data)

        if isinstance(event, Message):
            text = event.text or ''
            if text.startswith('/start') or event.contact:
                return await handler(event, data)
        if isinstance(event, CallbackQuery):
            cb_data = event.data or ''
            if cb_data == 'check_join' or cb_data.startswith('admin:') or cb_data == 'noop':
                return await handler(event, data)

        async with SessionLocal() as session:
            admin_service = AdminService(session)
            if await admin_service.is_admin(from_user.id):
                return await handler(event, data)
            settings_service = SettingsService(session)
            texts = await settings_service.get('texts')
            channels_cfg = await settings_service.get('channels')
            menu = await settings_service.get('menu')
            user_service = UserService(session)
            user = await user_service.get_or_create(from_user.id, from_user.first_name, from_user.last_name, from_user.username)

        if user.is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer(texts.get('blocked_message') or 'دسترسی شما مسدود شده است.', show_alert=True)
            else:
                await event.answer(texts.get('blocked_message') or 'دسترسی شما مسدود شده است.')
            return None

        if not await is_user_joined(data['bot'], from_user.id):
            channels = channels_cfg.get('required_channels') or []
            if isinstance(event, CallbackQuery):
                await event.answer(texts.get('force_join_failed') or 'عضویت کامل نیست.', show_alert=True)
                await event.message.answer(texts.get('force_join_message') or 'ابتدا عضو کانال شوید.', reply_markup=join_channels_keyboard(channels))
            else:
                await event.answer(texts.get('force_join_message') or 'ابتدا عضو کانال شوید.', reply_markup=join_channels_keyboard(channels))
            return None

        if await should_require_phone(user):
            if isinstance(event, CallbackQuery):
                await event.answer(texts.get('force_phone_message') or 'شماره تلفن را ارسال کنید.', show_alert=True)
                await event.message.answer(texts.get('force_phone_message') or 'شماره تلفن را ارسال کنید.', reply_markup=phone_request_keyboard(menu))
            else:
                await event.answer(texts.get('force_phone_message') or 'شماره تلفن را ارسال کنید.', reply_markup=phone_request_keyboard(menu))
            return None

        return await handler(event, data)
