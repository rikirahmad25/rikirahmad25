from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.models import Order, Payment
from app.services.payments.base import PaymentInitResult, PaymentProvider, PaymentVerifyResult
from app.services.settings_service import SettingsService

settings = get_settings()


class CardToCardProvider(PaymentProvider):
    slug = 'card_to_card'
    title = 'کارت به کارت'

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_payment(self, order: Order) -> PaymentInitResult:
        cfg = await SettingsService(self.session).get('card_to_card')
        metadata = {
            'card_number': cfg.get('card_number') or settings.card_to_card_number,
            'card_holder': cfg.get('card_holder') or settings.card_to_card_holder,
            'bank': cfg.get('bank') or settings.card_to_card_bank,
            'box_text': cfg.get('box_text'),
        }
        payment = Payment(
            order_id=order.id,
            method=PaymentMethod.CARD_TO_CARD.value,
            status=PaymentStatus.WAITING_RECEIPT.value,
            amount=order.amount,
            metadata_json=metadata,
        )
        order.status = OrderStatus.WAITING_FOR_PAYMENT.value
        order.payment_method = PaymentMethod.CARD_TO_CARD.value
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return PaymentInitResult(
            success=True,
            message='اطلاعات کارت نمایش داده شد. رسید یا کد پیگیری را برای بررسی ارسال کن.',
            payment=payment,
            extra=payment.metadata_json,
        )

    async def verify(self, authority: str, payload: dict | None = None) -> PaymentVerifyResult:
        return PaymentVerifyResult(success=False, message='رسید کارت به کارت باید دستی توسط ادمین تایید شود.')
