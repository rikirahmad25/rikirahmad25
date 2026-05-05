from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import DateTime, Numeric, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AdminActivity,
    AdminRole,
    AdminUser,
    Broadcast,
    DeliveryItem,
    DiscountCode,
    DiscountRedemption,
    Lottery,
    Order,
    Payment,
    Product,
    Setting,
    Ticket,
    TicketMessage,
    TutorialVideo,
    User,
    WalletTopup,
)
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService

EXPORT_MODELS = [
    Setting,
    User,
    AdminRole,
    AdminUser,
    TutorialVideo,
    Product,
    DeliveryItem,
    Order,
    Payment,
    WalletTopup,
    DiscountCode,
    DiscountRedemption,
    Ticket,
    TicketMessage,
    Broadcast,
    Lottery,
    AdminActivity,
]

# Restore has a stricter dependency order than export. In particular,
# users can reference users and delivery_items can reference orders.
RESTORE_MODELS = [
    Setting,
    User,
    AdminRole,
    AdminUser,
    TutorialVideo,
    Product,
    Order,
    Payment,
    WalletTopup,
    DiscountCode,
    DiscountRedemption,
    Ticket,
    TicketMessage,
    Broadcast,
    Lottery,
    DeliveryItem,
    AdminActivity,
]

DELETE_MODELS = [
    AdminActivity,
    DeliveryItem,
    Lottery,
    Broadcast,
    TicketMessage,
    Ticket,
    DiscountRedemption,
    DiscountCode,
    WalletTopup,
    Payment,
    Order,
    Product,
    TutorialVideo,
    AdminUser,
    AdminRole,
    User,
    Setting,
]


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _deserialize(model: type, key: str, value: Any) -> Any:
    if value is None:
        return None
    column = model.__table__.columns.get(key)
    if column is None:
        return value
    if isinstance(column.type, DateTime):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
    if isinstance(column.type, Numeric):
        return Decimal(str(value))
    return value


class BackupService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = SettingsService(session)

    async def export_data(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'version': 3,
            'backup_type': 'full',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'description': 'Full database backup: users, wallets, orders, payments, products, product extra_settings including auto-text delivery mode, delivery inventory, settings, discounts, tutorials, admins and logs.',
            'tables': {},
            'counts': {},
        }
        for model in EXPORT_MODELS:
            result = await self.session.execute(select(model))
            rows = []
            for item in result.scalars().all():
                row = {col.name: _serialize(getattr(item, col.name)) for col in model.__table__.columns}
                rows.append(row)
            payload['tables'][model.__tablename__] = rows
            payload['counts'][model.__tablename__] = len(rows)
        return payload

    async def export_bytes(self) -> bytes:
        data = await self.export_data()
        return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')

    async def send_backup_to_admins(self, bot: Bot, caption: str | None = None) -> None:
        data = await self.export_bytes()
        filename = f'telegram-sales-bot-backup-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}.json'
        admin_ids = await AdminService(self.session).get_admin_telegram_ids()
        for admin_id in admin_ids:
            try:
                await bot.send_document(
                    admin_id,
                    BufferedInputFile(data, filename=filename),
                    caption=caption or '💾 بکاپ ربات',
                )
            except Exception:
                pass

    async def restore_from_bytes(self, raw: bytes) -> dict[str, int]:
        try:
            payload = json.loads(raw.decode('utf-8-sig'))
        except Exception as exc:
            raise ValueError('فایل بکاپ JSON معتبر نیست یا قابل خواندن نیست.') from exc

        tables = payload.get('tables') or {}
        if not isinstance(tables, dict) or not tables:
            raise ValueError('فایل بکاپ معتبر نیست یا بخش tables ندارد.')

        bind = self.session.get_bind()
        dialect_name = getattr(getattr(bind, 'dialect', None), 'name', '') if bind is not None else ''
        if dialect_name == 'sqlite':
            await self.session.execute(text('PRAGMA foreign_keys=OFF'))

        counts: dict[str, int] = {}
        try:
            for model in DELETE_MODELS:
                await self.session.execute(delete(model))
            await self.session.flush()

            for model in RESTORE_MODELS:
                rows = tables.get(model.__tablename__) or []
                if model is User:
                    await self._restore_users_two_phase(rows)
                else:
                    await self._restore_model_rows(model, rows)
                counts[model.__tablename__] = len(rows)
                await self.session.flush()

            if dialect_name.startswith('postgres'):
                await self._reset_postgres_sequences()

            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        finally:
            if dialect_name == 'sqlite':
                try:
                    await self.session.execute(text('PRAGMA foreign_keys=ON'))
                    await self.session.commit()
                except Exception:
                    pass
        return counts

    async def _restore_model_rows(self, model: type, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            kwargs = {
                col.name: _deserialize(model, col.name, row.get(col.name))
                for col in model.__table__.columns
                if col.name in row
            }
            self.session.add(model(**kwargs))

    async def _restore_users_two_phase(self, rows: list[dict[str, Any]]) -> None:
        # Backup row order is not guaranteed. Create all users first, then
        # restore referred_by_user_id after every referenced user exists.
        pending_refs: dict[int, int | None] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            kwargs = {
                col.name: _deserialize(User, col.name, row.get(col.name))
                for col in User.__table__.columns
                if col.name in row
            }
            user_id = kwargs.get('id')
            if user_id is not None:
                pending_refs[int(user_id)] = kwargs.get('referred_by_user_id')
            kwargs['referred_by_user_id'] = None
            self.session.add(User(**kwargs))
        await self.session.flush()
        for user_id, ref_id in pending_refs.items():
            if ref_id is not None:
                user = await self.session.get(User, user_id)
                if user is not None:
                    user.referred_by_user_id = ref_id
        await self.session.flush()

    async def _reset_postgres_sequences(self) -> None:
        # Explicit IDs are restored from backup. PostgreSQL sequences must be
        # moved forward afterwards; otherwise the next insert can reuse an old ID.
        for model in EXPORT_MODELS:
            if 'id' not in model.__table__.columns:
                continue
            table_name = model.__tablename__
            await self.session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
                f"COALESCE((SELECT MAX(id) FROM {table_name}), 0) > 0)"
            ))

    async def maybe_send_scheduled_backup(self, bot: Bot) -> bool:
        cfg = await self.settings.get('backup')
        if not cfg.get('enabled'):
            return False
        interval = max(1, int(cfg.get('interval_hours') or 24))
        last_sent_at = cfg.get('last_sent_at')
        should_send = True
        if last_sent_at:
            try:
                last_dt = datetime.fromisoformat(str(last_sent_at))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                should_send = datetime.now(timezone.utc) - last_dt >= timedelta(hours=interval)
            except ValueError:
                should_send = True
        if not should_send:
            return False
        await self.send_backup_to_admins(bot, caption='💾 بکاپ خودکار ربات')
        cfg['last_sent_at'] = datetime.now(timezone.utc).isoformat()
        await self.settings.set('backup', cfg)
        return True
