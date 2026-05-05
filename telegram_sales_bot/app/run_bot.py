from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.router import build_dispatcher
from app.bootstrap import init_db
from app.config import get_settings
from app.services.scheduler_service import setup_scheduler

logging.basicConfig(level=logging.INFO)
settings = get_settings()


async def main() -> None:
    await init_db()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    setup_scheduler(bot)
    dp = build_dispatcher()
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
