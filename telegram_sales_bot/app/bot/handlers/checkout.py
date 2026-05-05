from __future__ import annotations

from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.admin import manual_review_keyboard
from app.bot.keyboards.user import DEFAULT_MENU_LABELS, discount_choice_keyboard, payment_methods_keyboard, payment_receipt_actions_keyboard, quantity_keyboard
from app.bot.states.order import CheckoutStates
from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.delivery_service import DeliveryService
from app.services.discount_service import DiscountService
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.crypto_rate_service import format_crypto_wallet_copy_text, format_crypto_wallets_text
from app.services.payments.registry import PaymentRegistry
from app.services.product_service import ProductService, allow_quantity_purchase, product_has_enough_stock, product_max_quantity, product_price_display, should_auto_deliver_after_payment, variant_parent_id
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.text import money

router = Router(name='checkout')


def _field_keys(product) -> list[str]:
    return [str(field.get('name') or field.get('type') or '').strip() for field in (product.required_fields or []) if (field.get('name') or field.get('type'))]


def _field_prompt(product, texts: dict[str, Any], field_key: str) -> str:
    for field in (getattr(product, 'required_fields', None) or []):
        key = str(field.get('name') or field.get('type') or '').strip()
        if key == field_key and str(field.get('prompt') or '').strip():
            return str(field.get('prompt')).strip()
    return texts.get(f'request_{field_key}') or texts.get('request_note') or f'لطفاً {field_key} را ارسال کن:'


FIELD_TITLES = {
    'email': 'ایمیل',
    'phone': 'شماره تلفن',
    'username': 'آیدی/نام کاربری',
    'note': 'توضیحات',
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


def _crypto_wallets_text(wallets: list[dict[str, Any]] | None, *, show_unit_price: bool = False) -> str:
    return format_crypto_wallets_text(wallets, show_unit_price=show_unit_price)


def _custom_payment_titles(plisio_cfg: dict[str, Any] | None = None, crypto_manual_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    titles: dict[str, str] = {}
    plisio_label = str((plisio_cfg or {}).get('display_label') or '').strip()
    crypto_manual_label = str((crypto_manual_cfg or {}).get('display_label') or '').strip()
    if plisio_label:
        titles[PaymentMethod.PLISIO.value] = plisio_label
    if crypto_manual_label:
        titles[PaymentMethod.CRYPTO_MANUAL.value] = crypto_manual_label
    return titles


def _format_plisio_pay_text(template: str, invoice_url: str, extra: dict[str, Any], **context: Any) -> str:
    source_rate_line = str(extra.get('_source_rate_line') or '').strip()
    values = {
        'invoice_url': invoice_url or '—',
        'crypto_amount': extra.get('invoice_total_sum') or extra.get('amount') or extra.get('pending_amount') or '—',
        'currency': extra.get('currency') or extra.get('psys_cid') or '—',
        'wallet_hash': extra.get('wallet_hash') or 'در لینک پرداخت نمایش داده می‌شود',
        'source_amount': extra.get('_source_amount') or extra.get('source_amount') or '—',
        'source_rate': extra.get('_source_rate_toman_display') or extra.get('_source_rate_toman') or '—',
        'source_rate_toman': extra.get('_source_rate_toman_display') or extra.get('_source_rate_toman') or '—',
        'source_rate_line': source_rate_line,
        'source_rate_mode': extra.get('_source_rate_mode') or '—',
        'source_rate_error': extra.get('_source_rate_error') or '',
    }
    values.update(context)
    text = template.format(**values)
    if source_rate_line and source_rate_line not in text:
        text += f'\n\n{source_rate_line}'
    return text


def _menu_text_values(menu_labels: dict[str, Any] | None) -> set[str]:
    values = set(DEFAULT_MENU_LABELS.values())
    values.update(str(value) for value in (menu_labels or {}).values() if value)
    return {value.strip() for value in values if value and value.strip()}


def _looks_like_menu_or_command(text: str | None, menu_labels: dict[str, Any] | None) -> bool:
    value = (text or '').strip()
    if not value:
        return False
    return value.startswith('/') or value in _menu_text_values(menu_labels)


def _append_note(current: str | None, new_note: str) -> str:
    current = (current or '').strip()
    return (current + '\n' + new_note).strip() if current else new_note


def _field_label(product, field_key: str) -> str:
    for field in (getattr(product, 'required_fields', None) or []):
        key = str(field.get('name') or field.get('type') or '').strip()
        if key == field_key:
            return str(field.get('label') or FIELD_TITLES.get(field_key, field_key)).strip()
    return FIELD_TITLES.get(field_key, field_key)


def _combined_fields_prompt(product, texts: dict[str, Any], fields: list[str]) -> str:
    lines = ['لطفاً همه اطلاعات موردنیاز این سفارش را در یک پیام بفرست:']
    for index, key in enumerate(fields, 1):
        prompt = _field_prompt(product, texts, key)
        label = _field_label(product, key)
        lines.append(f'{index}. {label}: {prompt}')
    lines.append('مثلاً هر مورد را در یک خط جدا بنویس تا ادمین راحت‌تر بررسی کند.')
    return '\n'.join(lines)


def _format_user_fields(fields: dict[str, Any]) -> str:
    visible = {k: v for k, v in (fields or {}).items() if k != 'applied_discount' and not str(k).startswith('_')}
    if not visible:
        return '—'
    return '\n'.join(f'• {key}: {value}' for key, value in visible.items())



def _quantity_from_fields(fields: dict[str, Any] | None) -> int:
    try:
        return max(1, int((fields or {}).get('_quantity') or 1))
    except (TypeError, ValueError):
        return 1


def _quantity_line(order) -> str:
    quantity = _quantity_from_fields(order.user_fields)
    if quantity <= 1:
        return 'تعداد: 1'
    unit_price = (order.user_fields or {}).get('_unit_price')
    unit = f' | قیمت واحد: {money(unit_price)}' if unit_price else ''
    return f'تعداد: {quantity}{unit}'


def _quantity_selector_text(product, quantity: int) -> str:
    quantity = max(1, int(quantity or 1))
    lines = [
        '🔢 تعداد مورد نیاز را انتخاب کن:',
        f'محصول: {product.title}',
        f'قیمت واحد: {product_price_display(product)}',
        f'تعداد انتخابی: {quantity}',
        f'جمع قابل پرداخت: {product_price_display(product, quantity)}',
    ]
    max_qty = product_max_quantity(product)
    if max_qty is not None:
        lines.append(f'موجودی قابل خرید: {max_qty}')
    return '\n'.join(lines)


def _order_review_text(order, payment=None, status_line: str | None = None) -> str:
    user = order.user
    method = payment.method if payment else order.payment_method
    lines = [
        f'🧾 رسید پرداخت ({_payment_method_title(method)})',
        f'شماره سفارش: {order.order_number}',
        f'کاربر: {user.first_name or "—"} (@{user.username or "—"})',
        f'آیدی تلگرام: {user.telegram_id}',
        f'محصول: {order.product.title}',
        f'مبلغ: {money(order.amount)}',
        f'روش پرداخت: {_payment_method_title(method)}',
        _quantity_line(order),
        f'اطلاعات مشتری:\n{_format_user_fields(order.user_fields)}',
    ]
    if payment and payment.receipt_text:
        lines.append(f'توضیح رسید: {payment.receipt_text}')
    if status_line:
        lines.append('')
        lines.append(status_line)
    text = '\n'.join(lines)
    return text[:1024]


async def _send_review_to_admins(bot, session, order, payment) -> None:
    admin_ids = await AdminService(session).get_admin_telegram_ids()
    review_messages: list[dict[str, Any]] = []
    send_errors: list[str] = []
    caption = _order_review_text(order, payment)
    receipt_type = (payment.metadata_json or {}).get('receipt_content_type')
    for admin_id in admin_ids:
        try:
            if payment.receipt_file_id and receipt_type == 'document':
                sent = await bot.send_document(admin_id, document=payment.receipt_file_id, caption=caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'document'
            elif payment.receipt_file_id:
                sent = await bot.send_photo(admin_id, photo=payment.receipt_file_id, caption=caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'photo'
            else:
                sent = await bot.send_message(admin_id, caption, reply_markup=manual_review_keyboard(order.id))
                content_type = 'text'
            review_messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': content_type})
        except Exception as exc:
            send_errors.append(f'{admin_id}: {type(exc).__name__}: {exc}')
            # اگر ارسال عکس/فایل رسید خطا داد، حداقل پیام متنی با دکمه تایید/رد ارسال شود.
            try:
                fallback_text = caption + '\n\n⚠️ ارسال فایل/رسید اصلی به این ادمین خطا داد، اما سفارش در لیست منتظر تایید قابل بررسی است.'
                sent = await bot.send_message(admin_id, fallback_text[:3900], reply_markup=manual_review_keyboard(order.id))
                review_messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': 'text'})
            except Exception as fallback_exc:
                send_errors.append(f'{admin_id} fallback: {type(fallback_exc).__name__}: {fallback_exc}')
    meta = dict(payment.metadata_json or {})
    meta['review_messages'] = review_messages
    if send_errors:
        meta['review_send_errors'] = send_errors[-20:]
        note = (order.internal_note or '').strip()
        error_note = 'خطا در ارسال پیام رسید به ادمین‌ها: ' + ' | '.join(send_errors[-5:])
        order.internal_note = (note + '\n' + error_note).strip() if note else error_note
    payment.metadata_json = meta
    await session.commit()


async def _paid_without_delivery(bot, session, order, transaction_id: str | None = None) -> None:
    order_service = OrderService(session)
    order = await order_service.mark_paid(order, transaction_id=transaction_id)
    order.status = OrderStatus.PROCESSING.value
    await session.commit()
    await DiscountService(session).mark_order_redeemed(order)
    await ReferralService(session).register_commission(order, bot)
    texts = await SettingsService(session).get('texts')
    await bot.send_message(order.user.telegram_id, (texts.get('payment_approved') or 'پرداخت سفارش {order_number} تایید شد.').format(order_number=order.order_number))

    delivery_note = ''
    if should_auto_deliver_after_payment(order.product):
        try:
            success, delivery_message = await DeliveryService(session).deliver(bot, order)
        except Exception as exc:
            await session.rollback()
            order = await order_service.get(order.id)
            if order:
                order.status = OrderStatus.PROCESSING.value
                await session.commit()
            success = False
            delivery_message = str(exc)
        if success:
            await AdminService(session).log(0, 'complete_order', 'order', str(order.id), {'admin': 'سیستم (تحویل خودکار)'})
            delivery_note = '\nوضعیت تحویل: اتوتکست به صورت خودکار تحویل شد.'
        else:
            delivery_note = f'\nوضعیت تحویل: تحویل خودکار انجام نشد و سفارش منتظر پردازش ماند. علت: {delivery_message}'

    admin_title = '✅ سفارش پرداخت و خودکار تحویل شد' if order and order.status == OrderStatus.COMPLETED.value else '✅ سفارش پرداخت شد و در انتظار تکمیل است'
    admin_text = (
        f'{admin_title}\n'
        f'شماره سفارش: {order.order_number}\n'
        f'کاربر: {order.user.first_name or "—"} (@{order.user.username or "—"})\n'
        f'محصول: {order.product.title}\n'
        f'مبلغ: {money(order.amount)}\n'
        f'{_quantity_line(order)}'
        f'{delivery_note}'
    )
    await NotificationService(session).notify_admins(bot, admin_text)


@router.callback_query(F.data.startswith('checkout:'))
async def start_checkout(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[1])
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
    if not product or not product.is_active or (product.extra_settings or {}).get('deleted'):
        await callback.message.answer('این محصول در دسترس نیست.')
        return
    if not product_has_enough_stock(product, 1):
        await callback.message.answer('موجودی این محصول تمام شده است.')
        return
    if allow_quantity_purchase(product):
        await state.clear()
        await callback.message.answer(
            _quantity_selector_text(product, 1),
            reply_markup=quantity_keyboard(product.id, 1, product_max_quantity(product)),
        )
        return
    await _start_checkout_with_quantity(callback.message, callback.from_user, product_id, 1, state)


@router.callback_query(F.data.startswith('qty:'))
async def quantity_callback(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(':')
    if len(parts) != 4:
        await callback.answer()
        return
    product_id = int(parts[1])
    quantity = max(1, int(parts[2] or 1))
    action = parts[3]
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
    if not product or not product.is_active or (product.extra_settings or {}).get('deleted'):
        await callback.answer('این محصول در دسترس نیست.', show_alert=True)
        return
    max_qty = product_max_quantity(product)
    if action == 'noop':
        await callback.answer()
        return
    if action == 'inc':
        if max_qty is not None and quantity >= max_qty:
            await callback.answer('موجودی به اندازه بیشتر نیست و افزایش مجاز نیست.', show_alert=True)
            return
        quantity += 1
    elif action == 'dec':
        quantity = max(1, quantity - 1)
    elif action == 'buy':
        if max_qty is not None and quantity > max_qty:
            await callback.answer('موجودی کافی نیست.', show_alert=True)
            return
        await callback.answer()
        await _start_checkout_with_quantity(callback.message, callback.from_user, product_id, quantity, state)
        return
    else:
        await callback.answer()
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            _quantity_selector_text(product, quantity),
            reply_markup=quantity_keyboard(product.id, quantity, max_qty),
        )
    except Exception:
        await callback.message.answer(
            _quantity_selector_text(product, quantity),
            reply_markup=quantity_keyboard(product.id, quantity, max_qty),
        )


async def _start_checkout_with_quantity(message: Message, telegram_user, product_id: int, quantity: int, state: FSMContext) -> None:
    quantity = max(1, int(quantity or 1))
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
        texts = await SettingsService(session).get('texts')
    if not product or not product.is_active or (product.extra_settings or {}).get('deleted'):
        await message.answer('این محصول در دسترس نیست.')
        return
    if not product_has_enough_stock(product, quantity):
        await message.answer('موجودی این محصول برای تعداد انتخابی کافی نیست.')
        await state.clear()
        return
    fields = _field_keys(product)
    if fields:
        await state.set_state(CheckoutStates.collecting_fields)
        collect_mode = 'single_message' if len(fields) > 1 else 'step'
        await state.update_data(product_id=product_id, quantity=quantity, field_keys=fields, field_index=0, user_fields={}, collect_mode=collect_mode)
        if collect_mode == 'single_message':
            await message.answer(_combined_fields_prompt(product, texts, fields))
        else:
            await message.answer(_field_prompt(product, texts, fields[0]))
        return
    await _create_order_and_continue(message, telegram_user, product_id, {}, state, quantity=quantity)


@router.message(CheckoutStates.collecting_fields)
async def collect_checkout_field(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fields = list(data.get('field_keys') or [])
    if data.get('collect_mode') == 'single_message':
        value = (message.text or message.caption or '').strip()
        if not value:
            await message.answer('لطفاً اطلاعات موردنیاز را در یک پیام متنی بفرست.')
            return
        labels = ', '.join(FIELD_TITLES.get(key, key) for key in fields)
        user_fields = {'اطلاعات مشتری': value, '_required_info': labels}
        await _create_order_and_continue(message, message.from_user, int(data['product_id']), user_fields, state, quantity=int(data.get('quantity') or 1))
        return
    index = int(data.get('field_index') or 0)
    if index >= len(fields):
        await _create_order_and_continue(message, message.from_user, int(data['product_id']), data.get('user_fields') or {}, state, quantity=int(data.get('quantity') or 1))
        return
    current = fields[index]
    user_fields = dict(data.get('user_fields') or {})
    user_fields[current] = message.text or message.caption or ''
    index += 1
    if index < len(fields):
        async with SessionLocal() as session:
            texts = await SettingsService(session).get('texts')
            product = await ProductService(session).get(int(data['product_id']))
        await state.update_data(field_index=index, user_fields=user_fields)
        await message.answer(_field_prompt(product, texts, fields[index]))
        return
    await _create_order_and_continue(message, message.from_user, int(data['product_id']), user_fields, state, quantity=int(data.get('quantity') or 1))


async def _create_order_and_continue(message: Message, telegram_user, product_id: int, user_fields: dict[str, Any], state: FSMContext, quantity: int = 1) -> None:
    async with SessionLocal() as session:
        user_service = UserService(session)
        user = await user_service.get_or_create(telegram_user.id, telegram_user.first_name, telegram_user.last_name, telegram_user.username)
        product = await ProductService(session).get(product_id)
        if not product:
            await message.answer('محصول پیدا نشد.')
            await state.clear()
            return
        quantity = max(1, int(quantity or 1))
        if not product_has_enough_stock(product, quantity):
            await message.answer('موجودی این محصول برای تعداد انتخابی کافی نیست.')
            await state.clear()
            return
        fields = dict(user_fields or {})
        fields['_quantity'] = quantity
        fields['_unit_price'] = str(product.price)
        fields['_unit_price_display'] = product_price_display(product)
        fields['_total_price_display'] = product_price_display(product, quantity)
        parent_id = variant_parent_id(product)
        if parent_id:
            fields['_variant_parent_id'] = parent_id
        order = await OrderService(session).create_order(user, product, fields, quantity=quantity)
        settings_service = SettingsService(session)
        discounts = await settings_service.get('discounts')
        payments = await settings_service.get('payments')
    await state.clear()
    if discounts.get('enabled') and discounts.get('apply_button_enabled', True):
        await state.update_data(order_id=order.id)
        await message.answer('سفارش ساخته شد. اگر کد تخفیف داری می‌توانی اعمال کنی.', reply_markup=discount_choice_keyboard())
        return
    await _choose_or_start_payment(message, order.id, payments, state)


@router.callback_query(F.data == 'discount:enter')
async def enter_discount(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        texts = await SettingsService(session).get('texts')
    await state.set_state(CheckoutStates.waiting_discount_code)
    await callback.message.answer(texts.get('discount_ask_code', 'کد تخفیف را ارسال کن:'))


@router.callback_query(F.data == 'discount:skip')
async def skip_discount(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    order_id = int(data.get('order_id'))
    await state.clear()
    async with SessionLocal() as session:
        payments = await SettingsService(session).get('payments')
    await _choose_or_start_payment(callback.message, order_id, payments, state)


@router.message(CheckoutStates.waiting_discount_code)
async def apply_discount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get('order_id'))
    async with SessionLocal() as session:
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        user = await UserService(session).get_by_telegram_id(message.from_user.id)
        texts = await SettingsService(session).get('texts')
        if not order or not user:
            await message.answer('سفارش پیدا نشد.')
            await state.clear()
            return
        result = await DiscountService(session).apply_to_order(message.text or '', order, user)
        payments = await SettingsService(session).get('payments')
        final_amount = result.final_amount if result.success else order.amount
    if not result.success:
        await message.answer(texts.get('discount_invalid', 'کد تخفیف معتبر نیست.'))
    else:
        await message.answer((texts.get('discount_applied') or 'کد اعمال شد. مبلغ نهایی: {final_amount}').format(
            original_amount=money(result.original_amount),
            discount_amount=money(result.discount_amount),
            final_amount=money(final_amount),
        ))
    await state.clear()
    if Decimal(str(final_amount)) <= 0:
        async with SessionLocal() as session:
            order = await OrderService(session).get(order_id)
            if order:
                await _paid_without_delivery(message.bot, session, order, transaction_id=f'discount:{order.order_number}')
        return
    await _choose_or_start_payment(message, order_id, payments, state)


async def _choose_or_start_payment(message: Message, order_id: int, payments_cfg: dict[str, Any], state: FSMContext | None = None, *, auto_start: bool = True) -> None:
    enabled = list(payments_cfg.get('enabled_methods') or ['card_to_card'])
    if not enabled:
        enabled = ['card_to_card']
    display_order = list(payments_cfg.get('display_order') or enabled)
    methods = [m for m in display_order if m in enabled]
    if auto_start and payments_cfg.get('auto_start_single_method', True) and len(methods) == 1:
        await _begin_payment(message, order_id, methods[0], state)
        return
    async with SessionLocal() as session:
        settings_service = SettingsService(session)
        texts = await settings_service.get('texts')
        plisio_cfg = await settings_service.get('plisio')
        crypto_manual_cfg = await settings_service.get('crypto_manual')
    titles = _custom_payment_titles(plisio_cfg, crypto_manual_cfg)
    await message.answer(texts.get('choose_payment_method', 'روش پرداخت را انتخاب کن:'), reply_markup=payment_methods_keyboard(methods, order_id=order_id, titles=titles))


@router.callback_query(F.data.startswith('pay:'))
async def pay_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) == 3:
        order_id = int(parts[1])
        method = parts[2]
    else:
        method = parts[1]
        data = await state.get_data()
        order_id = data.get('order_id')
        if not order_id:
            await callback.message.answer('سفارش فعال پیدا نشد. لطفاً خرید را دوباره شروع کن.')
            return
        order_id = int(order_id)
    await _begin_payment(callback.message, order_id, method, state)


async def _begin_payment(message: Message, order_id: int, method: str, state: FSMContext | None = None) -> None:
    async with SessionLocal() as session:
        order_service = OrderService(session)
        order = await order_service.get(order_id)
        if not order:
            await message.answer('سفارش پیدا نشد.')
            return
        user = order.user
        provider = PaymentRegistry(session, user).get(method)
        result = await provider.create_payment(order)
        texts = await SettingsService(session).get('texts')
        if not result.success:
            reply_markup = None
            if method == PaymentMethod.PLISIO.value and (result.extra or {}).get('error_code') == 'plisio_min_amount':
                reply_markup = payment_receipt_actions_keyboard(order.id)
            await message.answer(result.message, reply_markup=reply_markup)
            return
        if method == PaymentMethod.CARD_TO_CARD.value:
            payment = result.payment
            extra = result.extra or {}
            box = extra.get('box_text') or ''
            text = box.format(
                order_number=order.order_number,
                amount=money(order.amount),
                raw_amount=order.amount,
                card_number=extra.get('card_number') or '',
                card_holder=extra.get('card_holder') or '',
                bank=extra.get('bank') or '',
            )
            if state:
                await state.set_state(CheckoutStates.waiting_payment_receipt)
                await state.update_data(order_id=order.id, payment_id=payment.id if payment else None)
            await message.answer(text, reply_markup=payment_receipt_actions_keyboard(order.id))
            return
        if method == PaymentMethod.CRYPTO_MANUAL.value:
            payment = result.payment
            extra = result.extra or {}
            wallets = list(extra.get('wallets') or [])
            if not wallets and payment:
                wallets = list((payment.metadata_json or {}).get('wallets') or [])
            show_unit_price = bool(extra.get('show_unit_price', False))
            wallets_text = _crypto_wallets_text(wallets, show_unit_price=show_unit_price)
            instructions = str(extra.get('instructions') or '').strip()
            template = texts.get('crypto_manual_pay_message') or '🪙 پرداخت با رمزارز\n\nشماره سفارش: {order_number}\nمبلغ قابل پرداخت: {amount}\n\n{wallets_text}'
            text = template.format(
                order_number=order.order_number,
                amount=money(order.amount),
                raw_amount=order.amount,
                wallets_text=wallets_text,
                instructions=instructions,
                crypto_quote_errors='، '.join((extra.get('crypto_quote') or {}).get('errors') or []),
            )
            if instructions and instructions not in text:
                text += f'\n\n{instructions}'
            if state:
                await state.set_state(CheckoutStates.waiting_payment_receipt)
                await state.update_data(order_id=order.id, payment_id=payment.id if payment else None)
            await message.answer(text[:3900], reply_markup=payment_receipt_actions_keyboard(order.id, wallets=wallets))
            return
        if method == PaymentMethod.ZARINPAL.value:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='پرداخت زرین‌پال', url=result.payment_url)]])
            if state:
                await state.clear()
            await message.answer('برای پرداخت از لینک زیر استفاده کن:', reply_markup=keyboard)
            return
        if method == PaymentMethod.PLISIO.value:
            extra = result.extra or {}
            invoice_url = result.payment_url or extra.get('invoice_url') or '—'
            template = texts.get('plisio_pay_message') or 'برای پرداخت کریپتویی از لینک زیر استفاده کن:\n{invoice_url}'
            text = _format_plisio_pay_text(
                template,
                invoice_url,
                extra,
                order_number=order.order_number,
                amount=money(order.amount),
                raw_amount=order.amount,
            )
            keyboard = None
            if result.payment_url:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='پرداخت کریپتویی', url=result.payment_url)]])
            if state:
                await state.clear()
            await message.answer(text, reply_markup=keyboard)
            return
        if method == PaymentMethod.WALLET.value:
            await _paid_without_delivery(message.bot, session, order, transaction_id=f'wallet:{order.order_number}')
            if state:
                await state.clear()
            return


@router.callback_query(F.data.startswith('payflow:copy_wallet:'))
async def copy_order_crypto_wallet(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    try:
        order_id = int(parts[-2])
        index = int(parts[-1]) - 1
    except (TypeError, ValueError):
        await callback.message.answer('آدرس ولت پیدا نشد.')
        return
    async with SessionLocal() as session:
        order = await OrderService(session).get(order_id)
    if not order or not order.user or order.user.telegram_id != callback.from_user.id:
        await callback.message.answer('این آدرس برای سفارش شما پیدا نشد.')
        return
    payment = max(order.payments or [], key=lambda item: item.id, default=None)
    wallets = list((payment.metadata_json or {}).get('wallets') or []) if payment else []
    if index < 0 or index >= len(wallets):
        await callback.message.answer('آدرس ولت پیدا نشد.')
        return
    await callback.message.answer(format_crypto_wallet_copy_text(wallets[index]))


@router.callback_query(F.data.startswith('payflow:back:'))
async def payment_flow_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    order_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await OrderService(session).get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            await state.clear()
            return
        if order.status == OrderStatus.PENDING_MANUAL_REVIEW.value:
            await callback.message.answer('رسید این سفارش قبلاً ثبت شده و در حال بررسی است؛ امکان برگشت به پرداخت وجود ندارد.')
            await state.clear()
            return
        if order.status in {OrderStatus.PAID.value, OrderStatus.PROCESSING.value, OrderStatus.COMPLETED.value}:
            await callback.message.answer('این سفارش قبلاً پرداخت شده و امکان برگشت به روش پرداخت وجود ندارد.')
            await state.clear()
            return
        payment = order.payments[-1] if order.payments else None
        if payment and payment.status in {PaymentStatus.INITIATED.value, PaymentStatus.WAITING_RECEIPT.value}:
            payment.status = PaymentStatus.CANCELLED.value
        order.status = OrderStatus.WAITING_FOR_PAYMENT.value
        order.internal_note = _append_note(order.internal_note, 'مشتری از مرحله ارسال رسید به انتخاب روش پرداخت برگشت.')
        payments = await SettingsService(session).get('payments')
        await session.commit()
    await state.clear()
    await _choose_or_start_payment(callback.message, order_id, payments, state, auto_start=False)


@router.callback_query(F.data.startswith('payflow:cancel:'))
async def payment_flow_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer('لغو شد')
    order_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        order = await OrderService(session).get(order_id)
        if not order:
            await callback.message.answer('سفارش پیدا نشد.')
            await state.clear()
            return
        if order.status == OrderStatus.PENDING_MANUAL_REVIEW.value:
            await callback.message.answer('رسید این سفارش قبلاً ثبت شده و در حال بررسی است؛ برای لغو با پشتیبانی هماهنگ کن.')
            await state.clear()
            return
        if order.status in {OrderStatus.PAID.value, OrderStatus.PROCESSING.value, OrderStatus.COMPLETED.value}:
            await callback.message.answer('این سفارش قبلاً پرداخت شده و امکان لغو مستقیم ندارد.')
            await state.clear()
            return
        payment = order.payments[-1] if order.payments else None
        if payment and payment.status != PaymentStatus.VERIFIED.value:
            payment.status = PaymentStatus.CANCELLED.value
        order.status = OrderStatus.CANCELLED.value
        order.internal_note = _append_note(order.internal_note, 'سفارش توسط مشتری در مرحله پرداخت لغو شد.')
        await session.commit()
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('سفارش لغو شد و رسیدی برای ادمین ساخته نشد ✅')


@router.message(CheckoutStates.waiting_payment_receipt)
async def payment_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = int(data.get('order_id'))
    text = message.caption or message.text or ''
    receipt_content_type = 'text'
    file_id = message.photo[-1].file_id if message.photo else None
    if file_id:
        receipt_content_type = 'photo'
    if not file_id and message.document:
        file_id = message.document.file_id
        receipt_content_type = 'document'
    async with SessionLocal() as session:
        order_service = OrderService(session)
        settings_service = SettingsService(session)
        order = await order_service.get(order_id)
        texts = await settings_service.get('texts')
        menu_labels = await settings_service.get('menu')
        if not order:
            await message.answer('سفارش پیدا نشد.')
            await state.clear()
            return
        if not file_id and _looks_like_menu_or_command(text, menu_labels):
            await message.answer(
                'این پیام شبیه دکمه منو/دستور ربات است و به عنوان رسید ثبت نشد.\n'
                'لطفاً عکس فیش، فایل رسید یا هش/کد پیگیری پرداخت را ارسال کن؛ یا از دکمه‌های زیر برای برگشت و لغو استفاده کن.',
                reply_markup=payment_receipt_actions_keyboard(order.id),
            )
            return
        if not file_id and not (text or '').strip():
            await message.answer(
                'رسید معتبر دریافت نشد. لطفاً عکس فیش، فایل رسید یا هش/کد پیگیری پرداخت را ارسال کن.',
                reply_markup=payment_receipt_actions_keyboard(order.id),
            )
            return
        payment = await order_service.attach_receipt(order, text=text, file_id=file_id)
        if payment:
            meta = dict(payment.metadata_json or {})
            meta['receipt_content_type'] = receipt_content_type
            payment.metadata_json = meta
            await session.commit()
            await _send_review_to_admins(message.bot, session, order, payment)
    await state.clear()
    await message.answer(texts.get('receipt_received', 'رسید ثبت شد ✅ بعد از بررسی ادمین نتیجه برایت ارسال می‌شود.'))
