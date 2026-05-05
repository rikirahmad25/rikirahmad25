from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import OrderStatus
from app.db.models import AdminActivity, Order, Product, User
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService
from app.utils.text import money


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def dashboard(self) -> dict:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        async def count_orders(since):
            result = await self.session.execute(
                select(func.count(Order.id)).where(Order.completed_at >= since, Order.status == OrderStatus.COMPLETED.value)
            )
            return result.scalar() or 0

        async def sum_orders(since=None):
            stmt = select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == OrderStatus.COMPLETED.value)
            if since is not None:
                stmt = stmt.where(Order.completed_at >= since)
            result = await self.session.execute(stmt)
            return Decimal(str(result.scalar() or 0))

        async def count_users(since):
            result = await self.session.execute(select(func.count(User.id)).where(User.created_at >= since))
            return result.scalar() or 0

        best_sellers_result = await self.session.execute(
            select(Product.title, func.count(Order.id).label('cnt'))
            .join(Order, Order.product_id == Product.id)
            .where(Order.status == OrderStatus.COMPLETED.value)
            .group_by(Product.title)
            .order_by(func.count(Order.id).desc())
            .limit(5)
        )
        return {
            'sales_day': await count_orders(day_ago),
            'sales_week': await count_orders(week_ago),
            'sales_month': await count_orders(month_ago),
            'sales_day_amount': await sum_orders(day_ago),
            'sales_week_amount': await sum_orders(week_ago),
            'sales_month_amount': await sum_orders(month_ago),
            'sales_total_amount': await sum_orders(None),
            'new_users_day': await count_users(day_ago),
            'best_sellers': [dict(row._mapping) for row in best_sellers_result],
        }

    async def daily_sales_report(self, report_date: date | None = None, tz_name: str = 'Europe/Istanbul') -> str:
        tz = ZoneInfo(tz_name or 'Europe/Istanbul')
        today = report_date or datetime.now(tz).date()
        start_local = datetime.combine(today, time.min, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        result = await self.session.execute(
            select(Order)
            .where(Order.status == OrderStatus.COMPLETED.value)
            .options(selectinload(Order.user), selectinload(Order.product))
            .order_by(Order.completed_at.asc(), Order.id.asc())
        )
        orders = [
            order
            for order in result.scalars().all()
            if order.completed_at and start_utc <= _as_aware_utc(order.completed_at) < end_utc
        ]
        order_ids = [str(order.id) for order in orders]
        delivered_by: dict[str, str] = {}
        if order_ids:
            acts_result = await self.session.execute(
                select(AdminActivity)
                .where(
                    AdminActivity.action == 'complete_order',
                    AdminActivity.target_type == 'order',
                    AdminActivity.target_id.in_(order_ids),
                )
                .order_by(AdminActivity.id.desc())
            )
            for act in acts_result.scalars().all():
                if act.target_id and act.target_id not in delivered_by:
                    delivered_by[act.target_id] = (act.details or {}).get('admin') or str(act.admin_telegram_id)

        lines = [
            f'گزارش حساب روزانه - {today.isoformat()}',
            '=' * 60,
            '',
        ]
        if not orders:
            lines.append('برای این روز سفارش تکمیل‌شده‌ای ثبت نشده است.')
            return '\n'.join(lines)

        total = Decimal('0')
        summary: dict[str, dict[str, Decimal | int]] = {}
        for idx, order in enumerate(orders, start=1):
            amount = Decimal(str(order.amount or 0))
            total += amount
            product_title = order.product.title if order.product else 'محصول حذف‌شده'
            bucket = summary.setdefault(product_title, {'count': 0, 'amount': Decimal('0')})
            bucket['count'] = int(bucket['count']) + 1
            bucket['amount'] = Decimal(str(bucket['amount'])) + amount
            completed_at = order.completed_at
            if completed_at:
                completed_at = _as_aware_utc(completed_at).astimezone(tz)
            user = order.user
            lines.extend([
                f'{idx}. سفارش: {order.order_number}',
                f'   سرویس/محصول: {product_title}',
                f'   مبلغ: {money(amount)}',
                f'   مشتری: {(user.first_name if user else None) or "—"} (@{(user.username if user else None) or "—"}) | آیدی: {(user.telegram_id if user else "—")}',
                f'   تحویل‌دهنده: {delivered_by.get(str(order.id), "—")}',
                f'   زمان تکمیل: {completed_at.strftime("%Y-%m-%d %H:%M") if completed_at else "—"}',
                '-' * 60,
            ])

        lines.extend(['', 'جمع‌بندی سرویس‌ها:', '-' * 60])
        for title, info in summary.items():
            lines.append(f'• {title}: {info["count"]} فروش | جمع مبلغ: {money(info["amount"])}')
        lines.extend(['', f'جمع کل فروش روز: {money(total)}'])
        return '\n'.join(lines)

    async def maybe_send_daily_sales_report(self, bot: Bot) -> bool:
        settings_service = SettingsService(self.session)
        reports = await settings_service.get('reports')
        if not reports.get('daily_sales_enabled'):
            return False
        tz_name = reports.get('timezone') or 'Europe/Istanbul'
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        raw_time = str(reports.get('daily_sales_time') or '23:55')
        try:
            hour, minute = [int(part) for part in raw_time.split(':', 1)]
        except Exception:
            hour, minute = 23, 55
        send_time = time(hour=min(max(hour, 0), 23), minute=min(max(minute, 0), 59))
        if now.time() < send_time:
            return False
        today = now.date().isoformat()
        if reports.get('last_daily_sales_date') == today:
            return False

        text = await self.daily_sales_report(now.date(), tz_name=tz_name)
        admin_ids = await AdminService(self.session).get_admin_telegram_ids()
        for admin_id in admin_ids:
            try:
                file = BufferedInputFile(text.encode('utf-8'), filename=f'daily_sales_{today}.txt')
                await bot.send_document(admin_id, file, caption=f'📄 گزارش حساب روزانه {today}')
            except Exception:
                pass
        reports['last_daily_sales_date'] = today
        await settings_service.set('reports', reports)
        return True
