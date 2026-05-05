from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db.models import Order, Payment


@dataclass(slots=True)
class PaymentInitResult:
    success: bool
    message: str
    payment_url: str | None = None
    payment: Payment | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PaymentVerifyResult:
    success: bool
    message: str
    transaction_id: str | None = None
    authority: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class PaymentProvider:
    slug: str = 'base'
    title: str = 'Base'

    async def create_payment(self, order: Order) -> PaymentInitResult:
        raise NotImplementedError

    async def verify(self, authority: str, payload: dict[str, Any] | None = None) -> PaymentVerifyResult:
        raise NotImplementedError
