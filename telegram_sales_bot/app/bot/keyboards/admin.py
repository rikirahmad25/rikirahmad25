from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PRODUCT_KIND_TITLES = {
    'service': 'سرویس',
    'digital': 'دیجیتال',
    'file': 'فایل',
    'code': 'کد/لایسنس',
    'subscription': 'اشتراک',
}

DELIVERY_KIND_TITLES = {
    'manual': 'تحویل دستی / منوال',
    'auto_text': 'تحویل خودکار متن',
}

AUTO_TEXT_DELIVERY_MODE_TITLES = {
    'manual': 'نمایش دکمه تحویل برای ادمین',
    'auto': 'تحویل خودکار بعد از تایید پرداخت',
}

REQUIRED_FIELD_TITLES = {
    'email': 'ایمیل',
    'phone': 'شماره تلفن',
    'username': 'آیدی/نام کاربری',
    'note': 'توضیحات تکمیلی',
}

ROLE_TITLES = {
    'owner': 'مالک / دسترسی کامل',
    'sales_manager': 'مدیر فروش',
    'support': 'پشتیبانی',
    'accountant': 'حسابدار',
    'marketing': 'مارکتینگ',
}


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📊 داشبورد', callback_data='admin:dashboard')
    builder.button(text='📦 سفارش‌ها', callback_data='admin:orders')
    builder.button(text='🛍 محصولات', callback_data='admin:products')
    builder.button(text='👥 کاربران', callback_data='admin:users')
    builder.button(text='📣 پیام‌ها', callback_data='admin:broadcasts')
    builder.button(text='🎁 قرعه‌کشی', callback_data='admin:lottery')
    builder.button(text='👮‍♂️ ادمین‌ها', callback_data='admin:admins')
    builder.button(text='⚙️ تنظیمات', callback_data='admin:settings')
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()



def broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📣 ارسال همگانی', callback_data='admin:broadcasts:all')
    builder.button(text='👤 ارسال به یک عضو خاص', callback_data='admin:broadcasts:direct')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def manual_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ تایید پرداخت', callback_data=f'admin:approve_payment:{order_id}')
    builder.button(text='❌ رد رسید', callback_data=f'admin:reject_payment:{order_id}')
    builder.adjust(1)
    return builder.as_markup()


def order_processing_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📦 تحویل سفارش', callback_data=f'admin:complete_order:{order_id}')
    builder.button(text='📝 تحویل متن', callback_data=f'admin:deliver_text_prompt:{order_id}')
    builder.button(text='🛠 لیست منتظر پردازش', callback_data='admin:orders:list:processing:0')
    builder.adjust(1)
    return builder.as_markup()


def orders_admin_keyboard(counts: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    counts = counts or {}

    def label(title: str, key: str) -> str:
        value = counts.get(key)
        return f'{title} ({value})' if value is not None else title

    builder = InlineKeyboardBuilder()
    builder.button(text=label('🧾 منتظر تایید پرداخت', 'pending_review'), callback_data='admin:orders:list:pending_review:0')
    builder.button(text=label('🛠 منتظر پردازش', 'processing'), callback_data='admin:orders:list:processing:0')
    builder.button(text=label('✅ پردازش/تکمیل شده', 'completed'), callback_data='admin:orders:list:completed:0')
    builder.button(text=label('❌ رد شده/لغوشده', 'rejected'), callback_data='admin:orders:list:rejected:0')
    builder.button(text='🔎 جستجو با شماره یکتا سفارش', callback_data='admin:orders:search')
    builder.button(text='🧹 پاکسازی لیست سفارش‌ها', callback_data='admin:orders:cleanup')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def orders_list_keyboard(category: str, orders: list, page: int, has_next: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        product_title = getattr(getattr(order, 'product', None), 'title', 'بدون محصول') or 'بدون محصول'
        if len(product_title) > 24:
            product_title = product_title[:21] + '...'
        builder.button(text=f'جزئیات {order.order_number} | {product_title}', callback_data=f'admin:order:detail:{order.id}:{category}')
    builder.button(text='📄 خروجی فایل تکست', callback_data=f'admin:orders:export:{category}')
    if page > 0:
        builder.button(text='⬅️ صفحه قبل', callback_data=f'admin:orders:list:{category}:{page - 1}')
    if has_next:
        builder.button(text='صفحه بعد ➡️', callback_data=f'admin:orders:list:{category}:{page + 1}')
    builder.button(text='⬅️ دسته‌بندی سفارش‌ها', callback_data='admin:orders')
    builder.adjust(1)
    return builder.as_markup()


def orders_cleanup_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='پاکسازی تکمیل/ردشده قدیمی‌تر از ۱ روز', callback_data='admin:orders:cleanup:1')
    builder.button(text='پاکسازی تکمیل/ردشده قدیمی‌تر از ۷ روز', callback_data='admin:orders:cleanup:7')
    builder.button(text='پاکسازی تکمیل/ردشده قدیمی‌تر از ۳۰ روز', callback_data='admin:orders:cleanup:30')
    builder.button(text='پاکسازی همه تکمیل/ردشده‌ها', callback_data='admin:orders:cleanup:all')
    builder.button(text='⬅️ دسته‌بندی سفارش‌ها', callback_data='admin:orders')
    builder.adjust(1)
    return builder.as_markup()


def dashboard_keyboard(daily_enabled: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📄 خروجی حساب امروز', callback_data='admin:dashboard:export_today')
    builder.button(
        text='✅ ارسال روزانه حساب روشن' if daily_enabled else '❌ ارسال روزانه حساب خاموش',
        callback_data='admin:dashboard:daily_toggle',
    )
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def order_detail_keyboard(order_id: int, category: str | None = None, status: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status == 'pending_manual_review':
        builder.button(text='✅ تایید پرداخت', callback_data=f'admin:approve_payment:{order_id}')
        builder.button(text='❌ رد رسید', callback_data=f'admin:reject_payment:{order_id}')
        builder.button(text='🔁 ارسال مجدد پیام رسید به ادمین‌ها', callback_data=f'admin:resend_review:{order_id}')
    elif status in {'paid', 'processing'}:
        builder.button(text='📦 تحویل سفارش', callback_data=f'admin:complete_order:{order_id}')
        builder.button(text='📝 تحویل متن', callback_data=f'admin:deliver_text_prompt:{order_id}')
    if category:
        builder.button(text='⬅️ برگشت به همین دسته‌بندی', callback_data=f'admin:orders:list:{category}:0')
    builder.button(text='⬅️ دسته‌بندی سفارش‌ها', callback_data='admin:orders')
    builder.adjust(1)
    return builder.as_markup()


def topup_review_keyboard(topup_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ تایید شارژ', callback_data=f'admin:topup:approve:{topup_id}')
    builder.button(text='❌ رد شارژ', callback_data=f'admin:topup:reject:{topup_id}')
    builder.adjust(1)
    return builder.as_markup()


def product_categories_keyboard(categories: list[dict], counts: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    counts = counts or {}
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن محصول', callback_data='admin:product:add')
    builder.button(text='➕ افزودن محصول چند حالته', callback_data='admin:product:add_multi')
    builder.button(text='🗂 مدیریت دسته‌بندی‌ها', callback_data='admin:product:categories')
    for cat in categories:
        if not cat.get('is_active', True):
            continue
        cat_id = str(cat.get('id'))
        title = str(cat.get('title') or cat_id)
        builder.button(text=f'📁 {title} ({counts.get(cat_id, 0)})', callback_data=f'admin:products:cat:{cat_id}:0')
    if counts.get('uncategorized', 0):
        builder.button(text=f'📁 بدون دسته ({counts.get("uncategorized", 0)})', callback_data='admin:products:cat:uncategorized:0')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def product_categories_manage_keyboard(categories: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ ساخت دسته‌بندی', callback_data='admin:product:category:add')
    for cat in categories:
        prefix = '✅' if cat.get('is_active', True) else '❌'
        builder.button(text=f'{prefix} {cat.get("title")}', callback_data=f'admin:product:category:manage:{cat.get("id")}')
    builder.button(text='⬅️ محصولات', callback_data='admin:products')
    builder.adjust(1)
    return builder.as_markup()


def product_category_manage_keyboard(cat_id: str, is_active: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال/غیرفعال', callback_data=f'admin:product:category:toggle:{cat_id}')
    builder.button(text='✏️ تغییر عنوان', callback_data=f'admin:product:category:rename:{cat_id}')
    builder.button(text='🗑 حذف از لیست', callback_data=f'admin:product:category:delete:{cat_id}')
    builder.button(text='⬅️ دسته‌بندی‌ها', callback_data='admin:product:categories')
    builder.adjust(1)
    return builder.as_markup()


def category_choice_keyboard(categories: list[dict], selected_id: str | None = None, prefix: str = 'admin:product:select_category') -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat in categories:
        if not cat.get('is_active', True):
            continue
        cat_id = str(cat.get('id'))
        mark = '✅ ' if selected_id == cat_id else ''
        builder.button(text=f'{mark}{cat.get("title")}', callback_data=f'{prefix}:{cat_id}')
    builder.button(text='بدون دسته', callback_data=f'{prefix}:uncategorized')
    builder.adjust(1)
    return builder.as_markup()


def products_admin_keyboard(products: list, category_id: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن محصول', callback_data='admin:product:add')
    builder.button(text='➕ افزودن محصول چند حالته', callback_data='admin:product:add_multi')
    for product in products:
        state = '✅' if product.is_active else '⛔️'
        extra = product.extra_settings or {}
        variant_prefix = '↳ ' if extra.get('variant_parent_id') else ''
        parent_prefix = '🧩 ' if extra.get('is_variant_parent') else ''
        title = f'{variant_prefix}{parent_prefix}{state} #{product.id} {product.title}'
        if extra.get('deleted'):
            title = f'🗑 #{product.id} {product.title}'
        builder.button(text=title, callback_data=f'admin:product:manage:{product.id}')
    if category_id:
        builder.button(text='⬅️ دسته‌بندی محصولات', callback_data='admin:products')
    else:
        builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()



def product_manage_keyboard(
    product_id: int,
    is_active: bool = True,
    deleted: bool = False,
    is_auto_text: bool = False,
    is_variant_parent: bool = False,
    variant_parent_id: int | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not deleted:
        if is_variant_parent:
            builder.button(text='➕ افزودن حالت/زیرمحصول', callback_data=f'admin:product:add_variant:{product_id}')
            builder.button(text='📋 لیست حالت‌ها', callback_data=f'admin:product:variants:{product_id}')
        builder.button(text='✏️ ویرایش', callback_data=f'admin:product:edit:{product_id}')
        if not is_variant_parent:
            builder.button(text='➕ افزودن محتوای تحویل', callback_data=f'admin:product:add_delivery:{product_id}')
        if is_auto_text:
            builder.button(text='📋 محتوای فروخته‌نشده اتوتکست', callback_data=f'admin:product:unused_delivery:{product_id}')
            builder.button(text='🗑 حذف محتوای فروخته‌نشده', callback_data=f'admin:product:delete_delivery_prompt:{product_id}')
        builder.button(text='⛔️ غیرفعال کردن' if is_active else '✅ فعال کردن', callback_data=f'admin:toggle_product:{product_id}')
        builder.button(text='🗑 حذف', callback_data=f'admin:delete_product:{product_id}')
    if variant_parent_id:
        builder.button(text='⬅️ محصول مادر', callback_data=f'admin:product:manage:{variant_parent_id}')
    builder.button(text='⬅️ لیست محصولات', callback_data='admin:products')
    builder.adjust(1)
    return builder.as_markup()


def delivery_items_manage_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📋 دریافت دوباره لیست', callback_data=f'admin:product:unused_delivery:{product_id}')
    builder.button(text='🗑 حذف محتوا با شماره', callback_data=f'admin:product:delete_delivery_prompt:{product_id}')
    builder.button(text='⬅️ برگشت به محصول', callback_data=f'admin:product:manage:{product_id}')
    builder.adjust(1)
    return builder.as_markup()


def product_variants_admin_keyboard(parent_id: int, variants: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن حالت جدید', callback_data=f'admin:product:add_variant:{parent_id}')
    for product in variants:
        state = '✅' if product.is_active else '⛔️'
        builder.button(text=f'{state} #{product.id} {product.title}', callback_data=f'admin:product:manage:{product.id}')
    builder.button(text='⬅️ محصول مادر', callback_data=f'admin:product:manage:{parent_id}')
    builder.adjust(1)
    return builder.as_markup()


def price_currency_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='تومان', callback_data='admin:product:price_currency:toman')
    builder.button(text='دلار + محاسبه تومان', callback_data='admin:product:price_currency:usd')
    builder.adjust(1)
    return builder.as_markup()


def allow_quantity_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ اجازه خرید با تعداد مورد نیاز فعال باشد', callback_data='admin:product:allow_quantity:yes')
    builder.button(text='❌ فقط خرید یک عددی', callback_data='admin:product:allow_quantity:no')
    builder.adjust(1)
    return builder.as_markup()


def multi_variant_next_keyboard(parent_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن حالت بعدی', callback_data=f'admin:product:add_variant:{parent_id}')
    builder.button(text='✅ اتمام ساخت محصول چندحالته', callback_data=f'admin:product:multi_finish:{parent_id}')
    builder.button(text='📋 لیست حالت‌ها', callback_data=f'admin:product:variants:{parent_id}')
    builder.adjust(1)
    return builder.as_markup()


def product_kind_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in PRODUCT_KIND_TITLES.items():
        builder.button(text=title, callback_data=f'admin:product:kind:{key}')
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def delivery_kind_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in DELIVERY_KIND_TITLES.items():
        builder.button(text=title, callback_data=f'admin:product:delivery:{key}')
    builder.adjust(1)
    return builder.as_markup()


def auto_text_delivery_mode_keyboard(selected: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in AUTO_TEXT_DELIVERY_MODE_TITLES.items():
        prefix = '✅' if selected == key else '▫️'
        builder.button(text=f'{prefix} {title}', callback_data=f'admin:product:auto_text_mode:{key}')
    builder.adjust(1)
    return builder.as_markup()



def show_stock_choice_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ نمایش داده شود', callback_data='admin:product:show_stock:yes')
    builder.button(text='❌ نمایش داده نشود', callback_data='admin:product:show_stock:no')
    builder.adjust(1)
    return builder.as_markup()

def required_fields_keyboard(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or []
    builder = InlineKeyboardBuilder()
    for key, title in REQUIRED_FIELD_TITLES.items():
        prefix = '✅' if key in selected else '▫️'
        builder.button(text=f'{prefix} {title}', callback_data=f'admin:product:field:{key}')
    builder.button(text='✅ ثبت فیلدها', callback_data='admin:product:fields:done')
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def product_edit_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='عنوان', callback_data=f'admin:product:edit_field:{product_id}:title')
    builder.button(text='توضیحات', callback_data=f'admin:product:edit_field:{product_id}:description')
    builder.button(text='قیمت', callback_data=f'admin:product:edit_field:{product_id}:price')
    builder.button(text='موجودی', callback_data=f'admin:product:edit_field:{product_id}:stock_count')
    builder.button(text='دسته‌بندی', callback_data=f'admin:product:edit_category:{product_id}')
    builder.button(text='نوع محصول', callback_data=f'admin:product:edit_kind:{product_id}')
    builder.button(text='شیوه تحویل', callback_data=f'admin:product:edit_delivery:{product_id}')
    builder.button(text='حالت تحویل اتوتکست', callback_data=f'admin:product:edit_auto_mode:{product_id}')
    builder.button(text='اطلاعات لازم مشتری', callback_data=f'admin:product:edit_fields:{product_id}')
    builder.button(text='متن درخواست ایمیل', callback_data=f'admin:product:edit_prompt:{product_id}:email')
    builder.button(text='متن درخواست شماره', callback_data=f'admin:product:edit_prompt:{product_id}:phone')
    builder.button(text='موجودی متن تحویل خودکار', callback_data=f'admin:product:add_delivery:{product_id}')
    builder.button(text='نمایش موجودی برای مشتری', callback_data=f'admin:product:edit_show_stock:{product_id}')
    builder.button(text='خرید تعدادی روشن/خاموش', callback_data=f'admin:product:edit_allow_quantity:{product_id}')
    builder.button(text='تنظیم قیمت دلاری', callback_data=f'admin:product:edit_dollar_price:{product_id}')
    builder.button(text='⬅️ برگشت', callback_data=f'admin:product:manage:{product_id}')
    builder.adjust(2, 2, 1, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()


def settings_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='💳 پرداخت‌ها', callback_data='admin:set:payments')
    builder.button(text='🏦 کارت‌به‌کارت', callback_data='admin:set:card')
    builder.button(text='🌐 زرین‌پال', callback_data='admin:set:zarinpal')
    builder.button(text='🪙 Plisio', callback_data='admin:set:plisio')
    builder.button(text='🪙 پرداخت رمزارز دستی', callback_data='admin:set:crypto_manual')
    builder.button(text='🎟 کد تخفیف', callback_data='admin:set:discounts')
    builder.button(text='📢 عضویت اجباری', callback_data='admin:set:channels')
    builder.button(text='📱 شماره تلفن اجباری', callback_data='admin:set:phone')
    builder.button(text='☎️ پشتیبانی', callback_data='admin:set:support')
    builder.button(text='🎬 آموزش‌ها', callback_data='admin:set:tutorials')
    builder.button(text='🔔 اعلان‌ها', callback_data='admin:set:notifications')
    builder.button(text='💾 بکاپ و ریستور', callback_data='admin:set:backup')
    builder.button(text='📝 متن‌ها', callback_data='admin:set:texts')
    builder.button(text='🔘 دکمه‌های منو', callback_data='admin:set:menu')
    builder.button(text='🛡 ضداسپم', callback_data='admin:set:anti_spam')
    builder.button(text='👥 زیرمجموعه‌گیری', callback_data='admin:set:referral')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(2, 2, 2, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def payment_settings_keyboard(enabled: list[str]) -> InlineKeyboardMarkup:
    titles = {
        'card_to_card': 'کارت‌به‌کارت',
        'zarinpal': 'زرین‌پال',
        'plisio': 'Plisio',
        'crypto_manual': 'پرداخت رمزارز دستی',
        'wallet': 'کیف پول',
    }
    builder = InlineKeyboardBuilder()
    for method, title in titles.items():
        prefix = '✅' if method in enabled else '❌'
        builder.button(text=f'{prefix} {title}', callback_data=f'admin:set:payments:toggle:{method}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def card_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in [('card_number', 'شماره کارت'), ('card_holder', 'نام صاحب کارت'), ('bank', 'نام بانک'), ('box_text', 'متن باکس پرداخت')]:
        builder.button(text=title, callback_data=f'admin:set:card:edit:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def zarinpal_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='مرچنت آی‌دی', callback_data='admin:set:zarinpal:edit:merchant_id')
    builder.button(text='Callback URL', callback_data='admin:set:zarinpal:edit:callback_url')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def plisio_settings_keyboard(cfg: dict | None = None) -> InlineKeyboardMarkup:
    cfg = cfg or {}
    builder = InlineKeyboardBuilder()
    for key, title in [
        ('api_key', 'Secret/API Key'),
        ('source_currency', 'ارز مبدا فیات'),
        ('source_rate', 'نرخ دستی تومان به USD'),
        ('display_label', 'عنوان دکمه روش پرداخت'),
        ('currency', 'ارز کریپتویی پیش‌فرض'),
        ('allowed_psys_cids', 'ارزهای مجاز'),
        ('callback_url', 'Callback URL'),
        ('expire_min', 'انقضای فاکتور دقیقه'),
    ]:
        builder.button(text=title, callback_data=f'admin:set:plisio:edit:{key}')
    auto_status = '✅ نرخ خودکار USDT نوبیتکس' if cfg.get('auto_usdt_rate_enabled', False) else '❌ نرخ خودکار USDT نوبیتکس'
    fallback_status = '✅ نرخ دستی هنگام خطای نوبیتکس' if cfg.get('fallback_to_manual_rate_enabled', False) else '❌ نرخ دستی هنگام خطای نوبیتکس'
    show_status = '✅ نمایش نرخ به مشتری' if cfg.get('show_source_rate', False) else '❌ نمایش نرخ به مشتری'
    builder.button(text=auto_status, callback_data='admin:set:plisio:toggle_auto_usdt_rate')
    builder.button(text=fallback_status, callback_data='admin:set:plisio:toggle_fallback_manual_rate')
    builder.button(text=show_status, callback_data='admin:set:plisio:toggle_show_source_rate')
    builder.button(text='تایید امضای Callback روشن/خاموش', callback_data='admin:set:plisio:toggle_verify')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def crypto_manual_settings_keyboard(wallets: list[dict] | None = None, cfg: dict | None = None) -> InlineKeyboardMarkup:
    wallets = wallets or []
    cfg = cfg or {}
    builder = InlineKeyboardBuilder()
    unit_status = '✅ نمایش قیمت واحد به مشتری' if cfg.get('show_unit_price', False) else '❌ نمایش قیمت واحد به مشتری'
    builder.button(text=unit_status, callback_data='admin:set:crypto_manual:toggle_show_unit_price')
    builder.button(text='📝 عنوان دکمه روش پرداخت', callback_data='admin:set:crypto_manual:edit:display_label')
    builder.button(text='➕ افزودن آدرس ولت', callback_data='admin:set:crypto_manual:add')
    builder.button(text='📝 ویرایش متن راهنما', callback_data='admin:set:crypto_manual:edit:instructions')
    for wallet in wallets:
        wallet_id = wallet.get('id')
        if wallet_id is None:
            continue
        coin = str(wallet.get('coin_symbol') or wallet.get('coin') or 'ارز')
        network = str(wallet.get('network') or 'شبکه')
        status = '✅' if wallet.get('is_active', True) else '❌'
        builder.button(text=f'{status} {coin} / {network} روشن‌خاموش', callback_data=f'admin:set:crypto_manual:toggle:{wallet_id}')
        builder.button(text=f'🗑 حذف {coin} / {network}', callback_data=f'admin:set:crypto_manual:delete:{wallet_id}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def channels_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال' if enabled else '❌ غیرفعال', callback_data='admin:set:channels:toggle')
    builder.button(text='ویرایش کانال‌ها/گروه‌ها', callback_data='admin:set:channels:edit')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def phone_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال' if enabled else '❌ غیرفعال', callback_data='admin:set:phone:toggle')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def support_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='ویرایش آیدی پشتیبانی', callback_data='admin:set:support:edit:support_username')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
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


def tutorials_admin_keyboard(tutorials: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن آموزش', callback_data='admin:tutorial:add')
    for item in tutorials:
        prefix = '✅' if item.is_active else '❌'
        icon = _tutorial_type_icon(item)
        builder.button(text=f'{prefix} {icon} #{item.id} {item.title}', callback_data=f'admin:tutorial:manage:{item.id}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def tutorial_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📝 آموزش متنی', callback_data='admin:tutorial:type:text')
    builder.button(text='🖼 آموزش عکسی', callback_data='admin:tutorial:type:photo')
    builder.button(text='🖼📝 عکس با کپشن', callback_data='admin:tutorial:type:photo_text')
    builder.button(text='🎬 آموزش ویدیویی', callback_data='admin:tutorial:type:video')
    builder.button(text='⬅️ آموزش‌ها', callback_data='admin:set:tutorials')
    builder.adjust(1)
    return builder.as_markup()


def tutorial_manage_keyboard(tutorial_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال/غیرفعال', callback_data=f'admin:tutorial:toggle:{tutorial_id}')
    builder.button(text='🗑 حذف', callback_data=f'admin:tutorial:delete:{tutorial_id}')
    builder.button(text='⬅️ آموزش‌ها', callback_data='admin:set:tutorials')
    builder.adjust(1)
    return builder.as_markup()


def backup_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال' if enabled else '❌ غیرفعال', callback_data='admin:set:backup:toggle')
    builder.button(text='ویرایش بازه ارسال ساعتی', callback_data='admin:set:backup:edit:interval_hours')
    builder.button(text='ارسال بکاپ الان', callback_data='admin:set:backup:send_now')
    builder.button(text='ریستور از فایل', callback_data='admin:set:backup:restore')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def discounts_settings_keyboard(enabled: bool, apply_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ سیستم فعال' if enabled else '❌ سیستم غیرفعال', callback_data='admin:set:discounts:toggle')
    builder.button(text='✅ گزینه اعمال کد' if apply_enabled else '❌ گزینه اعمال کد', callback_data='admin:set:discounts:toggle_apply')
    builder.button(text='➕ ساخت کد', callback_data='admin:discount:create')
    builder.button(text='📋 لیست کدها', callback_data='admin:discount:list')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def discount_code_keyboard(code_id: int, is_active: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال/غیرفعال', callback_data=f'admin:discount:toggle:{code_id}')
    builder.button(text='🗑 حذف', callback_data=f'admin:discount:delete:{code_id}')
    builder.adjust(1)
    return builder.as_markup()


def discount_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='درصدی', callback_data='admin:discount:type:percent')
    builder.button(text='مبلغ ثابت', callback_data='admin:discount:type:fixed')
    builder.button(text='⬅️ برگشت', callback_data='admin:set:discounts')
    builder.adjust(2, 1)
    return builder.as_markup()


def discount_max_uses_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for title, value in [('نامحدود', 'unlimited'), ('۱ بار', '1'), ('۵ بار', '5'), ('۱۰ بار', '10'), ('۵۰ بار', '50'), ('۱۰۰ بار', '100')]:
        builder.button(text=title, callback_data=f'admin:discount:max:{value}')
    builder.adjust(2, 2, 2)
    return builder.as_markup()


def discount_per_user_limit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for title, value in [('۱ بار برای هر کاربر', '1'), ('۲ بار', '2'), ('۳ بار', '3'), ('نامحدود برای هر کاربر', '0')]:
        builder.button(text=title, callback_data=f'admin:discount:userlimit:{value}')
    builder.adjust(1)
    return builder.as_markup()


def discount_min_amount_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for title, value in [('بدون حداقل', '0'), ('۱۰۰ هزار', '100000'), ('۵۰۰ هزار', '500000'), ('۱ میلیون', '1000000')]:
        builder.button(text=title, callback_data=f'admin:discount:min:{value}')
    builder.adjust(2, 2)
    return builder.as_markup()


def texts_settings_keyboard(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in items:
        builder.button(text=title, callback_data=f'admin:set:texts:edit:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def menu_settings_keyboard(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, title in items:
        builder.button(text=title, callback_data=f'admin:set:menu:edit:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def anti_spam_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال' if enabled else '❌ غیرفعال', callback_data='admin:set:anti_spam:toggle')
    for key, title in [('max_messages', 'تعداد پیام مجاز'), ('window_seconds', 'بازه زمانی'), ('block_seconds', 'مدت بلاک'), ('warn_text', 'متن هشدار')]:
        builder.button(text=title, callback_data=f'admin:set:anti_spam:edit:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def referral_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال' if enabled else '❌ غیرفعال', callback_data='admin:set:referral:toggle')
    for key, title in [
        ('reward_type', 'نوع پاداش percent/fixed'),
        ('percent', 'درصد سود'),
        ('fixed_amount', 'مبلغ ثابت'),
        ('basis', 'مبنا paid_amount/original_amount'),
        ('min_order_amount', 'حداقل سفارش'),
        ('max_commission', 'سقف سود'),
        ('message_text', 'متن زیرمجموعه‌گیری'),
    ]:
        builder.button(text=title, callback_data=f'admin:set:referral:edit:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def notification_settings_keyboard(cfg: dict) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items = [
        ('new_user_enabled', 'اعلان ورود کاربر جدید'),
        ('user_blocked_bot_enabled', 'اعلان بلاک/حذف ربات'),
        ('referral_commission_enabled', 'اعلان پورسانت زیرمجموعه'),
    ]
    for key, title in items:
        prefix = '✅' if cfg.get(key, True) else '❌'
        builder.button(text=f'{prefix} {title}', callback_data=f'admin:set:notifications:toggle:{key}')
    builder.button(text='⬅️ برگشت', callback_data='admin:settings')
    builder.adjust(1)
    return builder.as_markup()


def admins_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='➕ افزودن ادمین', callback_data='admin:admins:add')
    builder.button(text='📋 لیست ادمین‌ها', callback_data='admin:admins:list')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def role_select_keyboard(admin_user_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    base = f'admin:admins:role:{admin_user_id}' if admin_user_id else 'admin:admins:add_role'
    for slug, title in ROLE_TITLES.items():
        builder.button(text=title, callback_data=f'{base}:{slug}')
    builder.button(text='⬅️ ادمین‌ها', callback_data='admin:admins')
    builder.adjust(1)
    return builder.as_markup()


def admin_item_keyboard(admin_id: int, is_active: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ فعال/غیرفعال', callback_data=f'admin:admins:toggle:{admin_id}')
    builder.button(text='🔐 تغییر سطح دسترسی', callback_data=f'admin:admins:change_role:{admin_id}')
    builder.button(text='⬅️ لیست ادمین‌ها', callback_data='admin:admins:list')
    builder.adjust(1)
    return builder.as_markup()


def users_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='📄 خروجی لیست کاربران', callback_data='admin:users:export')
    builder.button(text='🚫 مسدود کردن کاربر', callback_data='admin:users:block')
    builder.button(text='✅ رفع مسدودی کاربر', callback_data='admin:users:unblock')
    builder.button(text='💰 شارژ دستی کیف پول', callback_data='admin:users:wallet_charge')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()


def lottery_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text='✅ قرعه‌کشی فعال' if enabled else '❌ قرعه‌کشی غیرفعال', callback_data='admin:lottery:toggle')
    builder.button(text='🎲 انتخاب برنده و هدیه', callback_data='admin:lottery:draw')
    builder.button(text='⬅️ برگشت', callback_data='admin:back:main')
    builder.adjust(1)
    return builder.as_markup()
