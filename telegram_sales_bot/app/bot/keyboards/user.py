from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

DEFAULT_MENU_LABELS = {
    'products': '🛍 محصولات',
    'tutorials': '🎬 آموزش‌ها',
    'orders': '📦 سفارش‌های من',
    'support': '☎️ پشتیبانی',
    'wallet': '💰 کیف پول',
    'referral': '👥 زیرمجموعه‌گیری',
    'admin_panel': '⚙️ پنل ادمین',
    'send_phone': '📱 ارسال شماره',
}


def _labels(labels: dict | None) -> dict:
    merged = dict(DEFAULT_MENU_LABELS)
    merged.update(labels or {})
    return merged


def main_menu(is_admin: bool = False, labels: dict | None = None, features: dict | None = None) -> ReplyKeyboardMarkup:
    labels = _labels(labels)
    features = features or {}
    rows: list[list[KeyboardButton]] = [[KeyboardButton(text=labels['products'])]]
    if features.get('tutorials_enabled', True):
        rows.append([KeyboardButton(text=labels['tutorials'])])
    rows.append([KeyboardButton(text=labels['orders']), KeyboardButton(text=labels['wallet'])])
    rows.append([KeyboardButton(text=labels['support']), KeyboardButton(text=labels['referral'])])
    if is_admin:
        rows.append([KeyboardButton(text=labels['admin_panel'])])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def phone_request_keyboard(labels: dict | None = None) -> ReplyKeyboardMarkup:
    labels = _labels(labels)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=labels['send_phone'], request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def product_categories_keyboard(categories: list[dict], counts: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    counts = counts or {}
    builder = InlineKeyboardBuilder()
    for cat in categories:
        if not cat.get('is_active', True):
            continue
        cat_id = str(cat.get('id'))
        title = str(cat.get('title') or cat_id)
        builder.button(text=f'📁 {title}', callback_data=f'catalog:cat:{cat_id}')
    if counts.get('uncategorized', 0):
        builder.button(text='📁 بدون دسته', callback_data='catalog:cat:uncategorized')
    builder.adjust(1)
    return builder.as_markup()


def products_keyboard(products: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.button(text=str(product.title), callback_data=f'product:{product.id}')
    builder.button(text='⬅️ دسته‌بندی‌ها', callback_data='catalog:categories')
    builder.adjust(1)
    return builder.as_markup()


def product_keyboard(product_id: int, back_callback: str = 'catalog:back') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='🛒 خرید', callback_data=f'checkout:{product_id}')
    builder.button(text='⬅️ برگشت', callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def product_variants_keyboard(parent_id: int, variants: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in variants:
        builder.button(text=str(product.title), callback_data=f'product:{product.id}')
    builder.button(text='⬅️ دسته‌بندی‌ها', callback_data='catalog:back')
    builder.adjust(1)
    return builder.as_markup()


def quantity_keyboard(product_id: int, quantity: int = 1, max_quantity: int | None = None, back_callback: str | None = None) -> InlineKeyboardMarkup:
    quantity = max(1, int(quantity or 1))
    builder = InlineKeyboardBuilder()
    builder.button(text='➖', callback_data=f'qty:{product_id}:{quantity}:dec')
    builder.button(text=f'تعداد: {quantity}', callback_data=f'qty:{product_id}:{quantity}:noop')
    builder.button(text='➕', callback_data=f'qty:{product_id}:{quantity}:inc')
    builder.button(text='✅ ادامه خرید', callback_data=f'qty:{product_id}:{quantity}:buy')
    builder.button(text='⬅️ برگشت', callback_data=back_callback or f'product:{product_id}')
    builder.adjust(3, 1, 1)
    return builder.as_markup()


def payment_methods_keyboard(methods: list[str], order_id: int | None = None, titles: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    default_titles = {
        'card_to_card': '💳 کارت‌به‌کارت',
        'zarinpal': '🌐 زرین‌پال',
        'plisio': '🪙 پرداخت کریپتویی آنلاین',
        'crypto_manual': '🪙 پرداخت با رمز ارز',
        'wallet': '💰 کیف پول',
    }
    titles = {**default_titles, **(titles or {})}
    builder = InlineKeyboardBuilder()
    for method in methods:
        data = f'pay:{order_id}:{method}' if order_id is not None else f'pay:{method}'
        builder.button(text=titles.get(method, method), callback_data=data)
    builder.adjust(1)
    return builder.as_markup()


def _wallet_copy_button_text(wallet: dict, index: int) -> str:
    symbol = str(wallet.get('coin_symbol') or wallet.get('coin') or wallet.get('currency') or '').strip()
    network = str(wallet.get('network') or '').strip()
    label = 'آدرس ولت'
    if symbol:
        label += f' {symbol}'
    if network and network != '—':
        label += f' ({network})'
    return f'📋 {label}' if label.strip() else f'📋 آدرس ولت {index}'


def payment_receipt_actions_keyboard(order_id: int, wallets: list[dict] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, wallet in enumerate(wallets or [], 1):
        if not isinstance(wallet, dict) or not wallet.get('address'):
            continue
        builder.button(text=_wallet_copy_button_text(wallet, index), callback_data=f'payflow:copy_wallet:{order_id}:{index}')
    builder.button(text='⬅️ برگشت به روش‌های پرداخت', callback_data=f'payflow:back:{order_id}')
    builder.button(text='❌ لغو سفارش', callback_data=f'payflow:cancel:{order_id}')
    builder.adjust(1)
    return builder.as_markup()


def wallet_topup_receipt_actions_keyboard(topup_id: int, wallets: list[dict] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, wallet in enumerate(wallets or [], 1):
        if not isinstance(wallet, dict) or not wallet.get('address'):
            continue
        builder.button(text=_wallet_copy_button_text(wallet, index), callback_data=f'wallet:copy_wallet:{topup_id}:{index}')
    builder.button(text='⬅️ برگشت به روش‌های پرداخت', callback_data=f'wallet:back_payment:{topup_id}')
    builder.button(text='❌ لغو شارژ کیف پول', callback_data=f'wallet:cancel_topup:{topup_id}')
    builder.adjust(1)
    return builder.as_markup()


def wallet_payment_methods_keyboard(methods: list[str], titles: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    default_titles = {
        'card_to_card': '💳 کارت‌به‌کارت',
        'zarinpal': '🌐 زرین‌پال',
        'plisio': '🪙 پرداخت کریپتویی آنلاین',
        'crypto_manual': '🪙 پرداخت با رمز ارز',
    }
    titles = {**default_titles, **(titles or {})}
    builder = InlineKeyboardBuilder()
    for method in methods:
        if method == 'wallet':
            continue
        builder.button(text=titles.get(method, method), callback_data=f'wallet:pay:{method}')
    builder.button(text='⬅️ برگشت', callback_data='wallet:cancel')
    builder.adjust(1)
    return builder.as_markup()


def discount_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='🎟 اعمال کد تخفیف', callback_data='discount:enter')
    builder.button(text='ادامه بدون تخفیف', callback_data='discount:skip')
    builder.adjust(1)
    return builder.as_markup()


def join_channels_keyboard(channels: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for channel in channels:
        label = channel
        url = None
        if channel.startswith('https://t.me/') or channel.startswith('http://t.me/'):
            url = channel
            label = channel.rstrip('/').split('/')[-1]
        elif channel.startswith('@'):
            url = f'https://t.me/{channel[1:]}'
            label = channel
        if url:
            builder.button(text=f'عضویت در {label}', url=url)
    builder.button(text='✅ بررسی عضویت', callback_data='check_join')
    builder.adjust(1)
    return builder.as_markup()


def _tutorial_type_icon(item: object) -> str:
    meta = getattr(item, 'metadata_json', None) or {}
    content_type = meta.get('content_type') or ('video' if getattr(item, 'video_file_id', '') else 'text')
    if content_type == 'text':
        return '📝'
    if content_type in {'photo', 'photo_text'}:
        return '🖼'
    return '🎬'


def tutorials_keyboard(tutorials: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in tutorials:
        builder.button(text=f'{_tutorial_type_icon(item)} {item.title}', callback_data=f'tutorial:view:{item.id}')
    builder.adjust(1)
    return builder.as_markup()


def support_keyboard(username: str | None) -> InlineKeyboardMarkup | None:
    if not username:
        return None
    username = username.strip()
    if username.startswith('https://t.me/') or username.startswith('http://t.me/'):
        url = username
    else:
        username = username.lstrip('@')
        url = f'https://t.me/{username}'
    builder = InlineKeyboardBuilder()
    builder.button(text='ارتباط با پشتیبانی', url=url)
    return builder.as_markup()


def wallet_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ شارژ کیف پول', callback_data='wallet:topup')
    builder.adjust(1)
    return builder.as_markup()
