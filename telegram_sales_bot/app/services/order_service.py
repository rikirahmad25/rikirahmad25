from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import OrderStatus, PaymentStatus
from app.db.models import Order, Payment, Product, User
from app.utils.ids import generate_order_number


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_order(self, user: User, product: Product, user_fields: dict, quantity: int = 1) -> Order:
        quantity = max(1, int(quantity or 1))
        fields = dict(user_fields or {})
        fields.setdefault('_quantity', quantity)
        fields.setdefault('_unit_price', str(product.price))
        order = Order(
            order_number=generate_order_number(),
            user_id=user.id,
            product_id=product.id,
            amount=Decimal(str(product.price)) * Decimal(quantity),
            status=OrderStatus.WAITING_FOR_PAYMENT.value,
            user_fields=fields,
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def get(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.user), selectinload(Order.product), selectinload(Order.payments), selectinload(Order.delivered_items))
        )
        return result.scalar_one_or_none()

    async def get_by_number(self, order_number: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .where(Order.order_number == order_number)
            .options(selectinload(Order.user), selectinload(Order.product), selectinload(Order.payments), selectinload(Order.delivered_items))
        )
        return result.scalar_one_or_none()

    async def get_by_authority(self, authority: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .join(Payment)
            .where(Payment.authority == authority)
            .options(selectinload(Order.user), selectinload(Order.product), selectinload(Order.payments), selectinload(Order.delivered_items))
        )
        return result.scalar_one_or_none()

    async def attach_receipt(self, order: Order, text: str | None = None, file_id: str | None = None) -> Payment | None:
        payment = order.payments[-1] if order.payments else None
        if not payment:
            return None
        payment.receipt_text = text
        payment.receipt_file_id = file_id
        payment.status = PaymentStatus.PENDING_VERIFY.value
        order.status = OrderStatus.PENDING_MANUAL_REVIEW.value
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def mark_paid(self, order: Order, transaction_id: str | None = None) -> Order:
        payment = order.payments[-1] if order.payments else None
        if payment:
            payment.status = PaymentStatus.VERIFIED.value
            if transaction_id:
                payment.transaction_id = transaction_id
        order.status = OrderStatus.PAID.value
        order.paid_at = datetime.now(timezone.utc)
        if transaction_id:
            order.transaction_ref = transaction_id
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def mark_failed(self, order: Order, note: str | None = None) -> Order:
        payment = order.payments[-1] if order.payments else None
        if payment:
            payment.status = PaymentStatus.FAILED.value
        order.status = OrderStatus.NEEDS_ATTENTION.value if note else OrderStatus.CANCELLED.value
        if note:
            order.internal_note = note
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def complete_manual(self, order: Order, note: str | None = None) -> Order:
        order.status = OrderStatus.COMPLETED.value
        order.completed_at = datetime.now(timezone.utc)
        if note:
            order.internal_note = note
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def auto_cancel_unpaid(self, older_than_minutes: int) -> int:
        threshold = datetime.now(timezone.utc).timestamp() - (older_than_minutes * 60)
        result = await self.session.execute(
            select(Order).where(Order.status.in_([OrderStatus.WAITING_FOR_PAYMENT.value, OrderStatus.NEW.value]))
        )
        orders = result.scalars().all()
        cancelled = 0
        for order in orders:
            if order.created_at.timestamp() < threshold:
                order.status = OrderStatus.CANCELLED.value
                cancelled += 1
        if cancelled:
            await self.session.commit()
        return cancelled
