from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService


class AntiSpamMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, 'from_user', None)
        if not user:
            return await handler(event, data)

        async with SessionLocal() as session:
            admin_service = AdminService(session)
            if await admin_service.is_admin(user.id):
                return await handler(event, data)
            cfg = await SettingsService(session).get('anti_spam')

        if not cfg.get('enabled', True):
            return await handler(event, data)

        now = time.monotonic()
        blocked_until = self._blocked_until.get(user.id, 0)
        if blocked_until > now:
            await self._warn(event, cfg.get('warn_text'))
            return None

        window_seconds = int(cfg.get('window_seconds') or 10)
        max_messages = int(cfg.get('max_messages') or 8)
        block_seconds = int(cfg.get('block_seconds') or 30)
        bucket = self._events[user.id]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        bucket.append(now)
        if len(bucket) > max_messages:
            self._blocked_until[user.id] = now + block_seconds
            bucket.clear()
            await self._warn(event, cfg.get('warn_text'))
            return None

        return await handler(event, data)

    @staticmethod
    async def _warn(event: TelegramObject, text: str | None) -> None:
        message = text or 'لطفاً کمی آرام‌تر پیام بفرستید و چند ثانیه بعد دوباره تلاش کنید.'
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(message, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(message)
        except Exception:
            pass
