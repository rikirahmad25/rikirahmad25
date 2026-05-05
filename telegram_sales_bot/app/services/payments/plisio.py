from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.models import Order, Payment, WalletTopup
from app.services.crypto_rate_service import fetch_nobitex_toman_prices
from app.services.payments.base import PaymentInitResult, PaymentProvider, PaymentVerifyResult
from app.services.settings_service import SettingsService


class PlisioRateUnavailable(RuntimeError):
    def __init__(self, message: str, meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.meta = meta or {}


class PlisioProvider(PaymentProvider):
    slug = 'plisio'
    title = 'Plisio'
    invoice_url = 'https://api.plisio.net/api/v1/invoices/new'

    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings_service = SettingsService(session)

    async def _config(self) -> dict[str, Any]:
        return await self.settings_service.get('plisio')

    @staticmethod
    def _as_decimal(value: Any, default: str = '0') -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal(default)

    @staticmethod
    def _format_rate(value: Decimal) -> str:
        if value == value.to_integral():
            return f'{int(value):,}'
        return f'{value:,.2f}'.rstrip('0').rstrip('.')

    def _manual_source_rate(self, cfg: dict[str, Any]) -> Decimal:
        rate = self._as_decimal(cfg.get('source_rate') or 1, '1')
        if rate <= 0:
            rate = Decimal('1')
        return rate

    async def _resolve_source_rate(self, cfg: dict[str, Any]) -> tuple[Decimal, dict[str, Any]]:
        manual_rate = self._manual_source_rate(cfg)
        source_currency = str(cfg.get('source_currency') or 'USD').upper().strip() or 'USD'
        auto_enabled = bool(cfg.get('auto_usdt_rate_enabled', False))
        fallback_enabled = bool(cfg.get('fallback_to_manual_rate_enabled', False))
        meta: dict[str, Any] = {
            'source_currency': source_currency,
            'manual_source_rate_toman': str(manual_rate),
            'manual_source_rate_toman_display': self._format_rate(manual_rate),
            'auto_usdt_rate_enabled': auto_enabled,
            'fallback_to_manual_rate_enabled': fallback_enabled,
            'rate_mode': 'manual',
            'rate_source': 'manual_source_rate',
        }
        if auto_enabled and source_currency == 'USD':
            meta['rate_mode'] = 'auto_usdt_nobitex'
            try:
                prices = await fetch_nobitex_toman_prices(['USDT'])
                auto_rate = prices.get('USDT')
                if auto_rate and auto_rate > 0:
                    meta.update({
                        'resolved_source_rate_toman': str(auto_rate),
                        'resolved_source_rate_toman_display': self._format_rate(auto_rate),
                        'rate_source': 'nobitex_usdt_toman',
                        'used_fallback_manual_rate': False,
                    })
                    return auto_rate, meta
                meta['rate_error'] = 'USDT rate was not returned by Nobitex.'
            except Exception as exc:
                meta['rate_error'] = f'{type(exc).__name__}: {exc}'
            if fallback_enabled:
                meta['rate_mode'] = 'auto_usdt_nobitex_fallback_manual'
                meta['rate_source'] = 'manual_source_rate_fallback'
                meta['used_fallback_manual_rate'] = True
            else:
                meta['rate_mode'] = 'auto_usdt_nobitex_failed'
                meta['rate_source'] = 'nobitex_usdt_toman'
                meta['used_fallback_manual_rate'] = False
                raise PlisioRateUnavailable(
                    'نرخ لحظه‌ای USDT از نوبیتکس دریافت نشد و پرداخت Plisio موقتاً متوقف است. لطفاً چند دقیقه بعد دوباره تلاش کن یا با پشتیبانی تماس بگیر.',
                    meta,
                )
        elif auto_enabled and source_currency != 'USD':
            meta['rate_warning'] = 'Auto Nobitex USDT rate is only used when source_currency is USD.'

        meta.setdefault('resolved_source_rate_toman', str(manual_rate))
        meta.setdefault('resolved_source_rate_toman_display', self._format_rate(manual_rate))
        meta.setdefault('used_fallback_manual_rate', False)
        return manual_rate, meta

    def _source_amount(self, amount: Decimal, rate: Decimal) -> str:
        if rate <= 0:
            rate = Decimal('1')
        value = (Decimal(str(amount)) / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return format(value, 'f')

    def _minimum_source_amount_result(self, source_amount: str, rate_meta: dict[str, Any], cfg: dict[str, Any]) -> PaymentInitResult | None:
        minimum_source_amount = Decimal('1.00')
        try:
            source_amount_decimal = Decimal(str(source_amount))
        except Exception:
            return None
        if source_amount_decimal > minimum_source_amount:
            return None
        extra: dict[str, Any] = {
            'error_code': 'plisio_min_amount',
            'source_amount': source_amount,
            'minimum_source_amount': format(minimum_source_amount, 'f'),
            'source_currency': str(rate_meta.get('source_currency') or cfg.get('source_currency') or 'USD').upper(),
            'source_rate': rate_meta,
        }
        extra.update(self._rate_extra(source_amount, rate_meta, cfg))
        return PaymentInitResult(
            success=False,
            message='حداقل واریز رمز ارز یک دلار است. لطفاً روش‌های دیگر را امتحان کنید.',
            extra=extra,
        )

    def _rate_extra(self, source_amount: str, rate_meta: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
        show_rate = bool(cfg.get('show_source_rate', False))
        rate_display = str(rate_meta.get('resolved_source_rate_toman_display') or rate_meta.get('resolved_source_rate_toman') or '')
        source_currency = str(rate_meta.get('source_currency') or cfg.get('source_currency') or 'USD').upper()
        rate_line = ''
        if show_rate and rate_display:
            if rate_meta.get('used_fallback_manual_rate'):
                mode_text = 'دستی هنگام خطا'
            else:
                mode_text = 'خودکار از نوبیتکس' if str(rate_meta.get('rate_source')) == 'nobitex_usdt_toman' else 'دستی'
            currency_label = 'USD/USDT' if source_currency == 'USD' else source_currency
            rate_line = f'نرخ تبدیل: هر ۱ {currency_label} ≈ {rate_display} تومان ({mode_text})'
        return {
            '_source_amount': source_amount,
            '_source_rate_toman': rate_meta.get('resolved_source_rate_toman'),
            '_source_rate_toman_display': rate_display,
            '_source_rate_line': rate_line,
            '_source_rate_mode': rate_meta.get('rate_mode'),
            '_source_rate_source': rate_meta.get('rate_source'),
            '_show_source_rate': show_rate,
            '_source_rate_error': rate_meta.get('rate_error') or rate_meta.get('rate_warning') or '',
        }

    async def _request_invoice(self, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(self.invoice_url, params={k: v for k, v in params.items() if v not in (None, '')})
            data = response.json()
        if data.get('status') != 'success':
            raise RuntimeError(str(data))
        return data.get('data') or {}

    async def create_payment(self, order: Order) -> PaymentInitResult:
        cfg = await self._config()
        api_key = cfg.get('api_key')
        if not api_key:
            return PaymentInitResult(success=False, message='API Key درگاه Plisio تنظیم نشده است.')
        amount = Decimal(str(order.amount))
        try:
            rate, rate_meta = await self._resolve_source_rate(cfg)
        except PlisioRateUnavailable as exc:
            return PaymentInitResult(success=False, message=str(exc), extra={'source_rate': exc.meta})
        source_amount = self._source_amount(amount, rate)
        minimum_amount_result = self._minimum_source_amount_result(source_amount, rate_meta, cfg)
        if minimum_amount_result:
            return minimum_amount_result
        params = {
            'source_currency': cfg.get('source_currency') or 'USD',
            'source_amount': source_amount,
            'order_number': order.order_number,
            'currency': cfg.get('currency') or None,
            'allowed_psys_cids': cfg.get('allowed_psys_cids') or None,
            'order_name': f'Order {order.order_number}',
            'description': f'Telegram order {order.order_number}',
            'callback_url': cfg.get('callback_url') or None,
            'expire_min': cfg.get('expire_min') or None,
            'api_key': api_key,
        }
        try:
            invoice = await self._request_invoice(params)
        except Exception as exc:
            return PaymentInitResult(success=False, message=f'خطا در ساخت فاکتور Plisio: {exc}')
        txn_id = invoice.get('txn_id')
        if not txn_id:
            return PaymentInitResult(success=False, message=f'پاسخ Plisio معتبر نیست: {invoice}')
        order.payment_method = PaymentMethod.PLISIO.value
        order.status = OrderStatus.WAITING_FOR_PAYMENT.value
        extra = dict(invoice)
        extra.update(self._rate_extra(source_amount, rate_meta, cfg))
        payment = Payment(
            order_id=order.id,
            method=PaymentMethod.PLISIO.value,
            status=PaymentStatus.PENDING_VERIFY.value,
            amount=order.amount,
            authority=str(txn_id),
            metadata_json={
                'plisio': invoice,
                'request': {k: v for k, v in params.items() if k != 'api_key'},
                'source_rate': rate_meta,
            },
        )
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return PaymentInitResult(
            success=True,
            message='فاکتور کریپتویی ساخته شد.',
            payment=payment,
            payment_url=invoice.get('invoice_url'),
            extra=extra,
        )

    async def create_wallet_topup(self, topup: WalletTopup) -> PaymentInitResult:
        cfg = await self._config()
        api_key = cfg.get('api_key')
        if not api_key:
            return PaymentInitResult(success=False, message='API Key درگاه Plisio تنظیم نشده است.')
        amount = Decimal(str(topup.amount))
        try:
            rate, rate_meta = await self._resolve_source_rate(cfg)
        except PlisioRateUnavailable as exc:
            return PaymentInitResult(success=False, message=str(exc), extra={'source_rate': exc.meta})
        source_amount = self._source_amount(amount, rate)
        minimum_amount_result = self._minimum_source_amount_result(source_amount, rate_meta, cfg)
        if minimum_amount_result:
            return minimum_amount_result
        params = {
            'source_currency': cfg.get('source_currency') or 'USD',
            'source_amount': source_amount,
            'order_number': topup.topup_number,
            'currency': cfg.get('currency') or None,
            'allowed_psys_cids': cfg.get('allowed_psys_cids') or None,
            'order_name': f'Wallet topup {topup.topup_number}',
            'description': f'Telegram wallet topup {topup.topup_number}',
            'callback_url': cfg.get('callback_url') or None,
            'expire_min': cfg.get('expire_min') or None,
            'api_key': api_key,
        }
        try:
            invoice = await self._request_invoice(params)
        except Exception as exc:
            return PaymentInitResult(success=False, message=f'خطا در ساخت فاکتور Plisio: {exc}')
        txn_id = invoice.get('txn_id')
        if not txn_id:
            return PaymentInitResult(success=False, message=f'پاسخ Plisio معتبر نیست: {invoice}')
        extra = dict(invoice)
        extra.update(self._rate_extra(source_amount, rate_meta, cfg))
        topup.method = PaymentMethod.PLISIO.value
        topup.status = PaymentStatus.PENDING_VERIFY.value
        topup.authority = str(txn_id)
        topup.metadata_json = {
            'plisio': invoice,
            'request': {k: v for k, v in params.items() if k != 'api_key'},
            'source_rate': rate_meta,
        }
        await self.session.commit()
        return PaymentInitResult(success=True, message='فاکتور کریپتویی ساخته شد.', payment_url=invoice.get('invoice_url'), extra=extra)

    @staticmethod
    def _php_serialize_value(value: Any) -> str:
        if isinstance(value, bool):
            return f'b:{1 if value else 0};'
        if isinstance(value, int):
            return f'i:{value};'
        if isinstance(value, float):
            return f'd:{value};'
        if isinstance(value, dict):
            return PlisioProvider._php_serialize(value)
        if isinstance(value, list):
            data = {str(i): item for i, item in enumerate(value)}
            return PlisioProvider._php_serialize(data)
        value_str = str(value)
        return f's:{len(value_str.encode("utf-8"))}:"{value_str}";'

    @staticmethod
    def _php_serialize(data: dict[str, Any]) -> str:
        parts = []
        for key in sorted(data.keys()):
            parts.append(PlisioProvider._php_serialize_value(str(key)))
            parts.append(PlisioProvider._php_serialize_value(data[key]))
        return f'a:{len(data)}:{{{"".join(parts)}}}'

    @staticmethod
    def verify_callback_hash(data: dict[str, Any], secret_key: str) -> bool:
        verify_hash = data.get('verify_hash')
        if not verify_hash or not secret_key:
            return False
        payload = dict(data)
        payload.pop('verify_hash', None)
        if 'expire_utc' in payload:
            payload['expire_utc'] = str(payload['expire_utc'])
        candidates = [
            json.dumps(payload, separators=(',', ':'), ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
            urlencode(payload),
            PlisioProvider._php_serialize(payload),
        ]
        for candidate in candidates:
            digest = hmac.new(secret_key.encode(), candidate.encode(), hashlib.sha1).hexdigest()
            if hmac.compare_digest(str(verify_hash), digest):
                return True
        return False

    async def verify(self, authority: str, payload: dict[str, Any] | None = None) -> PaymentVerifyResult:
        payload = payload or {}
        cfg = await self._config()
        if cfg.get('verify_callback', True) and payload.get('verify_hash'):
            if not self.verify_callback_hash(payload, str(cfg.get('api_key') or '')):
                return PaymentVerifyResult(success=False, message='امضای Callback Plisio معتبر نیست.', authority=authority)
        status = str(payload.get('status') or '').lower()
        success = status == 'completed'
        return PaymentVerifyResult(
            success=success,
            message='پرداخت Plisio تایید شد.' if success else f'وضعیت Plisio: {status or "unknown"}',
            transaction_id=str(payload.get('txn_id') or authority),
            authority=authority,
            extra=payload,
        )
