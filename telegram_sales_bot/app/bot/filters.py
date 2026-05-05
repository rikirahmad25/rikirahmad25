from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import Message

from app.db.session import SessionLocal
from app.services.settings_service import SettingsService


class MenuTextFilter(Filter):
    def __init__(self, key: str, fallback: str):
        self.key = key
        self.fallback = fallback

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        async with SessionLocal() as session:
            labels = await SettingsService(session).get('menu')
        return message.text == labels.get(self.key, self.fallback) or message.text == self.fallback
