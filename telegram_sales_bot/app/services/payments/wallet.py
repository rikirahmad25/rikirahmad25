from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.models import Order, Payment, User
from app.services.payments.base import PaymentInitResult, PaymentProvider, PaymentVerifyResult


class WalletProvider(PaymentProvider):
    slug = 'wallet'
    title = 'کیف پول'

    def __init__(self, session: AsyncSession, user: User):
        self.session = session
        self.user = user

    async def create_payment(self, order: Order) -> PaymentInitResult:
        balance = self.user.wallet_balance or Decimal('0')
        if balance < order.amount:
            return PaymentInitResult(success=False, message='موجودی کیف پول کافی نیست.')
        self.user.wallet_balance = balance - order.amount
        payment = Payment(
            order_id=order.id,
            method=PaymentMethod.WALLET.value,
            status=PaymentStatus.VERIFIED.value,
            amount=order.amount,
            transaction_id=f'wallet:{order.order_number}',
        )
        order.status = OrderStatus.PAID.value
        order.payment_method = PaymentMethod.WALLET.value
        order.paid_at = datetime.now(timezone.utc)
        self.session.add(payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return PaymentInitResult(success=True, message='پرداخت از کیف پول انجام شد.', payment=payment)

    async def verify(self, authority: str, payload: dict | None = None) -> PaymentVerifyResult:
        return PaymentVerifyResult(success=True, message='Wallet payments do not need callback verification.')
