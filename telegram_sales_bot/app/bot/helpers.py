from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from app.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.settings_service import SettingsService

settings = get_settings()


async def is_user_joined(bot: Bot, telegram_id: int) -> bool:
    async with SessionLocal() as session:
        channels_cfg = await SettingsService(session).get('channels')
    if not channels_cfg.get('enabled'):
        return True
    channels = channels_cfg.get('required_channels') or []
    if not channels:
        return True
    for channel in channels:
        chat_id = channel.strip()
        if chat_id.startswith('https://t.me/') or chat_id.startswith('http://t.me/'):
            chat_id = '@' + chat_id.rstrip('/').split('/')[-1]
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=telegram_id)
            if member.status in {'left', 'kicked'}:
                return False
        except (TelegramBadRequest, TelegramForbiddenError):
            return False
    return True


async def should_require_phone(user: User | None) -> bool:
    async with SessionLocal() as session:
        phone_cfg = await SettingsService(session).get('phone_verification')
    if not phone_cfg.get('enabled'):
        return False
    if not user:
        return True
    return not bool(user.is_phone_verified and user.phone_number)
