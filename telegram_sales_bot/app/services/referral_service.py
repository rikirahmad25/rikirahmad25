from __future__ import annotations

from decimal import Decimal

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, User
from app.services.settings_service import SettingsService
from app.utils.text import money


class ReferralService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings_service = SettingsService(session)

    async def register_commission(self, order: Order, bot: Bot | None = None) -> Decimal:
        user = order.user
        if not user or not user.referred_by_user_id:
            return Decimal('0')
        ref_settings = await self.settings_service.get('referral')
        if not ref_settings.get('enabled', True):
            return Decimal('0')

        paid_amount = Decimal(str(order.amount or 0))
        if paid_amount < Decimal(str(ref_settings.get('min_order_amount') or 0)):
            return Decimal('0')

        basis = ref_settings.get('basis', 'paid_amount')
        applied_discount = (order.user_fields or {}).get('applied_discount') or {}
        if basis == 'original_amount' and applied_discount.get('original_amount'):
            base_amount = Decimal(str(applied_discount.get('original_amount')))
        else:
            base_amount = paid_amount

        reward_type = ref_settings.get('reward_type', 'percent')
        if reward_type == 'fixed':
            commission = Decimal(str(ref_settings.get('fixed_amount') or 0))
        else:
            percent = Decimal(str(ref_settings.get('percent', 10)))
            commission = (base_amount * percent) / Decimal('100')

        max_commission = Decimal(str(ref_settings.get('max_commission') or 0))
        if max_commission > 0:
            commission = min(commission, max_commission)
        commission = max(Decimal('0'), commission.quantize(Decimal('1')))
        if commission <= 0:
            return Decimal('0')

        referrer = await self.session.get(User, user.referred_by_user_id)
        if not referrer:
            return Decimal('0')
        referrer.wallet_balance = (referrer.wallet_balance or Decimal('0')) + commission
        await self.session.commit()
        if bot:
            await self._notify_referrer(bot, referrer, order, commission)
        return commission

    async def _notify_referrer(self, bot: Bot, referrer: User, order: Order, commission: Decimal) -> None:
        notifications = await self.settings_service.get('notifications')
        if not notifications.get('referral_commission_enabled', True):
            return
        texts = await self.settings_service.get('texts')
        text = (texts.get('referral_commission_received') or 'پورسانت شما: {commission}').format(
            order_number=order.order_number,
            commission=money(commission),
            balance=money(referrer.wallet_balance or 0),
        )
        try:
            await bot.send_message(referrer.telegram_id, text)
        except Exception:
            pass
