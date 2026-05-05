from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.bot.keyboards.admin import (
    manual_review_keyboard,
    order_detail_keyboard,
    order_processing_keyboard,
    orders_admin_keyboard,
    orders_cleanup_keyboard,
    orders_list_keyboard,
)
from app.bot.states.admin import AdminOrderStates
from app.core.enums import OrderStatus, PaymentMethod
from app.core.permissions import MANAGE_ORDERS, MANAGE_PAYMENTS
from app.db.models import Order, WalletTopup
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.delivery_service import DeliveryService
from app.services.discount_service import DiscountService
from app.services.order_service import OrderService
from app.services.product_service import ProductService, order_quantity, should_auto_deliver_after_payment
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService
from app.services.wallet_topup_service import WalletTopupService
from app.utils.text import money

router = Router(name='admin_orders')

PAGE_SIZE = 8

ORDER_CATEGORY_TITLES = {
    'pending_review': 'منتظر تایید پرداخت',
    'processing': 'منتظر پردازش',
    'completed': 'پردازش/تکمیل شده',
    'rejected': 'رد شده/لغوشده',
}

ORDER_CATEGORY_STATUSES = {
    'pending_review': [OrderStatus.PENDING_MANUAL_REVIEW.value],
    'processing': [OrderStatus.PROCESSING.value, OrderStatus.PAID.value],
    'completed': [OrderStatus.COMPLETED.value],
    'rejected': [OrderStatus.NEEDS_ATTENTION.value, OrderStatus.CANCELLED.value],
}

STATUS_TITLES = {
    OrderStatus.NEW.value: 'جدید',
    OrderStatus.WAITING_FOR_INFO.value: 'منتظر اطلاعات مشتری',
    OrderStatus.WAITING_FOR_PAYMENT.value: 'منتظر پرداخت',
    OrderStatus.PAID.value: 'پرداخت‌شده/منتظر پردازش',
    OrderStatus.PENDING_MANUAL_REVIEW.value: 'منتظر تایید پرداخت',
    OrderStatus.PROCESSING.value: 'منتظر پردازش',
    OrderStatus.COMPLETED.value: 'تکمیل‌شده',
    OrderStatus.CANCELLED.value: 'لغوشده',
    OrderStatus.NEEDS_ATTENTION.value: 'رد شده/نیازمند بررسی',
}


PAYMENT_METHOD_TITLES = {
    PaymentMethod.CARD_TO_CARD.value: 'کارت‌به‌کارت',
    PaymentMethod.ZARINPAL.value: 'زرین‌پال',
    PaymentMethod.PLISIO.value: 'پرداخت کریپتویی آنلاین',
    PaymentMethod.CRYPTO_MANUAL.value: 'پرداخت رمزارز دستی',
    PaymentMethod.WALLET.value: 'کیف پول',
}


def _payment_method_title(method: str | None) -> str:
    return PAYMENT_METHOD_TITLES.get(method or '', method or '—')


def _append_note(old_note: str | None, new_note: str) -> str:
    old = (old_note or '').strip()
    return (old + '\n' + new_note).strip() if old else new_note


def _crypto_wallets_admin_text(payment) -> str:
    wallets = (getattr(payment, 'metadata_json', None) or {}).get('wallets') or []
    if not wallets:
        return ''
    lines = ['آدرس‌های رمزارز نمایش‌داده‌شده به مشتری:']
    for idx, wallet in enumerate(wallets, 1):
        lines.append(f'{idx}. {wallet.get("coin") or "—"} | شبکه: {wallet.get("network") or "—"}')
        lines.append(f'آدرس: {wallet.get("address") or "—"}')
        if wallet.get('note'):
            lines.append(f'توضیح: {wallet.get("note")}')
    return '\n'.join(lines)


async def _has_order_access(telegram_id: int, permission: str = MANAGE_ORDERS) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, permission)


def _admin_title(callback: CallbackQuery) -> str:
    user = callback.from_user
    name = ' '.join(part for part in [user.first_name, user.last_name] if part) or (user.username or str(user.id))
    if user.username:
        return f'{name} (@{user.username})'
    return f'{name} ({user.id})'


def _status_title(status: str | None) -> str:
    return STATUS_TITLES.get(status or '', status or '—')


def _category_for_status(status: str | None) -> str | None:
    for category, statuses in ORDER_CATEGORY_STATUSES.items():
        if status in statuses:
            return category
    return None


def _is_admin_hidden(order: Order) -> bool:
    hidden = (order.user_fields or {}).get('_admin_hidden')
    return bool(hidden)


def _reference_time_for_cleanup(order: Order):
    value = order.completed_at or order.updated_at or order.created_at
    if value and getattr(value, 'tzinfo', None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _fields_text(fields: dict | None, include_discount: bool = False) -> str:
    fields = dict(fields or {})
    fields = {k: v for k, v in fields.items() if not str(k).startswith('_')}
    if not include_discount:
        fields = {k: v for k, v in fields.items() if k != 'applied_discount'}
    if not fields:
        return '—'
    lines: list[str] = []
    for key, value in fields.items():
        if key == 'applied_discount' and isinstance(value, dict):
            code = value.get('code') or '—'
            amount = value.get('amount') or 0
            lines.append(f'• کد تخفیف: {code} | مقدار تخفیف: {money(amount)}')
        else:
            lines.append(f'• {key}: {value}')
    return '\n'.join(lines) or '—'



def _order_quantity_text(order: Order) -> str:
    fields = dict(order.user_fields or {})
    try:
        quantity = max(1, int(fields.get('_quantity') or 1))
    except (TypeError, ValueError):
        quantity = 1
    unit_display = fields.get('_unit_price_display')
    total_display = fields.get('_total_price_display')
    parts = [f'تعداد: {quantity}']
    if unit_display:
        parts.append(f'قیمت واحد: {unit_display}')
    if total_display and quantity > 1:
        parts.append(f'جمع: {total_display}')
    return ' | '.join(parts)


def _format_dt(value: Any) -> str:
    if not value:
        return '—'
    try:
        return value.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(value)


def _latest_payment(order: Order):
    payments = list(order.payments or [])
    if not payments:
        return None
    return sorted(payments, key=lambda item: item.id)[-1]


def _order_caption(order: Order, payment=None, status_line: str | None = None) -> str:
    method = payment.method if payment else order.payment_method
    text = (
        f'🧾 رسید پرداخت ({_payment_method_title(method)})\n'
        f'شماره سفارش: {order.order_number}\n'
        f'وضعیت: {_status_title(order.status)}\n'
        f'کاربر: {order.user.first_name or "—"} (@{order.user.username or "—"})\n'
        f'آیدی تلگرام: {order.user.telegram_id}\n'
        f'محصول: {order.product.title}\n'
        f'مبلغ: {money(order.amount)}\n'
        f'روش پرداخت: {_payment_method_title(method)}\n'
        f'{_order_quantity_text(order)}\n'
        f'اطلاعات مشتری:\n{_fields_text(order.user_fields)}'
    )
    if payment and payment.receipt_text:
        text += f'\nتوضیح رسید: {payment.receipt_text}'
    if status_line:
        text += f'\n\n{status_line}'
    return text[:1024]


def _topup_caption(topup: WalletTopup, status_line: str | None = None) -> str:
    text = (
        '🧾 رسید شارژ کیف پول\n'
        f'شماره شارژ: {topup.topup_number}\n'
        f'کاربر: {topup.user.first_name or "—"} (@{topup.user.username or "—"})\n'
        f'آیدی تلگرام: {topup.user.telegram_id}\n'
        f'مبلغ: {money(topup.amount)}'
    )
    if topup.receipt_text:
        text += f'\nتوضیح رسید: {topup.receipt_text}'
    if status_line:
        text += f'\n\n{status_line}'
    return text[:1024]



def _delivered_payload_preview(payload: Any, file_id: str | None = None, limit: int = 1200) -> str:
    value = str(payload or '').strip()
    if not value and file_id:
        value = '\u0641\u0627\u06cc\u0644 \u062a\u062d\u0648\u06cc\u0644'
    if file_id:
        value = f'{value}\nfile_id: {file_id}' if value else f'file_id: {file_id}'
    if not value:
        value = '\u0645\u062d\u062a\u0648\u0627\u06cc\u06cc \u062b\u0628\u062a \u0646\u0634\u062f\u0647 \u0627\u0633\u062a.'
    if len(value) > limit:
        value = value[:limit] + '...'
    return html.escape(value)


def _delivered_items_text(order: Order) -> str:
    lines: list[str] = []
    seen_ids: set[int] = set()
    for item in (order.user_fields or {}).get('_delivered_items') or []:
        if not isinstance(item, dict):
            continue
        raw_item_id = item.get('delivery_item_id')
        item_id = int(raw_item_id) if str(raw_item_id or '').isdigit() else None
        if item.get('delivery_type') == 'manual_text':
            title = 'تحویل متنی توسط ادمین'
        elif item_id:
            seen_ids.add(item_id)
            title = f'\u062a\u062d\u0648\u06cc\u0644\u200c\u0634\u062f\u0647 \u0627\u0632 \u0622\u06cc\u062a\u0645 #{item_id}'
        else:
            title = '\u062a\u062d\u0648\u06cc\u0644\u200c\u0634\u062f\u0647 \u0627\u0632 \u0645\u0648\u062c\u0648\u062f\u06cc \u062a\u06a9\u0631\u0627\u0631\u06cc/\u0642\u062f\u06cc\u0645\u06cc'
        if item.get('delivered_at'):
            title += f' | \u0632\u0645\u0627\u0646 \u062a\u062d\u0648\u06cc\u0644: {item.get("delivered_at")}'
        lines.append(f'{title}\n{_delivered_payload_preview(item.get("payload"), item.get("file_id"))}')
    for db_item in order.__dict__.get('delivered_items') or []:
        if db_item.id in seen_ids:
            continue
        lines.append(f'\u062a\u062d\u0648\u06cc\u0644\u200c\u0634\u062f\u0647 \u0627\u0632 \u0622\u06cc\u062a\u0645 #{db_item.id}\n{_delivered_payload_preview(db_item.payload, db_item.file_id)}')
    return '\n\n'.join(lines) if lines else '\u2014'

def _payment_text(payment) -> str:
    if not payment:
        return '—'
    lines = [
        f'روش: {_payment_method_title(payment.method)}',
        f'وضعیت پرداخت: {payment.status or "—"}',
        f'مبلغ پرداخت: {money(payment.amount)}',
    ]
    if payment.transaction_id:
        lines.append(f'کد تراکنش: {payment.transaction_id}')
    if payment.authority:
        lines.append(f'شناسه درگاه/authority: {payment.authority}')
    if payment.receipt_text:
        lines.append(f'توضیح رسید: {payment.receipt_text}')
    wallets_text = _crypto_wallets_admin_text(payment)
    if wallets_text:
        lines.append(wallets_text)
    return '\n'.join(lines)


def _order_detail_text(order: Order, status_line: str | None = None) -> str:
    payment = _latest_payment(order)
    user = order.user
    product = order.product
    lines = [
        '📦 جزئیات سفارش',
        '',
        f'شناسه داخلی: #{order.id}',
        f'شماره یکتا سفارش: {order.order_number}',
        f'وضعیت: {_status_title(order.status)}',
        f'مبلغ: {money(order.amount)}',
        _order_quantity_text(order),
        f'روش پرداخت سفارش: {_payment_method_title(order.payment_method or (payment.method if payment else None))}',
        '',
        '👤 مشخصات مشتری',
        f'نام: {user.first_name or "—"} {user.last_name or ""}'.strip(),
        f'یوزرنیم: @{user.username}' if user.username else 'یوزرنیم: —',
        f'آیدی تلگرام: {user.telegram_id}',
        f'شماره تلفن ثبت‌شده: {user.phone_number or "—"}',
        '',
        '🛍 محصول',
        f'شناسه محصول: #{product.id}',
        f'عنوان محصول: {product.title}',
        f'نوع محصول: {product.kind}',
        f'شیوه تحویل: {product.delivery_kind}',
        '',
        '📦 محتوای تحویل‌شده به مشتری',
        _delivered_items_text(order),
        '',
        '📝 اطلاعات ارسال‌شده مشتری',
        _fields_text(order.user_fields, include_discount=True),
        '',
        '💳 اطلاعات پرداخت',
        _payment_text(payment),
        '',
        '⏱ زمان‌ها',
        f'ثبت سفارش: {_format_dt(order.created_at)}',
        f'تایید پرداخت: {_format_dt(order.paid_at)}',
        f'تکمیل سفارش: {_format_dt(order.completed_at)}',
    ]
    if order.internal_note:
        lines.extend(['', f'یادداشت داخلی: {order.internal_note}'])
    if status_line:
        lines.extend(['', status_line])
    return '\n'.join(lines)[:3900]


def _safe_order_detail_text(order: Order, status_line: str | None = None) -> str:
    try:
        return _order_detail_text(order, status_line)
    except Exception as exc:
        payment = _latest_payment(order)
        user = getattr(order, 'user', None)
        product = getattr(order, 'product', None)
        lines = [
            '📦 جزئیات سفارش',
            '',
            '⚠️ بخشی از اطلاعات این سفارش ناقص/خراب بود، ولی اطلاعات اصلی برای بررسی نمایش داده شد.',
            f'خطای ساخت جزئیات کامل: {type(exc).__name__}: {exc}',
            '',
            f'شناسه داخلی: #{getattr(order, "id", "—")}',
            f'شماره یکتا سفارش: {getattr(order, "order_number", "—")}',
            f'وضعیت: {_status_title(getattr(order, "status", None))}',
            f'مبلغ: {money(getattr(order, "amount", 0) or 0)}',
            f'روش پرداخت: {_payment_method_title(getattr(order, "payment_method", None) or (payment.method if payment else None))}',
            '',
            f'مشتری: {getattr(user, "first_name", None) or "—"} (@{getattr(user, "username", None) or "—"})',
            f'آیدی تلگرام: {getattr(user, "telegram_id", None) or "—"}',
            f'محصول: {getattr(product, "title", None) or "—"}',
            '',
            'اطلاعات مشتری:',
            _fields_text(getattr(order, "user_fields", None), include_discount=True),
            '',
            'پرداخت:',
            _payment_text(payment),
        ]
        if getattr(order, 'internal_note', None):
            lines.extend(['', f'یادداشت داخلی: {order.internal_note}'])
        if status_line:
            lines.extend(['', status_line])
        return '\n'.join(lines)[:3900]


async def _send_order_review_to_admins(bot, session, order: Order, payment) -> tuple[int, list[str]]:
    admin_ids = await AdminService(session).get_admin_telegram_ids()
    messages: list[dict[str, Any]] = []
    errors: list[str] = []
    caption = _order_caption(order, payment)
    receipt_type = (payment.metadata_json or {}).get('receipt_content_type') if payment else None
    for admin_id in admin_ids:
        try:
            if payment and payment.receipt_file_id and receipt_type == 'document':
                sent = await bot.send_document(admin_id, document=payment.receipt_file_id, caption=caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'document'
            elif payment and payment.receipt_file_id:
                sent = await bot.send_photo(admin_id, photo=payment.receipt_file_id, caption=caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'photo'
            else:
                sent = await bot.send_message(admin_id, caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'text'
            messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': content_type})
        except Exception as exc:
            errors.append(f'{admin_id}: {type(exc).__name__}: {exc}')
            try:
                sent = await bot.send_message(admin_id, (caption + '\n\n⚠️ ارسال فایل رسید خطا داد، اما سفارش در لیست منتظر تایید قابل بررسی است.')[:3900], reply_markup=manual_review_keyboard(order.id))
                messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': 'text'})
            except Exception as fallback_exc:
                errors.append(f'{admin_id} fallback: {type(fallback_exc).__name__}: {fallback_exc}')
    if payment:
        meta = dict(payment.metadata_json or {})
        existing = list(meta.get('review_messages') or [])
        meta['review_messages'] = existing + messages
        if errors:
            meta['review_send_errors'] = list(meta.get('review_send_errors') or []) + errors[-20:]
            order.internal_note = _append_note(order.internal_note, 'خطا در ارسال/ارسال مجدد پیام رسید به ادمین‌ها: ' + ' | '.join(errors[-5:]))
        payment.metadata_json = meta
    await session.commit()
    return len(messages), errors


async def _edit_review_messages(bot, messages: list[dict], text: str, reply_markup=None) -> None:
    for item in messages or []:
        try:
            if item.get('content_type') in {'photo', 'document'}:
                await bot.edit_message_caption(
                    chat_id=item['chat_id'],
                    message_id=item['message_id'],
                    caption=text[:1024],
                    reply_markup=reply_markup,
                )
            else:
                await bot.edit_message_text(
                    chat_id=item['chat_id'],
                    message_id=item['message_id'],
                    text=text,
                    reply_markup=reply_markup,
                )
        except Exception:
            try:
                await bot.edit_message_reply_markup(chat_id=item['chat_id'], message_id=item['message_id'], reply_markup=reply_markup)
            except Exception:
                pass


async def _safe_edit_current_message(callback: CallbackQuery, text: str, caption_text: str | None = None, reply_markup=None) -> None:
    message = callback.message
    if not message:
        return
    try:
        if getattr(message, 'photo', None) or getattr(message, 'document', None):
            await message.edit_caption(caption=(caption_text or text)[:1024], reply_markup=reply_markup)
        else:
            await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await message.edit_reply_markup(reply_markup=reply_markup)
        except Exception:
            pass


async def _category_counts(session) -> dict[str, int]:
    result = await session.execute(select(Order))
    counts = {category: 0 for category in ORDER_CATEGORY_STATUSES}
    for order in result.scalars().all():
        if _is_admin_hidden(order):
            continue
        category = _category_for_status(order.status)
        if category in counts:
            counts[category] += 1
    return counts


async def _load_orders(session, category: str, page: int = 0, limit: int = PAGE_SIZE) -> tuple[list[Order], bool]:
    statuses = ORDER_CATEGORY_STATUSES.get(category)
    if not statuses:
        return [], False
    result = await session.execute(
        select(Order)
        .where(Order.status.in_(statuses))
        .options(selectinload(Order.user), selectinload(Order.product), selectinload(Order.payments), selectinload(Order.delivered_items))
        .order_by(Order.id.desc())
    )
    visible = [order for order in result.scalars().all() if not _is_admin_hidden(order)]
    start = max(page, 0) * limit
    end = start + limit
    return visible[start:end], len(visible) > end


async def _load_export_orders(session, category: str) -> list[Order]:
    statuses = ORDER_CATEGORY_STATUSES.get(category)
    if not statuses:
        return []
    result = await session.execute(
        select(Order)
        .where(Order.status.in_(statuses))
        .options(selectinload(Order.user), selectinload(Order.product), selectinload(Order.payments), selectinload(Order.delivered_items))
        .order_by(Order.id.desc())
    )
    return [order for order in result.scalars().all() if not _is_admin_hidden(order)]


async def _admin_cleanup_completed_rejected(session, admin_id: int, days: int | None) -> int:
    statuses = ORDER_CATEGORY_STATUSES['completed'] + ORDER_CATEGORY_STATUSES['rejected']
    result = await session.execute(
        select(Order)
        .where(Order.status.in_(statuses))
        .order_by(Order.id.desc())
    )
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=days) if days is not None else None
    count = 0
    for order in result.scalars().all():
        if _is_admin_hidden(order):
            continue
        ref_time = _reference_time_for_cleanup(order)
        if threshold is not None and ref_time and ref_time > threshold:
            continue
        fields = dict(order.user_fields or {})
        fields['_admin_hidden'] = {
            'hidden_at': now.isoformat(),
            'hidden_by': admin_id,
            'scope': f'older_than_{days}_days' if days is not None else 'all_completed_rejected',
        }
        order.user_fields = fields
        count += 1
    if count:
        await session.commit()
    return count


def _export_text(category: str, orders: list[Order]) -> str:
    title = ORDER_CATEGORY_TITLES.get(category, category)
    lines = [f'خروجی سفارش‌ها - {title}', '=' * 50, '']
    if not orders:
        lines.append('سفارشی در این دسته‌بندی وجود ندارد.')
        return '\n'.join(lines)
    for order in orders:
        payment = _latest_payment(order)
        user = order.user
        product = order.product
        lines.extend([
            f'شماره سفارش: {order.order_number}',
            f'شناسه داخلی: #{order.id}',
            f'وضعیت: {_status_title(order.status)}',
            f'مشتری: {user.first_name or "—"} (@{user.username or "—"}) | تلگرام: {user.telegram_id} | تلفن: {user.phone_number or "—"}',
            f'محصول: #{product.id} {product.title}',
            f'مبلغ: {money(order.amount)}',
            _order_quantity_text(order),
            f'روش پرداخت: {_payment_method_title(order.payment_method or (payment.method if payment else None))}',
            f'وضعیت پرداخت: {payment.status if payment else "—"}',
            f'کد تراکنش: {payment.transaction_id if payment and payment.transaction_id else "—"}',
            'اطلاعات مشتری:',
            _fields_text(order.user_fields, include_discount=True),
            'محتوای تحویل‌شده:',
            _delivered_items_text(order),
            f'ثبت: {_format_dt(order.created_at)} | پرداخت: {_format_dt(order.paid_at)} | تکمیل: {_format_dt(order.completed_at)}',
            '-' * 50,
        ])
    return '\n'.join(lines)


async def _send_orders_export(callback: CallbackQuery, category: str, orders: list[Order]) -> None:
    title = ORDER_CATEGORY_TITLES.get(category, category)
    content = _export_text(category, orders).encode('utf-8')
    file = BufferedInputFile(content, filename=f'orders_{category}.txt')
    await callback.message.answer_document(file, caption=f'📄 خروجی دسته‌بندی: {title}')


@router.callback_query(F.data == 'admin:orders')
async def admin_orders(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        counts = await _category_counts(session)
    await callback.message.answer('📦 مدیریت سفارش‌ها\n\nدسته‌بندی مورد نظر را انتخاب کن:', reply_markup=orders_admin_keyboard(counts))


@router.callback_query(F.data == 'admin:orders:cleanup')
async def admin_orders_cleanup_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_order_access(callback.from_user.id, MANAGE_ORDERS):
        await callback.message.answer('دسترسی نداری.')
        return
    await callback.message.answer(
        '🧹 پاکسازی لیست سفارش‌ها\n\n'
        'این گزینه سفارش را از دیتابیس حذف نمی‌کند؛ فقط از لیست‌های شلوغ ادمین مخفی می‌کند. '
        'سفارش برای مشتری و در جستجوی شماره یکتا همچنان باقی می‌ماند.',
        reply_markup=orders_cleanup_keyboard(),
    )


@router.callback_query(F.data.startswith('admin:orders:cleanup:'))
async def admin_orders_cleanup_apply(callback: CallbackQuery) -> None:
    await callback.answer('در حال پاکسازی')
    raw = callback.data.split(':')[-1]
    days = None if raw == 'all' else int(raw)
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        count = await _admin_cleanup_completed_rejected(session, callback.from_user.id, days)
        await admin_service.log(callback.from_user.id, 'cleanup_orders_admin_list', 'orders', raw, {'count': count})
        counts = await _category_counts(session)
    label = 'همه سفارش‌های تکمیل/ردشده' if days is None else f'سفارش‌های تکمیل/ردشده قدیمی‌تر از {days} روز'
    await callback.message.answer(f'✅ {count} سفارش از لیست ادمین مخفی شد.\nمحدوده: {label}', reply_markup=orders_admin_keyboard(counts))


@router.callback_query(F.data.startswith('admin:orders:list:'))
async def admin_orders_list(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    category = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 0
    if category not in ORDER_CATEGORY_STATUSES:
        await callback.message.answer('دسته‌بندی سفارش معتبر نیست.')
        return
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        orders, has_next = await _load_orders(session, category, page)
    title = ORDER_CATEGORY_TITLES.get(category, category)
    if not orders:
        await callback.message.answer(
            f'📦 {title}\n\nسفارشی در این دسته‌بندی وجود ندارد.',
            reply_markup=orders_list_keyboard(category, [], page, has_next=False),
        )
        return
    await callback.message.answer(
        f'📦 {title}\n\nبرای دیدن مشخصات مشتری، اطلاعات ارسال‌شده و عملیات سفارش، روی جزئیات بزن. برای خروجی کامل، فایل تکست بگیر.',
        reply_markup=orders_list_keyboard(category, orders, page, has_next=has_next),
    )


@router.callback_query(F.data.startswith('admin:orders:export:'))
async def admin_orders_export(callback: CallbackQuery) -> None:
    await callback.answer('در حال ساخت خروجی')
    category = callback.data.split(':')[-1]
    if category not in ORDER_CATEGORY_STATUSES:
        await callback.message.answer('دسته‌بندی سفارش معتبر نیست.')
        return
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        orders = await _load_export_orders(session, category)
    await _send_orders_export(callback, category, orders)


@router.callback_query(F.data.startswith('admin:order:detail:'))
async def admin_order_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    order_id = int(parts[3])
    category = parts[4] if len(parts) > 4 else None
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        order = await OrderService(session).get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        category = category or _category_for_status(order.status)
        text = _safe_order_detail_text(order)
        markup = order_detail_keyboard(order.id, category, order.status)
    await callback.message.answer(text, reply_markup=markup)


@router.callback_query(F.data == 'admin:orders:search')
async def admin_orders_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_order_access(callback.from_user.id, MANAGE_ORDERS):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.set_state(AdminOrderStates.waiting_search)
    await callback.message.answer('شماره یکتا سفارش را بفرست. مثال: ORD-20260424120000-1234')


@router.message(AdminOrderStates.waiting_search)
async def admin_orders_search_result(message: Message, state: FSMContext) -> None:
    if not await _has_order_access(message.from_user.id, MANAGE_ORDERS):
        await message.answer('دسترسی نداری.')
        await state.clear()
        return
    raw = (message.text or '').strip()
    cleaned = re.sub(r'[^A-Za-z0-9_-]', '', raw).upper()
    async with SessionLocal() as session:
        order = await OrderService(session).get_by_number(cleaned)
        if not order and raw.isdigit():
            order = await OrderService(session).get(int(raw))
        if not order:
            await message.answer('سفارشی با این شماره پیدا نشد.')
            await state.clear()
            return
        category = _category_for_status(order.status)
        text = _safe_order_detail_text(order)
        markup = order_detail_keyboard(order.id, category, order.status)
    await state.clear()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith('admin:resend_review:'))
async def resend_order_review(callback: CallbackQuery) -> None:
    await callback.answer('در حال ارسال مجدد')
    order_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_PAYMENTS):
            await callback.message.answer('دسترسی نداری.')
            return
        order = await OrderService(session).get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        payment = _latest_payment(order)
        count, errors = await _send_order_review_to_admins(callback.bot, session, order, payment)
        text = _safe_order_detail_text(order)
        markup = order_detail_keyboard(order.id, _category_for_status(order.status), order.status)
    await callback.message.answer(text, reply_markup=markup)
    if count:
        await callback.message.answer(f'پیام رسید برای {count} ادمین ارسال/ثبت شد ✅')
    else:
        msg = 'ارسال مجدد پیام رسید موفق نشد.'
        if errors:
            msg += '\nخطا: ' + '\n'.join(errors[-3:])
        await callback.message.answer(msg)


@router.callback_query(F.data.startswith('admin:deliver_text_prompt:'))
async def manual_text_delivery_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    order_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        order = await OrderService(session).get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        if order.status not in {OrderStatus.PROCESSING.value, OrderStatus.PAID.value}:
            await callback.message.answer('این سفارش برای تحویل متنی آماده نیست. اول باید پرداخت تایید شده باشد.')
            return
    await state.set_state(AdminOrderStates.waiting_manual_delivery_text)
    await state.update_data(
        order_id=order_id,
        source_chat_id=callback.message.chat.id if callback.message else None,
        source_message_id=callback.message.message_id if callback.message else None,
    )
    await callback.message.answer('متن تحویل کالا را بفرست. همین متن مستقیم برای مشتری ارسال می‌شود و سفارش تکمیل خواهد شد.')


@router.message(AdminOrderStates.waiting_manual_delivery_text)
async def manual_text_delivery_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get('order_id') or 0)
    delivery_text = (message.text or message.caption or '').strip()
    if not delivery_text:
        await message.answer('متن تحویل خالی است. متن قابل ارسال برای مشتری را بفرست.')
        return
    admin_name = ' '.join(part for part in [message.from_user.first_name, message.from_user.last_name] if part) or (message.from_user.username or str(message.from_user.id))
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(message.from_user.id, MANAGE_ORDERS):
            await message.answer('دسترسی نداری.')
            await state.clear()
            return
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        if not order:
            await message.answer('سفارش پیدا نشد.')
            await state.clear()
            return
        if order.status not in {OrderStatus.PROCESSING.value, OrderStatus.PAID.value}:
            await message.answer('این سفارش دیگر در وضعیت قابل تحویل نیست.')
            await state.clear()
            return
        try:
            await message.bot.send_message(order.user.telegram_id, f'📦 تحویل سفارش {order.order_number}\n\n{delivery_text}')
            texts = await SettingsService(session).get('texts')
            await message.bot.send_message(
                order.user.telegram_id,
                (texts.get('order_completed') or '✅ سفارش {order_number} تکمیل شد. ممنون از خریدت.').format(order_number=order.order_number),
            )
        except Exception as exc:
            await message.answer('ارسال متن تحویل به مشتری ناموفق بود و سفارش تکمیل نشد. خطا: ' + str(exc))
            return
        fields = dict(order.user_fields or {})
        delivered_items = list(fields.get('_delivered_items') or [])
        delivered_items.append({
            'delivery_type': 'manual_text',
            'payload': delivery_text,
            'file_id': None,
            'delivered_at': datetime.now(timezone.utc).isoformat(),
            'admin': admin_name,
        })
        fields['_delivered_items'] = delivered_items
        order.user_fields = fields
        order.status = OrderStatus.COMPLETED.value
        order.completed_at = datetime.now(timezone.utc)
        order.internal_note = _append_note(order.internal_note, f'تحویل متنی توسط {admin_name}')
        await ProductService(session).consume_stock(order.product, order_quantity(order))
        await session.commit()
        await admin_service.log(message.from_user.id, 'complete_order_text_delivery', 'order', str(order.id), {'admin': admin_name})
        payment = _latest_payment(order)
        status_line = f'📝 سفارش توسط {admin_name} با متن دستی تحویل و تکمیل شد.'
        review_messages = (payment.metadata_json or {}).get('review_messages') if payment else []
        await _edit_review_messages(message.bot, review_messages, _order_caption(order, payment, status_line), reply_markup=None)
        detail_text = _safe_order_detail_text(order, status_line)
    source_chat_id = data.get('source_chat_id')
    source_message_id = data.get('source_message_id')
    if source_chat_id and source_message_id:
        try:
            await message.bot.edit_message_reply_markup(chat_id=source_chat_id, message_id=source_message_id, reply_markup=None)
        except Exception:
            pass
    await state.clear()
    await message.answer('متن برای مشتری ارسال شد و سفارش به پردازش/تکمیل‌شده منتقل شد ✅')
    await message.answer(detail_text)


@router.callback_query(F.data.startswith('admin:approve_payment:'))
async def approve_payment(callback: CallbackQuery) -> None:
    await callback.answer('پرداخت تایید شد')
    order_id = int(callback.data.split(':')[-1])
    admin_name = _admin_title(callback)
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_PAYMENTS):
            await callback.message.answer('دسترسی نداری.')
            return
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        order = await order_service.mark_paid(order, transaction_id=f'manual:{order.order_number}')
        order.status = OrderStatus.PROCESSING.value
        await session.commit()
        await DiscountService(session).mark_order_redeemed(order)
        await ReferralService(session).register_commission(order, callback.bot)
        texts = await SettingsService(session).get('texts')
        await admin_service.log(callback.from_user.id, 'approve_payment', 'order', str(order.id), {'admin': admin_name})
        await callback.bot.send_message(
            order.user.telegram_id,
            (texts.get('payment_approved') or '✅ پرداخت سفارش {order_number} تایید شد و سفارش در مرحله پردازش قرار گرفت.').format(order_number=order.order_number),
        )

        final_markup = order_processing_keyboard(order.id)
        final_answer = 'پرداخت تایید شد ✅ دکمه تایید/رد حذف شد و دکمه «تحویل سفارش» همین‌جا نمایش داده شد. همچنین سفارش از دسته‌بندی «منتظر پردازش» قابل تحویل است.'
        if should_auto_deliver_after_payment(order.product):
            try:
                success, delivery_message = await DeliveryService(session).deliver(callback.bot, order)
            except Exception as exc:
                await session.rollback()
                order = await order_service.get(order_id)
                if order:
                    order.status = OrderStatus.PROCESSING.value
                    await session.commit()
                success = False
                delivery_message = str(exc)
            if success:
                await admin_service.log(callback.from_user.id, 'complete_order', 'order', str(order.id), {'admin': f'{admin_name} (تحویل خودکار)'})
                status_line = f'✅ پرداخت توسط {admin_name} تایید شد و محصول اتوتکست به صورت خودکار تحویل شد. سفارش به دسته‌بندی «پردازش/تکمیل شده» منتقل شد.'
                final_markup = None
                final_answer = 'پرداخت تایید شد و تحویل خودکار اتوتکست انجام شد ✅'
            else:
                status_line = f'✅ پرداخت توسط {admin_name} تایید شد، اما تحویل خودکار انجام نشد: {delivery_message}\nسفارش در «منتظر پردازش» ماند و می‌توانی دستی تحویل بزنی.'
        else:
            status_line = f'✅ پرداخت توسط {admin_name} تایید شد. سفارش به دسته‌بندی «منتظر پردازش» منتقل شد.'

        payment = _latest_payment(order)
        review_messages = (payment.metadata_json or {}).get('review_messages') if payment else []
        await _edit_review_messages(
            callback.bot,
            review_messages,
            _order_caption(order, payment, status_line),
            reply_markup=final_markup,
        )
        detail_text = _safe_order_detail_text(order, status_line)
        caption_text = _order_caption(order, payment, status_line)
    await _safe_edit_current_message(callback, detail_text, caption_text=caption_text, reply_markup=final_markup)
    await callback.message.answer(final_answer)


@router.callback_query(F.data.startswith('admin:reject_payment:'))
async def reject_payment(callback: CallbackQuery) -> None:
    await callback.answer('رسید رد شد')
    order_id = int(callback.data.split(':')[-1])
    admin_name = _admin_title(callback)
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_PAYMENTS):
            await callback.message.answer('دسترسی نداری.')
            return
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        await order_service.mark_failed(order, note=f'Receipt rejected by {admin_name}')
        texts = await SettingsService(session).get('texts')
        await admin_service.log(callback.from_user.id, 'reject_payment', 'order', str(order.id), {'admin': admin_name})
        payment = _latest_payment(order)
        status_line = f'❌ رسید توسط {admin_name} رد شد. سفارش به دسته‌بندی «رد شده/لغوشده» منتقل شد.'
        review_messages = (payment.metadata_json or {}).get('review_messages') if payment else []
        await _edit_review_messages(callback.bot, review_messages, _order_caption(order, payment, status_line), reply_markup=None)
        await callback.bot.send_message(
            order.user.telegram_id,
            (texts.get('payment_rejected') or '❌ رسید سفارش {order_number} تایید نشد.').format(order_number=order.order_number),
        )
        detail_text = _safe_order_detail_text(order, status_line)
        caption_text = _order_caption(order, payment, status_line)
    await _safe_edit_current_message(callback, detail_text, caption_text=caption_text, reply_markup=None)
    await callback.message.answer('رسید رد شد ✅ دکمه‌ها حذف شدند و سفارش به «رد شده/لغوشده» منتقل شد.')


@router.callback_query(F.data.startswith('admin:complete_order:'))
async def complete_order(callback: CallbackQuery) -> None:
    await callback.answer('سفارش تکمیل شد')
    order_id = int(callback.data.split(':')[-1])
    admin_name = _admin_title(callback)
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.has_permission(callback.from_user.id, MANAGE_ORDERS):
            await callback.message.answer('دسترسی نداری.')
            return
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            return
        if order.status not in {OrderStatus.PROCESSING.value, OrderStatus.PAID.value}:
            await callback.message.answer('این سفارش در وضعیت قابل تحویل نیست. اول باید پرداخت تایید شده باشد.')
            return
        try:
            success, delivery_message = await DeliveryService(session).deliver(callback.bot, order)
        except Exception as exc:
            await session.rollback()
            await callback.message.answer('تحویل انجام نشد و سفارش تکمیل نشد. خطا: ' + str(exc))
            return
        if not success:
            await callback.message.answer('تحویل انجام نشد: ' + delivery_message)
            return
        await admin_service.log(callback.from_user.id, 'complete_order', 'order', str(order.id), {'admin': admin_name})
        payment = _latest_payment(order)
        status_line = f'📦 سفارش توسط {admin_name} تکمیل و تحویل شد. سفارش به دسته‌بندی «پردازش/تکمیل شده» منتقل شد.'
        review_messages = (payment.metadata_json or {}).get('review_messages') if payment else []
        await _edit_review_messages(callback.bot, review_messages, _order_caption(order, payment, status_line), reply_markup=None)
        detail_text = _safe_order_detail_text(order, status_line)
        caption_text = _order_caption(order, payment, status_line)
    await _safe_edit_current_message(callback, detail_text, caption_text=caption_text, reply_markup=None)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('سفارش تکمیل و تحویل شد ✅ دکمه تحویل حذف شد و سفارش به «پردازش/تکمیل شده» منتقل شد.')


@router.callback_query(F.data.startswith('admin:topup:approve:'))
async def approve_topup(callback: CallbackQuery) -> None:
    await callback.answer('شارژ تایید شد')
    topup_id = int(callback.data.split(':')[-1])
    admin_name = _admin_title(callback)
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_PAYMENTS):
            await callback.message.answer('دسترسی نداری.')
            return
        service = WalletTopupService(session)
        topup = await service.get(topup_id)
        if not topup:
            await callback.message.answer('درخواست شارژ پیدا نشد.')
            return
        topup = await service.mark_paid(topup, transaction_id=f'manual:{topup.topup_number}')
        texts = await SettingsService(session).get('texts')
        await AdminService(session).log(callback.from_user.id, 'approve_topup', 'wallet_topup', str(topup.id), {'admin': admin_name})
        status_line = f'✅ شارژ کیف پول توسط {admin_name} تایید شد.'
        await _edit_review_messages(callback.bot, (topup.metadata_json or {}).get('review_messages') or [], _topup_caption(topup, status_line))
        await callback.bot.send_message(
            topup.user.telegram_id,
            (texts.get('wallet_charge_paid') or '✅ شارژ کیف پول به مبلغ {amount} تایید شد. موجودی فعلی: {balance}').format(
                amount=money(topup.amount),
                balance=money(topup.user.wallet_balance),
            ),
        )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('شارژ کیف پول تایید شد ✅')


@router.callback_query(F.data.startswith('admin:topup:reject:'))
async def reject_topup(callback: CallbackQuery) -> None:
    await callback.answer('شارژ رد شد')
    topup_id = int(callback.data.split(':')[-1])
    admin_name = _admin_title(callback)
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_PAYMENTS):
            await callback.message.answer('دسترسی نداری.')
            return
        service = WalletTopupService(session)
        topup = await service.get(topup_id)
        if not topup:
            await callback.message.answer('درخواست شارژ پیدا نشد.')
            return
        topup = await service.mark_failed(topup, note=f'Rejected by {admin_name}')
        texts = await SettingsService(session).get('texts')
        await AdminService(session).log(callback.from_user.id, 'reject_topup', 'wallet_topup', str(topup.id), {'admin': admin_name})
        status_line = f'❌ شارژ کیف پول توسط {admin_name} رد شد.'
        await _edit_review_messages(callback.bot, (topup.metadata_json or {}).get('review_messages') or [], _topup_caption(topup, status_line))
        await callback.bot.send_message(topup.user.telegram_id, texts.get('wallet_charge_rejected') or '❌ رسید شارژ کیف پول تایید نشد.')
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('شارژ کیف پول رد شد ✅')
