from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.models import Order, Payment, WalletTopup
from app.services.payments.base import PaymentInitResult, PaymentProvider, PaymentVerifyResult
from app.services.settings_service import SettingsService

settings = get_settings()


class ZarinPalProvider(PaymentProvider):
    slug = 'zarinpal'
    title = 'زرین پال'
    request_url = 'https://api.zarinpal.com/pg/v4/payment/request.json'
    verify_url = 'https://api.zarinpal.com/pg/v4/payment/verify.json'
    pay_url = 'https://www.zarinpal.com/pg/StartPay/'

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings_service = SettingsService(session)

    async def _config(self) -> dict:
        cfg = await self.settings_service.get('zarinpal')
        return {
            'merchant_id': cfg.get('merchant_id') or settings.zarinpal_merchant_id,
            'callback_url': cfg.get('callback_url') or settings.zarinpal_callback_url,
        }

    async def create_payment(self, order: Order) -> PaymentInitResult:
        cfg = await self._config()
        if not cfg.get('merchant_id') or not cfg.get('callback_url'):
            return PaymentInitResult(success=False, message='تنظیمات زرین‌پال کامل نیست.')

        payload = {
            'merchant_id': cfg['merchant_id'],
            'amount': int(order.amount),
            'description': f'Order {order.order_number}',
            'callback_url': cfg['callback_url'],
            'metadata': {
                'order_number': order.order_number,
                'telegram_id': str(order.user.telegram_id if order.user else ''),
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.request_url, json=payload)
            data = response.json()
        authority = (data.get('data') or {}).get('authority')
        if not authority:
            return PaymentInitResult(success=False, message=str(data))

        order.payment_method = PaymentMethod.ZARINPAL.value
        order.status = OrderStatus.WAITING_FOR_PAYMENT.value
        payment = Payment(
            order_id=order.id,
            method=PaymentMethod.ZARINPAL.value,
            status=PaymentStatus.PENDING_VERIFY.value,
            amount=order.amount,
            authority=authority,
            metadata_json=data,
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return PaymentInitResult(success=True, message='لینک پرداخت ساخته شد.', payment=payment, payment_url=f'{self.pay_url}{authority}', extra={'authority': authority})

    async def create_wallet_topup(self, topup: WalletTopup) -> PaymentInitResult:
        cfg = await self._config()
        if not cfg.get('merchant_id') or not cfg.get('callback_url'):
            return PaymentInitResult(success=False, message='تنظیمات زرین‌پال کامل نیست.')
        payload = {
            'merchant_id': cfg['merchant_id'],
            'amount': int(topup.amount),
            'description': f'Wallet topup {topup.topup_number}',
            'callback_url': cfg['callback_url'],
            'metadata': {'topup_number': topup.topup_number},
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.request_url, json=payload)
            data = response.json()
        authority = (data.get('data') or {}).get('authority')
        if not authority:
            return PaymentInitResult(success=False, message=str(data))
        topup.method = PaymentMethod.ZARINPAL.value
        topup.status = PaymentStatus.PENDING_VERIFY.value
        topup.authority = authority
        topup.metadata_json = {'zarinpal': data}
        await self.session.commit()
        return PaymentInitResult(success=True, message='لینک پرداخت ساخته شد.', payment_url=f'{self.pay_url}{authority}', extra={'authority': authority})

    async def _payment_for_authority(self, authority: str):
        result = await self.session.execute(select(Payment).where(Payment.authority == authority))
        payment = result.scalar_one_or_none()
        if payment:
            return payment.amount
        result = await self.session.execute(select(WalletTopup).where(WalletTopup.authority == authority))
        topup = result.scalar_one_or_none()
        return topup.amount if topup else None

    async def verify(self, authority: str, payload: dict | None = None) -> PaymentVerifyResult:
        amount = await self._payment_for_authority(authority)
        if amount is None:
            return PaymentVerifyResult(success=False, message='پرداخت پیدا نشد.', authority=authority)
        return await self.verify_raw(authority, amount)

    async def verify_raw(self, authority: str, amount) -> PaymentVerifyResult:
        cfg = await self._config()
        if not cfg.get('merchant_id'):
            return PaymentVerifyResult(success=False, message='مرچنت آی‌دی زرین‌پال تنظیم نشده است.', authority=authority)
        request_body = {
            'merchant_id': cfg['merchant_id'],
            'amount': int(amount),
            'authority': authority,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.verify_url, json=request_body)
            data = response.json()
        verified = (data.get('data') or {}).get('code') in {100, 101}
        ref_id = str((data.get('data') or {}).get('ref_id') or '')
        return PaymentVerifyResult(
            success=verified,
            message='پرداخت تایید شد.' if verified else str(data),
            transaction_id=ref_id or None,
            authority=authority,
            extra=data,
        )
