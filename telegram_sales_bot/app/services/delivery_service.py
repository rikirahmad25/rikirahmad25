from __future__ import annotations

import html
from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus
from app.db.models import Order
from app.services.product_service import AUTO_DELIVERY_KINDS, ProductService, order_quantity
from app.services.settings_service import SettingsService


class DeliveryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.products = ProductService(session)
        self.settings = SettingsService(session)

    async def _send_auto_text_payloads(self, bot: Bot, order: Order, payload_rows: list[dict]) -> bool:
        """Send one or more auto-text inventory payloads to the customer."""
        if not payload_rows:
            return False
        rows_with_files = [row for row in payload_rows if row.get('file_id')]
        if rows_with_files:
            for idx, row in enumerate(payload_rows, 1):
                payload = row.get('payload') or f'آیتم {idx}'
                file_id = row.get('file_id')
                if file_id:
                    await bot.send_document(order.user.telegram_id, document=file_id, caption=payload or '📦 فایل سفارش شما')
                elif payload:
                    await bot.send_message(order.user.telegram_id, f'📦 اطلاعات آیتم {idx} سفارش شما:\n\n{html.escape(str(payload))}')
            return True

        if len(payload_rows) == 1:
            safe_payload = html.escape(str(payload_rows[0].get('payload') or ''))
            await bot.send_message(order.user.telegram_id, f'📦 اطلاعات سفارش شما:\n\n{safe_payload}')
            return True

        lines = ['📦 اطلاعات سفارش شما:', '']
        for idx, row in enumerate(payload_rows, 1):
            payload = html.escape(str(row.get('payload') or ''))
            lines.append(f'{idx}. {payload}')
            lines.append('')
        await bot.send_message(order.user.telegram_id, '\n'.join(lines).strip())
        return True

    async def deliver(self, bot: Bot, order: Order) -> tuple[bool, str]:
        product = order.product
        quantity = order_quantity(order)
        delivered_content = False

        # Only auto_text products are delivered automatically.
        if product.delivery_kind in AUTO_DELIVERY_KINDS:
            items = await self.products.get_unused_delivery_items(product.id, quantity)
            payload_rows: list[dict] = []
            if len(items) >= quantity:
                for item in items[:quantity]:
                    item.is_used = True
                    item.used_in_order_id = order.id
                    payload_rows.append({
                        'delivery_item_id': item.id,
                        'payload': item.payload,
                        'file_id': item.file_id,
                        'delivered_at': datetime.now(timezone.utc).isoformat(),
                    })
            else:
                fallback = dict(product.auto_delivery_payload or {})
                if fallback.get('repeat') and (fallback.get('text') or fallback.get('file_id')):
                    for _ in range(quantity):
                        payload_rows.append({
                            'delivery_item_id': None,
                            'payload': fallback.get('text'),
                            'file_id': fallback.get('file_id'),
                            'delivered_at': datetime.now(timezone.utc).isoformat(),
                        })

            if len(payload_rows) < quantity:
                await self.session.commit()
                return False, 'موجودی تحویل خودکار این محصول برای تعداد انتخابی کافی نیست یا محتوایی برای تحویل ثبت نشده است.'

            delivered_content = await self._send_auto_text_payloads(bot, order, payload_rows)
            if delivered_content:
                fields = dict(order.user_fields or {})
                delivered_items = list(fields.get('_delivered_items') or [])
                delivered_items.extend(payload_rows)
                fields['_delivered_items'] = delivered_items
                order.user_fields = fields

        texts = await self.settings.get('texts')
        complete_text = (texts.get('order_completed') or '✅ سفارش {order_number} تکمیل شد.').format(order_number=order.order_number)
        await bot.send_message(order.user.telegram_id, complete_text)

        order.status = OrderStatus.COMPLETED.value
        order.completed_at = datetime.now(timezone.utc)

        if product.delivery_kind in AUTO_DELIVERY_KINDS:
            await self.products.sync_auto_stock(product)
        else:
            await self.products.consume_stock(product, quantity)

        await self.session.commit()
        return True, 'سفارش تکمیل شد.' if delivered_content else 'سفارش بدون محتوای خودکار تکمیل شد.'
