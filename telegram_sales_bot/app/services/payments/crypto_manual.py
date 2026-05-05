from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.models import Order, Payment
from app.services.crypto_rate_service import SUPPORTED_CRYPTO_SYMBOLS, build_crypto_payment_options, wallet_coin_symbol
from app.services.payments.base import PaymentInitResult, PaymentProvider, PaymentVerifyResult
from app.services.settings_service import SettingsService


class CryptoManualProvider(PaymentProvider):
    slug = 'crypto_manual'
    title = 'پرداخت رمزارز دستی'

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _active_wallets(cfg: dict) -> list[dict]:
        wallets = []
        for wallet in cfg.get('wallets') or []:
            if not isinstance(wallet, dict):
                continue
            symbol = wallet_coin_symbol(wallet)
            if wallet.get('is_active', True) and wallet.get('address') and symbol in SUPPORTED_CRYPTO_SYMBOLS:
                item = dict(wallet)
                item['coin_symbol'] = symbol
                wallets.append(item)
        return wallets

    async def create_payment(self, order: Order) -> PaymentInitResult:
        cfg = await SettingsService(self.session).get('crypto_manual')
        wallets = self._active_wallets(cfg)
        if not wallets:
            return PaymentInitResult(success=False, message='آدرس ولت فعالی برای پرداخت رمزارز ثبت نشده است.')

        crypto_options = await build_crypto_payment_options(
            order.amount,
            wallets,
            show_unit_price=bool(cfg.get('show_unit_price', False)),
            auto_convert_enabled=bool(cfg.get('auto_convert_enabled', True)),
        )
        wallets = list(crypto_options.get('wallets') or wallets)
        payment = Payment(
            order_id=order.id,
            method=PaymentMethod.CRYPTO_MANUAL.value,
            status=PaymentStatus.WAITING_RECEIPT.value,
            amount=order.amount,
            metadata_json={'wallets': wallets, 'crypto_quote': crypto_options.get('quote') or {}},
        )
        order.status = OrderStatus.WAITING_FOR_PAYMENT.value
        order.payment_method = PaymentMethod.CRYPTO_MANUAL.value
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return PaymentInitResult(
            success=True,
            message='اطلاعات پرداخت رمزارز نمایش داده شد. بعد از واریز، رسید یا هش تراکنش را ارسال کن.',
            payment=payment,
            extra={
                'wallets': wallets,
                'instructions': cfg.get('instructions') or '',
                'show_unit_price': bool(cfg.get('show_unit_price', False)),
                'crypto_quote': crypto_options.get('quote') or {},
            },
        )

    async def verify(self, authority: str, payload: dict | None = None) -> PaymentVerifyResult:
        return PaymentVerifyResult(success=False, message='پرداخت رمزارز دستی باید توسط ادمین تایید شود.')
