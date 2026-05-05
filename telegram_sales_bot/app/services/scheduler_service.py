from __future__ import annotations

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.db.session import SessionLocal
from app.services.analytics_service import AnalyticsService
from app.services.backup_service import BackupService
from app.services.order_service import OrderService

settings = get_settings()
scheduler = AsyncIOScheduler(timezone='UTC')


async def cancel_unpaid_orders_job() -> None:
    async with SessionLocal() as session:
        await OrderService(session).auto_cancel_unpaid(settings.order_auto_cancel_minutes)


async def scheduled_backup_job(bot: Bot) -> None:
    async with SessionLocal() as session:
        await BackupService(session).maybe_send_scheduled_backup(bot)


async def scheduled_daily_sales_report_job(bot: Bot) -> None:
    async with SessionLocal() as session:
        await AnalyticsService(session).maybe_send_daily_sales_report(bot)


def setup_scheduler(bot: Bot | None = None) -> AsyncIOScheduler:
    if scheduler.running:
        return scheduler
    scheduler.add_job(cancel_unpaid_orders_job, 'interval', minutes=5, id='cancel_unpaid_orders')
    if bot is not None:
        scheduler.add_job(scheduled_backup_job, 'interval', minutes=10, id='scheduled_backup', args=[bot])
        scheduler.add_job(scheduled_daily_sales_report_job, 'interval', minutes=10, id='scheduled_daily_sales_report', args=[bot])
    scheduler.start()
    return scheduler
