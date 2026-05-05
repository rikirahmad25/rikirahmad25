from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import PaymentStatus
from app.db.models import User, WalletTopup
from app.utils.ids import generate_order_number


class WalletTopupService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User, amount: Decimal, method: str | None = None) -> WalletTopup:
        topup = WalletTopup(
            topup_number=generate_order_number('WAL'),
            user_id=user.id,
            amount=amount,
            method=method,
            status=PaymentStatus.INITIATED.value,
            metadata_json={},
        )
        self.session.add(topup)
        await self.session.commit()
        await self.session.refresh(topup)
        return topup

    async def get(self, topup_id: int) -> WalletTopup | None:
        result = await self.session.execute(select(WalletTopup).where(WalletTopup.id == topup_id).options(selectinload(WalletTopup.user)))
        return result.scalar_one_or_none()

    async def get_by_authority(self, authority: str) -> WalletTopup | None:
        result = await self.session.execute(select(WalletTopup).where(WalletTopup.authority == authority).options(selectinload(WalletTopup.user)))
        return result.scalar_one_or_none()

    async def get_by_number(self, number: str) -> WalletTopup | None:
        result = await self.session.execute(select(WalletTopup).where(WalletTopup.topup_number == number).options(selectinload(WalletTopup.user)))
        return result.scalar_one_or_none()

    async def set_pending_receipt(self, topup: WalletTopup, text: str | None, file_id: str | None) -> WalletTopup:
        topup.receipt_text = text
        topup.receipt_file_id = file_id
        topup.status = PaymentStatus.PENDING_VERIFY.value
        await self.session.commit()
        await self.session.refresh(topup)
        return topup

    async def mark_paid(self, topup: WalletTopup, transaction_id: str | None = None) -> WalletTopup:
        topup.status = PaymentStatus.VERIFIED.value
        topup.paid_at = datetime.now(timezone.utc)
        topup.reviewed_at = datetime.now(timezone.utc)
        if transaction_id:
            topup.transaction_id = transaction_id
        user = topup.user or await self.session.get(User, topup.user_id)
        if user:
            user.wallet_balance = (user.wallet_balance or Decimal('0')) + Decimal(str(topup.amount or 0))
        await self.session.commit()
        await self.session.refresh(topup)
        return topup

    async def mark_failed(self, topup: WalletTopup, note: str | None = None) -> WalletTopup:
        topup.status = PaymentStatus.FAILED.value
        topup.reviewed_at = datetime.now(timezone.utc)
        meta = dict(topup.metadata_json or {})
        if note:
            meta['note'] = note
        topup.metadata_json = meta
        await self.session.commit()
        await self.session.refresh(topup)
        return topup
