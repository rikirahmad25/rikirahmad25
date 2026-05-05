from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    BroadcastStatus,
    DeliveryKind,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    ProductKind,
    TicketStatus,
)
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    referred_by = relationship('User', remote_side=[id])
    orders = relationship('Order', back_populates='user')


class AdminRole(Base, TimestampMixin):
    __tablename__ = 'admin_roles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminUser(Base, TimestampMixin):
    __tablename__ = 'admin_users'
    __table_args__ = (UniqueConstraint('telegram_id', name='uq_admin_users_telegram_id'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey('admin_roles.id'))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    role = relationship('AdminRole')


class Product(Base, TimestampMixin):
    __tablename__ = 'products'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    kind: Mapped[str] = mapped_column(String(50), default=ProductKind.DIGITAL.value)
    delivery_kind: Mapped[str] = mapped_column(String(50), default=DeliveryKind.MANUAL.value)
    required_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    stock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_delivery_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extra_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    delivery_items = relationship('DeliveryItem', back_populates='product')


class DeliveryItem(Base, TimestampMixin):
    __tablename__ = 'delivery_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    payload: Mapped[str] = mapped_column(Text)
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_in_order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id'), nullable=True)

    product = relationship('Product', back_populates='delivery_items')
    used_in_order = relationship('Order', foreign_keys=[used_in_order_id], back_populates='delivered_items')


class Order(Base, TimestampMixin):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(50), default=OrderStatus.NEW.value, index=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transaction_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    internal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship('User', back_populates='orders')
    product = relationship('Product')
    payments = relationship('Payment', back_populates='order')
    delivered_items = relationship('DeliveryItem', foreign_keys='DeliveryItem.used_in_order_id', back_populates='used_in_order')


class Payment(Base, TimestampMixin):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), index=True)
    method: Mapped[str] = mapped_column(String(50), default=PaymentMethod.CARD_TO_CARD.value)
    status: Mapped[str] = mapped_column(String(50), default=PaymentStatus.INITIATED.value, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    authority: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    order = relationship('Order', back_populates='payments')


class TutorialVideo(Base, TimestampMixin):
    __tablename__ = 'tutorial_videos'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_file_id: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WalletTopup(Base, TimestampMixin):
    __tablename__ = 'wallet_topups'
    __table_args__ = (UniqueConstraint('topup_number', name='uq_wallet_topups_number'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topup_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(50), default=PaymentStatus.INITIATED.value, index=True)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    authority: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user = relationship('User')


class DiscountCode(Base, TimestampMixin):
    __tablename__ = 'discount_codes'
    __table_args__ = (UniqueConstraint('code', name='uq_discount_codes_code'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discount_type: Mapped[str] = mapped_column(String(20), default='percent')
    discount_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    min_order_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DiscountRedemption(Base, TimestampMixin):
    __tablename__ = 'discount_redemptions'
    __table_args__ = (UniqueConstraint('discount_code_id', 'order_id', name='uq_discount_redemption_order'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discount_code_id: Mapped[int] = mapped_column(ForeignKey('discount_codes.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    discount_code = relationship('DiscountCode')
    user = relationship('User')
    order = relationship('Order')


class Ticket(Base, TimestampMixin):
    __tablename__ = 'tickets'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default=TicketStatus.OPEN.value)

    user = relationship('User')
    messages = relationship('TicketMessage', back_populates='ticket')


class TicketMessage(Base, TimestampMixin):
    __tablename__ = 'ticket_messages'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'), index=True)
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    sender_admin_id: Mapped[int | None] = mapped_column(ForeignKey('admin_users.id'), nullable=True)
    text: Mapped[str] = mapped_column(Text)

    ticket = relationship('Ticket', back_populates='messages')


class Setting(Base, TimestampMixin):
    __tablename__ = 'settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AdminActivity(Base, TimestampMixin):
    __tablename__ = 'admin_activities'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Broadcast(Base, TimestampMixin):
    __tablename__ = 'broadcasts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    message_text: Mapped[str] = mapped_column(Text)
    target_filter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default=BroadcastStatus.DRAFT.value)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Lottery(Base, TimestampMixin):
    __tablename__ = 'lotteries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    prize_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    draw_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
