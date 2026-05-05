from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.utils.ids import generate_referral_code


class UserService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, telegram_id: int, first_name: str | None, last_name: str | None, username: str | None) -> User:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            meta = dict(user.metadata_json or {})
            if meta.get('bot_blocked'):
                meta['bot_blocked'] = False
                meta.pop('bot_blocked_notified', None)
                user.metadata_json = meta
            await self.session.commit()
            return user
        user = User(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            referral_code=generate_referral_code(),
            metadata_json={'new_user_notified': False},
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def find(self, identifier: str) -> User | None:
        raw = (identifier or '').strip()
        if not raw:
            return None
        username = raw.lstrip('@')
        conditions = []
        if raw.isdigit():
            conditions.append(User.telegram_id == int(raw))
            conditions.append(User.id == int(raw))
        conditions.append(User.username == username)
        conditions.append(User.phone_number == raw)
        result = await self.session.execute(select(User).where(or_(*conditions)).limit(1))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.id.desc()))
        return result.scalars().all()

    async def set_referrer(self, user: User, referrer: User) -> None:
        if user.id == referrer.id or user.referred_by_user_id:
            return
        user.referred_by_user_id = referrer.id
        await self.session.commit()

    async def add_wallet(self, user: User, amount: Decimal) -> User:
        user.wallet_balance = (user.wallet_balance or Decimal('0')) + amount
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def deduct_wallet(self, user: User, amount: Decimal) -> bool:
        balance = user.wallet_balance or Decimal('0')
        if balance < amount:
            return False
        user.wallet_balance = balance - amount
        await self.session.commit()
        return True

    async def set_blocked(self, user: User, blocked: bool) -> User:
        user.is_blocked = blocked
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def mark_bot_blocked(self, user: User, blocked: bool = True) -> User:
        meta = dict(user.metadata_json or {})
        meta['bot_blocked'] = blocked
        if not blocked:
            meta.pop('bot_blocked_notified', None)
        user.metadata_json = meta
        await self.session.commit()
        await self.session.refresh(user)
        return user
