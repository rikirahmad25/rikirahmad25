from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot.filters import MenuTextFilter
from app.bot.keyboards.user import product_categories_keyboard, product_keyboard, product_variants_keyboard, products_keyboard
from app.db.models import Order
from app.db.session import SessionLocal
from app.services.product_service import (
    ProductService,
    allow_quantity_purchase,
    category_layout,
    is_variant_parent,
    product_price_display,
    show_stock_to_customer,
    variant_parent_id,
)
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.text import money

router = Router(name='catalog')


async def _show_categories(message_or_callback) -> None:
    async with SessionLocal() as session:
        settings_service = SettingsService(session)
        texts = await settings_service.get('texts')
        service = ProductService(session)
        products = await service.list_active()
        categories = await service.list_categories()
        counts = await service.category_counts(customer_visible=True)
        cats_layout = await service.get_categories_layout()
        uncat_layout = await service.get_uncategorized_layout()
    if not products:
        await message_or_callback.answer(texts.get('no_products', 'فعلاً محصول فعالی نداریم.'))
        return
    # The main Products button should always reset the customer to the first
    # catalog page (category list), instead of keeping them inside the last
    # category. If no category exists at all, show products directly.
    if not categories and not counts.get('uncategorized'):
        await message_or_callback.answer(
            texts.get('products_title', 'محصولات فعال:'),
            reply_markup=products_keyboard(products, layout=uncat_layout),
        )
        return
    await message_or_callback.answer(
        '🗂 دسته‌بندی محصولات را انتخاب کن:',
        reply_markup=product_categories_keyboard(categories, counts, layout=cats_layout),
    )


@router.message(MenuTextFilter('products', '🛍 محصولات'))
async def products_menu(message: Message) -> None:
    await _show_categories(message)


@router.callback_query(F.data == 'catalog:categories')
async def catalog_categories(callback: CallbackQuery) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        service = ProductService(session)
        categories = await service.list_categories()
        counts = await service.category_counts(customer_visible=True)
        cats_layout = await service.get_categories_layout()
    await callback.message.edit_text(
        '🗂 دسته‌بندی محصولات را انتخاب کن:',
        reply_markup=product_categories_keyboard(categories, counts, layout=cats_layout),
    )


@router.callback_query(F.data.startswith('catalog:cat:'))
async def category_products(callback: CallbackQuery) -> None:
    await callback.answer()
    category_id = callback.data.split(':', 2)[2]
    async with SessionLocal() as session:
        texts = await SettingsService(session).get('texts')
        service = ProductService(session)
        products = await service.list_active(category_id=category_id)
        if category_id == 'uncategorized':
            category = {'title': 'بدون دسته'}
            layout = await service.get_uncategorized_layout()
        else:
            category = await service.get_category(category_id)
            layout = category_layout(category)
    title = category.get('title') if category else 'محصولات'
    if not products:
        await callback.message.edit_text(
            f'در دسته‌بندی «{title}» محصول فعالی وجود ندارد.',
            reply_markup=products_keyboard([], layout=layout),
        )
        return
    await callback.message.edit_text(
        f'{texts.get("products_title", "محصولات فعال:")}\nدسته‌بندی: {title}',
        reply_markup=products_keyboard(products, layout=layout),
    )


@router.callback_query(F.data.in_({'back:products', 'catalog:back'}))
async def back_products(callback: CallbackQuery) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        service = ProductService(session)
        categories = await service.list_categories()
        counts = await service.category_counts(customer_visible=True)
        cats_layout = await service.get_categories_layout()
    await callback.message.edit_text(
        '🗂 دسته‌بندی محصولات را انتخاب کن:',
        reply_markup=product_categories_keyboard(categories, counts, layout=cats_layout),
    )


@router.callback_query(F.data.startswith('product:'))
async def product_details(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[1])
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        variants = await service.list_variants(product_id) if product and is_variant_parent(product) else []
        parent_id = variant_parent_id(product) if product else None
        parent = await service.get(parent_id) if parent_id else None
    if not product or not product.is_active or (product.extra_settings or {}).get('deleted'):
        await callback.message.answer('این محصول در دسترس نیست.')
        return

    if is_variant_parent(product):
        if not variants:
            await callback.message.answer('فعلاً هیچ حالت فعالی برای این محصول ثبت نشده است.')
            return
        lines = [
            f'🛍 {product.title}',
            '',
            product.description or 'بدون توضیح',
            '',
            'حالت‌های قابل خرید:',
        ]
        for item in variants:
            desc = (item.description or '').strip()
            short_desc = f' — {desc[:80]}' if desc else ''
            lines.append(f'• {item.title}: {product_price_display(item)}{short_desc}')
        lines.append('')
        lines.append('برای دیدن توضیحات کامل و خرید، یکی از حالت‌ها را انتخاب کن.')
        await callback.message.edit_text('\n'.join(lines), reply_markup=product_variants_keyboard(product.id, variants))
        return

    fields = product.required_fields or []
    fields_text = '، '.join(field.get('label', field.get('name', 'field')) for field in fields) if fields else 'ندارد'
    lines = [
        f'🛍 {product.title}',
    ]
    if parent:
        lines.append(f'مربوط به: {parent.title}')
    lines.extend([
        '',
        product.description or 'بدون توضیح',
        '',
        f'💵 قیمت: {product_price_display(product)}',
        f'📥 اطلاعات موردنیاز: {fields_text}',
    ])
    if allow_quantity_purchase(product):
        lines.append('🔢 امکان خرید با تعداد دلخواه: فعال')
    if show_stock_to_customer(product):
        stock_text = 'نامحدود' if product.stock_count is None else str(product.stock_count)
        lines.append(f'📊 موجودی: {stock_text}')
    text = '\n'.join(lines)
    back_callback = f'product:{parent.id}' if parent else 'catalog:back'
    await callback.message.edit_text(text, reply_markup=product_keyboard(product.id, back_callback=back_callback))


@router.message(MenuTextFilter('orders', '📦 سفارش‌های من'))
async def my_orders(message: Message) -> None:
    async with SessionLocal() as session:
        user_service = UserService(session)
        db_user = await user_service.get_by_telegram_id(message.from_user.id)
        if not db_user:
            await message.answer('ابتدا /start را بزن.')
            return
        result = await session.execute(select(Order).where(Order.user_id == db_user.id).order_by(Order.id.desc()).limit(10))
        orders = result.scalars().all()
    if not orders:
        await message.answer('هنوز سفارشی نداری.')
        return
    lines = ['آخرین سفارش‌های شما:']
    for order in orders:
        lines.append(f'• {order.order_number} | {money(order.amount)} | {order.status}')
    await message.answer('\n'.join(lines))
