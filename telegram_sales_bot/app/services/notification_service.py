from __future__ import annotations

import asyncio

import aiosmtplib
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.admin_service import AdminService

settings = get_settings()


class NotificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.admin_service = AdminService(session)

    async def notify_admins(self, bot: Bot, text: str) -> None:
        admin_ids = await self.admin_service.get_admin_telegram_ids()
        tasks = [bot.send_message(chat_id=admin_id, text=text) for admin_id in admin_ids]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_admin_email(self, subject: str, body: str) -> None:
        if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password or not settings.smtp_from:
            return
        message = f'Subject: {subject}\nFrom: {settings.smtp_from}\nTo: {settings.smtp_username}\n\n{body}'
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=True,
        )
