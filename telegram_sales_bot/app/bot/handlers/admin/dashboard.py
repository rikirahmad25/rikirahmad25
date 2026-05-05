from __future__ import annotations

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from app.bot.keyboards.admin import dashboard_keyboard
from app.core.permissions import VIEW_REPORTS
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.analytics_service import AnalyticsService
from app.services.settings_service import SettingsService
from app.utils.text import money

router = Router(name='admin_dashboard')


async def _has_report_access(telegram_id: int) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, VIEW_REPORTS)


@router.callback_query(F.data == 'admin:dashboard')
async def admin_dashboard(callback: CallbackQuery) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, VIEW_REPORTS):
            await callback.message.answer('دسترسی نداری.')
            return
        data = await AnalyticsService(session).dashboard()
        reports = await SettingsService(session).get('reports')
    best = '\n'.join([f"• {row['title']} ({row['cnt']})" for row in data['best_sellers']]) or '—'
    text = (
        '📊 داشبورد\n\n'
        f"تعداد فروش 24 ساعت: {data['sales_day']} | مبلغ: {money(data['sales_day_amount'])}\n"
        f"تعداد فروش 7 روز: {data['sales_week']} | مبلغ: {money(data['sales_week_amount'])}\n"
        f"تعداد فروش 30 روز: {data['sales_month']} | مبلغ: {money(data['sales_month_amount'])}\n"
        f"💰 فروش کل: {money(data['sales_total_amount'])}\n"
        f"کاربر جدید 24 ساعت: {data['new_users_day']}\n\n"
        f'پرفروش‌ها:\n{best}'
    )
    await callback.message.answer(text, reply_markup=dashboard_keyboard(bool(reports.get('daily_sales_enabled'))))


@router.callback_query(F.data == 'admin:dashboard:export_today')
async def dashboard_export_today(callback: CallbackQuery) -> None:
    await callback.answer('در حال ساخت خروجی')
    if not await _has_report_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        analytics = AnalyticsService(session)
        reports = await SettingsService(session).get('reports')
        text = await analytics.daily_sales_report(tz_name=reports.get('timezone') or 'Europe/Istanbul')
    file = BufferedInputFile(text.encode('utf-8'), filename='daily_sales_today.txt')
    await callback.message.answer_document(file, caption='📄 خروجی حساب امروز')


@router.callback_query(F.data == 'admin:dashboard:daily_toggle')
async def dashboard_daily_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, VIEW_REPORTS):
            await callback.message.answer('دسترسی نداری.')
            return
        settings_service = SettingsService(session)
        reports = await settings_service.get('reports')
        reports['daily_sales_enabled'] = not bool(reports.get('daily_sales_enabled'))
        await settings_service.set('reports', reports)
        await admin_service.log(callback.from_user.id, 'toggle_daily_sales_report', 'settings', 'reports', {'enabled': reports['daily_sales_enabled']})
    await callback.message.answer(
        'ارسال روزانه حساب روشن شد ✅ گزارش هر روز آخر شب به ادمین‌ها ارسال می‌شود.'
        if reports['daily_sales_enabled']
        else 'ارسال روزانه حساب خاموش شد ❌',
        reply_markup=dashboard_keyboard(bool(reports.get('daily_sales_enabled'))),
    )
