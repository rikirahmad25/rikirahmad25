from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.bot.filters import MenuTextFilter
from app.bot.keyboards.user import support_keyboard
from app.db.session import SessionLocal
from app.services.settings_service import SettingsService

router = Router(name='support')


@router.message(MenuTextFilter('support', '☎️ پشتیبانی'))
async def support_entry(message: Message) -> None:
    async with SessionLocal() as session:
        settings_service = SettingsService(session)
        support = await settings_service.get('support')
        texts = await settings_service.get('texts')
    username = support.get('support_username') or ''
    text = texts.get('support_text') or 'برای ارتباط با پشتیبانی روی دکمه زیر بزن.'
    if not username:
        await message.answer('آیدی پشتیبانی هنوز در تنظیمات ثبت نشده است.')
        return
    await message.answer(text, reply_markup=support_keyboard(username))
