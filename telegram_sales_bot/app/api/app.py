from __future__ import annotations

import json
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Query, Request

from app.bootstrap import init_db
from app.config import get_settings
from app.core.enums import OrderStatus
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.delivery_service import DeliveryService
from app.services.discount_service import DiscountService
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.payments.plisio import PlisioProvider
from app.services.payments.zarinpal import ZarinPalProvider
from app.services.product_service import should_auto_deliver_after_payment
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService
from app.services.wallet_topup_service import WalletTopupService
from app.utils.text import money

settings = get_settings()
app = FastAPI(title='Telegram Sales Bot API')


@app.on_event('startup')
async def startup_event() -> None:
    await init_db()


@app.get('/health')
async def health() -> dict:
    return {'ok': True}


async def _send_order_payment_approved(bot, session, order) -> None:
    texts = await SettingsService(session).get('texts')
    await bot.send_message(
        order.user.telegram_id,
        (texts.get('payment_approved') or '✅ پرداخت سفارش {order_number} تایید شد و سفارش در مرحله پردازش قرار گرفت.').format(order_number=order.order_number),
    )


async def _notify_order_paid(bot, session, order, delivery_note: str = '') -> None:
    admin_title = '✅ سفارش پرداخت و خودکار تحویل شد' if order.status == OrderStatus.COMPLETED.value else '✅ سفارش پرداخت شد و در انتظار تکمیل است'
    admin_text = (
        f'{admin_title}\n'
        f'شماره سفارش: {order.order_number}\n'
        f'کاربر: {order.user.first_name or "—"} (@{order.user.username or "—"})\n'
        f'محصول: {order.product.title}\n'
        f'مبلغ: {money(order.amount)}'
        f'{delivery_note}'
    )
    await NotificationService(session).notify_admins(bot, admin_text)


async def _notify_topup_paid(bot, session, topup) -> None:
    texts = await SettingsService(session).get('texts')
    await bot.send_message(topup.user.telegram_id, (texts.get('wallet_charge_paid') or '✅ شارژ کیف پول به مبلغ {amount} تایید شد. موجودی فعلی: {balance}').format(amount=money(topup.amount), balance=money(topup.user.wallet_balance)))


@app.get('/payments/zarinpal/callback')
async def zarinpal_callback(Status: str | None = Query(default=None), Authority: str | None = Query(default=None)) -> dict:
    if not Authority:
        raise HTTPException(status_code=400, detail='Authority is required')
    async with SessionLocal() as session:
        from aiogram import Bot
        bot = Bot(token=settings.bot_token)
        try:
            order_service = OrderService(session)
            topup_service = WalletTopupService(session)
            order = await order_service.get_by_authority(Authority)
            topup = await topup_service.get_by_authority(Authority)
            if not order and not topup:
                raise HTTPException(status_code=404, detail='Payment not found')
            if (Status or '').lower() != 'ok':
                if order:
                    await order_service.mark_failed(order, note='Gateway callback status not ok')
                if topup:
                    await topup_service.mark_failed(topup, note='Gateway callback status not ok')
                return {'ok': False, 'message': 'Payment canceled or failed'}
            provider = ZarinPalProvider(session)
            amount = order.amount if order else topup.amount
            verification = await provider.verify_raw(Authority, amount)
            if not verification.success:
                if order:
                    await order_service.mark_failed(order, note=verification.message)
                if topup:
                    await topup_service.mark_failed(topup, note=verification.message)
                return {'ok': False, 'message': verification.message}
            if order:
                order = await order_service.mark_paid(order, verification.transaction_id)
                order.status = OrderStatus.PROCESSING.value
                await session.commit()
                await DiscountService(session).mark_order_redeemed(order)
                await ReferralService(session).register_commission(order, bot)
                await _send_order_payment_approved(bot, session, order)
                delivery_note = ''
                if should_auto_deliver_after_payment(order.product):
                    try:
                        success, delivery_message = await DeliveryService(session).deliver(bot, order)
                    except Exception as exc:
                        await session.rollback()
                        order = await order_service.get(order.id)
                        if order:
                            order.status = OrderStatus.PROCESSING.value
                            await session.commit()
                        success = False
                        delivery_message = str(exc)
                    if success:
                        await AdminService(session).log(0, 'complete_order', 'order', str(order.id), {'admin': 'سیستم (تحویل خودکار)'})
                        delivery_note = '\nوضعیت تحویل: اتوتکست به صورت خودکار تحویل شد.'
                    else:
                        delivery_note = f'\nوضعیت تحویل: تحویل خودکار انجام نشد و سفارش منتظر پردازش ماند. علت: {delivery_message}'
                await _notify_order_paid(bot, session, order, delivery_note)
                return {'ok': True, 'message': 'Payment verified', 'order_number': order.order_number}
            topup = await topup_service.mark_paid(topup, verification.transaction_id)
            await _notify_topup_paid(bot, session, topup)
            return {'ok': True, 'message': 'Wallet topup verified', 'topup_number': topup.topup_number}
        finally:
            await bot.session.close()


@app.post('/payments/plisio/callback')
async def plisio_callback(request: Request) -> dict:
    content_type = request.headers.get('content-type', '')
    raw_body = await request.body()
    if 'application/json' in content_type:
        payload = json.loads(raw_body.decode('utf-8') or '{}')
    else:
        payload = dict(parse_qsl(raw_body.decode('utf-8'), keep_blank_values=True))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Invalid payload')
    txn_id = str(payload.get('txn_id') or '')
    order_number = str(payload.get('order_number') or '')
    status = str(payload.get('status') or '').lower()
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('plisio')
        if cfg.get('verify_callback', True):
            if not PlisioProvider.verify_callback_hash(payload, str(cfg.get('api_key') or '')):
                raise HTTPException(status_code=422, detail='Invalid Plisio signature')
        order_service = OrderService(session)
        topup_service = WalletTopupService(session)
        order = await order_service.get_by_authority(txn_id) if txn_id else None
        topup = await topup_service.get_by_authority(txn_id) if txn_id else None
        if not order and not topup and order_number:
            order = await order_service.get_by_number(order_number)
            topup = await topup_service.get_by_number(order_number)
        if not order and not topup:
            raise HTTPException(status_code=404, detail='Order/topup not found')
        from aiogram import Bot
        bot = Bot(token=settings.bot_token)
        try:
            if status == 'completed':
                if order:
                    order = await order_service.mark_paid(order, transaction_id=txn_id or order_number)
                    order.status = OrderStatus.PROCESSING.value
                    await session.commit()
                    await DiscountService(session).mark_order_redeemed(order)
                    await ReferralService(session).register_commission(order, bot)
                    await _send_order_payment_approved(bot, session, order)
                    delivery_note = ''
                    if should_auto_deliver_after_payment(order.product):
                        try:
                            success, delivery_message = await DeliveryService(session).deliver(bot, order)
                        except Exception as exc:
                            await session.rollback()
                            order = await order_service.get(order.id)
                            if order:
                                order.status = OrderStatus.PROCESSING.value
                                await session.commit()
                            success = False
                            delivery_message = str(exc)
                        if success:
                            await AdminService(session).log(0, 'complete_order', 'order', str(order.id), {'admin': 'سیستم (تحویل خودکار)'})
                            delivery_note = '\nوضعیت تحویل: اتوتکست به صورت خودکار تحویل شد.'
                        else:
                            delivery_note = f'\nوضعیت تحویل: تحویل خودکار انجام نشد و سفارش منتظر پردازش ماند. علت: {delivery_message}'
                    await _notify_order_paid(bot, session, order, delivery_note)
                    return {'ok': True, 'message': 'Order payment completed', 'order_number': order.order_number}
                topup = await topup_service.mark_paid(topup, transaction_id=txn_id or order_number)
                await _notify_topup_paid(bot, session, topup)
                return {'ok': True, 'message': 'Wallet topup completed', 'topup_number': topup.topup_number}
            if status in {'cancelled duplicate'}:
                return {'ok': True, 'message': 'Duplicate invoice ignored'}
            if status in {'expired', 'cancelled', 'error'}:
                if order:
                    await order_service.mark_failed(order, note=f'Plisio status: {status}')
                if topup:
                    await topup_service.mark_failed(topup, note=f'Plisio status: {status}')
                return {'ok': False, 'message': f'Plisio status: {status}'}
            return {'ok': True, 'message': f'Plisio status: {status or "unknown"}'}
        finally:
            await bot.session.close()
