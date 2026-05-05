from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DiscountCode, DiscountRedemption, Order, User
from app.services.settings_service import SettingsService


@dataclass(slots=True)
class DiscountApplyResult:
    success: bool
    message: str
    discount_amount: Decimal = Decimal('0')
    original_amount: Decimal = Decimal('0')
    final_amount: Decimal = Decimal('0')
    code: DiscountCode | None = None


class DiscountService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings_service = SettingsService(session)

    @staticmethod
    def normalize_code(code: str) -> str:
        return code.strip().upper().replace(' ', '')

    async def list_codes(self, limit: int = 20) -> list[DiscountCode]:
        result = await self.session.execute(select(DiscountCode).order_by(DiscountCode.id.desc()).limit(limit))
        return list(result.scalars().all())

    async def get_by_id(self, code_id: int) -> DiscountCode | None:
        return await self.session.get(DiscountCode, code_id)

    async def get_by_code(self, code: str) -> DiscountCode | None:
        normalized = self.normalize_code(code)
        result = await self.session.execute(select(DiscountCode).where(DiscountCode.code == normalized))
        return result.scalar_one_or_none()

    async def create_code(
        self,
        code: str,
        discount_type: str,
        discount_value: Decimal,
        max_uses: int | None = None,
        per_user_limit: int = 1,
        min_order_amount: Decimal = Decimal('0'),
        title: str | None = None,
    ) -> DiscountCode:
        item = DiscountCode(
            code=self.normalize_code(code),
            title=title,
            discount_type=discount_type,
            discount_value=discount_value,
            max_uses=max_uses,
            per_user_limit=per_user_limit,
            min_order_amount=min_order_amount,
            used_count=0,
            is_active=True,
            metadata_json={},
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def toggle_code(self, code_id: int) -> DiscountCode | None:
        item = await self.get_by_id(code_id)
        if not item:
            return None
        item.is_active = not item.is_active
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_code(self, code_id: int) -> bool:
        item = await self.get_by_id(code_id)
        if not item:
            return False
        if int(item.used_count or 0) > 0:
            item.is_active = False
        else:
            await self.session.delete(item)
        await self.session.commit()
        return True

    async def _user_used_count(self, discount_code_id: int, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(DiscountRedemption.id)).where(
                DiscountRedemption.discount_code_id == discount_code_id,
                DiscountRedemption.user_id == user_id,
            )
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    def _metadata_allows_now(metadata: dict[str, Any] | None) -> bool:
        metadata = metadata or {}
        now = datetime.now(timezone.utc)
        starts_at = metadata.get('starts_at')
        ends_at = metadata.get('ends_at')
        try:
            if starts_at:
                start_dt = datetime.fromisoformat(str(starts_at))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                if start_dt > now:
                    return False
            if ends_at:
                end_dt = datetime.fromisoformat(str(ends_at))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                if end_dt < now:
                    return False
        except (TypeError, ValueError):
            return False
        return True

    def calculate_discount(self, discount: DiscountCode, amount: Decimal) -> Decimal:
        value = Decimal(str(discount.discount_value or 0))
        if discount.discount_type == 'percent':
            value = max(Decimal('0'), min(value, Decimal('100')))
            discount_amount = (amount * value) / Decimal('100')
        else:
            discount_amount = value
        if discount_amount < 0:
            return Decimal('0')
        return min(discount_amount.quantize(Decimal('1')), amount)

    async def validate_for_order(self, code: str, order: Order, user: User) -> DiscountApplyResult:
        discount_cfg = await self.settings_service.get('discounts')
        if not discount_cfg.get('enabled'):
            return DiscountApplyResult(False, 'discounts_disabled')
        if (order.user_fields or {}).get('applied_discount') and not discount_cfg.get('stackable'):
            return DiscountApplyResult(False, 'discount_already_applied')
        discount = await self.get_by_code(code)
        if not discount or not discount.is_active:
            return DiscountApplyResult(False, 'discount_not_found')
        if not self._metadata_allows_now(discount.metadata_json):
            return DiscountApplyResult(False, 'discount_not_in_date')
        if discount.max_uses is not None and int(discount.used_count or 0) >= int(discount.max_uses):
            return DiscountApplyResult(False, 'discount_usage_finished')
        if int(discount.per_user_limit or 0) > 0:
            used_by_user = await self._user_used_count(discount.id, user.id)
            if used_by_user >= int(discount.per_user_limit):
                return DiscountApplyResult(False, 'discount_user_limit')
        amount = Decimal(str(order.amount or 0))
        if amount < Decimal(str(discount.min_order_amount or 0)):
            return DiscountApplyResult(False, 'discount_min_order')
        discount_amount = self.calculate_discount(discount, amount)
        final_amount = max(Decimal('0'), amount - discount_amount)
        return DiscountApplyResult(
            True,
            'discount_ok',
            discount_amount=discount_amount,
            original_amount=amount,
            final_amount=final_amount,
            code=discount,
        )

    async def apply_to_order(self, code: str, order: Order, user: User) -> DiscountApplyResult:
        result = await self.validate_for_order(code, order, user)
        if not result.success or not result.code:
            return result
        fields = dict(order.user_fields or {})
        fields['applied_discount'] = {
            'id': result.code.id,
            'code': result.code.code,
            'type': result.code.discount_type,
            'value': str(result.code.discount_value),
            'discount_amount': str(result.discount_amount),
            'original_amount': str(result.original_amount),
            'final_amount': str(result.final_amount),
        }
        order.user_fields = fields
        order.amount = result.final_amount
        await self.session.commit()
        await self.session.refresh(order)
        return result

    async def mark_order_redeemed(self, order: Order) -> bool:
        applied = (order.user_fields or {}).get('applied_discount') or {}
        code_id = applied.get('id')
        if not code_id or not order.user_id:
            return False
        result = await self.session.execute(
            select(DiscountRedemption).where(DiscountRedemption.order_id == order.id)
        )
        if result.scalar_one_or_none():
            return False
        amount = Decimal(str(applied.get('discount_amount') or 0))
        redemption = DiscountRedemption(
            discount_code_id=int(code_id),
            user_id=order.user_id,
            order_id=order.id,
            amount=amount,
        )
        discount = await self.get_by_id(int(code_id))
        if discount:
            discount.used_count = int(discount.used_count or 0) + 1
        self.session.add(redemption)
        await self.session.commit()
        return True
