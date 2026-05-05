from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.keyboards.admin import (
    DELIVERY_KIND_TITLES,
    PRODUCT_KIND_TITLES,
    REQUIRED_FIELD_TITLES,
    auto_text_delivery_mode_keyboard,
    allow_quantity_choice_keyboard,
    delivery_items_manage_keyboard,
    category_choice_keyboard,
    delivery_kind_keyboard,
    layout_choice_keyboard,
    multi_variant_next_keyboard,
    price_currency_keyboard,
    product_categories_keyboard,
    product_categories_manage_keyboard,
    product_category_manage_keyboard,
    product_edit_keyboard,
    product_kind_keyboard,
    product_manage_keyboard,
    product_variants_admin_keyboard,
    products_admin_keyboard,
    required_fields_keyboard,
    show_stock_choice_keyboard,
)
from app.bot.states.admin import AdminProductStates
from app.core.permissions import MANAGE_PRODUCTS
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.product_service import (
    AUTO_DELIVERY_KINDS,
    ProductService,
    allow_quantity_purchase,
    auto_text_delivery_mode,
    auto_text_delivery_mode_title,
    category_layout,
    is_variant_parent,
    normalize_layout,
    product_price_display,
    show_stock_to_customer,
    variant_parent_id,
)
from app.utils.text import money

router = Router(name='admin_products')


async def _has_access(telegram_id: int) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, MANAGE_PRODUCTS)


def _file_id_from_message(message: Message) -> str | None:
    if message.document:
        return message.document.file_id
    if message.video:
        return message.video.file_id
    if message.photo:
        return message.photo[-1].file_id
    return None


def _split_delivery_payload(text: str | None) -> list[str]:
    raw = (text or '').strip()
    if not raw or raw == '-':
        return []
    if '|||' in raw:
        return [part.strip() for part in raw.split('|||') if part.strip()]
    if re.search(r'(?m)^---+$', raw):
        return [part.strip() for part in re.split(r'(?m)^---+$', raw) if part.strip()]
    if re.search(r'(?m)^###+$', raw):
        return [part.strip() for part in re.split(r'(?m)^###+$', raw) if part.strip()]
    return [raw]


def _category_title(categories: list[dict], category_id: str | None) -> str:
    if not category_id or category_id == 'uncategorized':
        return 'بدون دسته'
    for item in categories:
        if str(item.get('id')) == str(category_id):
            return str(item.get('title') or category_id)
    return category_id


def _field_prompts_from_required(required_fields: list[dict] | None) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for field in required_fields or []:
        key = str(field.get('name') or field.get('type') or '').strip()
        prompt = str(field.get('prompt') or '').strip()
        if key and prompt:
            prompts[key] = prompt
    return prompts


def _prompt_field_keys(selected: list[str]) -> list[str]:
    # The user specifically asked for per-product email text. Phone is included
    # because it is another common product-level field and uses the same flow.
    return [key for key in selected if key in {'email', 'phone'}]


def _field_prompt_question(field_key: str) -> str:
    title = REQUIRED_FIELD_TITLES.get(field_key, field_key)
    return f'متن درخواست {title} برای همین محصول را بفرست. برای استفاده از متن عمومی، فقط - بفرست:'


def _product_summary(product, category_title: str = '—', unused_count: int | None = None, variants: list | None = None) -> str:
    fields = ', '.join(REQUIRED_FIELD_TITLES.get(f.get('name'), f.get('name')) for f in (product.required_fields or [])) or 'ندارد'
    prompts = _field_prompts_from_required(product.required_fields)
    prompt_lines = []
    if prompts.get('email'):
        prompt_lines.append(f'متن درخواست ایمیل: {prompts["email"]}')
    if prompts.get('phone'):
        prompt_lines.append(f'متن درخواست شماره: {prompts["phone"]}')
    prompt_text = ('\n' + '\n'.join(prompt_lines)) if prompt_lines else ''
    stock = 'نامحدود' if product.stock_count is None else str(product.stock_count)
    show_stock = 'بله' if show_stock_to_customer(product) else 'خیر'
    allow_qty = 'بله' if allow_quantity_purchase(product) else 'خیر'
    deleted = ' | حذف‌شده' if (product.extra_settings or {}).get('deleted') else ''
    unused = f'\nموجودی تحویل خودکار: {unused_count}' if unused_count is not None else ''
    auto_mode = ''
    if product.delivery_kind in AUTO_DELIVERY_KINDS:
        auto_mode = f'\nحالت اتوتکست: {auto_text_delivery_mode_title(product)}'
    parent_note = ''
    parent_id = variant_parent_id(product)
    if is_variant_parent(product):
        parent_note = '\nنوع ساختار: محصول چندحالته / مادر'
    elif parent_id:
        parent_note = f'\nنوع ساختار: حالت/زیرمحصول از محصول مادر #{parent_id}'
    price_text = 'وابسته به حالت‌ها' if is_variant_parent(product) else product_price_display(product)
    variant_text = ''
    if variants is not None:
        if variants:
            lines = ['\nحالت‌های ثبت‌شده:']
            for item in variants:
                state = 'فعال' if item.is_active else 'غیرفعال'
                lines.append(f'• #{item.id} {item.title} | {product_price_display(item)} | {DELIVERY_KIND_TITLES.get(item.delivery_kind, item.delivery_kind)} | {state}')
            variant_text = '\n'.join(lines)
        else:
            variant_text = '\nحالت‌های ثبت‌شده: ندارد'
    return (
        f'🛍 محصول #{product.id}{deleted}\n\n'
        f'عنوان: {product.title}\n'
        f'دسته‌بندی: {category_title}\n'
        f'وضعیت: {"فعال" if product.is_active else "غیرفعال"}\n'
        f'قیمت: {price_text}\n'
        f'نوع: {PRODUCT_KIND_TITLES.get(product.kind, product.kind)}\n'
        f'تحویل: {DELIVERY_KIND_TITLES.get(product.delivery_kind, product.delivery_kind)}{auto_mode}\n'
        f'اطلاعات لازم: {fields}{prompt_text}\n'
        f'موجودی: {stock}{unused}\n'
        f'نمایش موجودی برای مشتری: {show_stock}\n'
        f'خرید با تعداد مورد نیاز: {allow_qty}{parent_note}{variant_text}\n\n'
        f'{product.description or "بدون توضیح"}'
    )


async def _show_products_home(callback: CallbackQuery) -> None:
    async with SessionLocal() as session:
        service = ProductService(session)
        categories = await service.list_categories(include_inactive=True)
        counts = await service.category_counts()
    await callback.message.answer('🛍 مدیریت محصولات\n\nابتدا دسته‌بندی را انتخاب کن یا محصول جدید بساز:', reply_markup=product_categories_keyboard(categories, counts))


@router.callback_query(F.data == 'admin:products')
async def admin_products(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await _show_products_home(callback)


@router.callback_query(F.data.startswith('admin:products:cat:'))
async def admin_products_category(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    category_id = parts[3]
    async with SessionLocal() as session:
        service = ProductService(session)
        products = await service.list_all(category_id=category_id)
        categories = await service.list_categories(include_inactive=True)
    await callback.message.answer(
        f'📁 محصولات دسته‌بندی: {_category_title(categories, category_id)}',
        reply_markup=products_admin_keyboard(products, category_id=category_id),
    )


@router.callback_query(F.data == 'admin:product:categories')
async def product_categories(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        service = ProductService(session)
        categories = await service.list_categories(include_inactive=True)
        cats_layout = await service.get_categories_layout()
        uncat_layout = await service.get_uncategorized_layout()
    await callback.message.answer(
        '🗂 مدیریت دسته‌بندی محصولات:',
        reply_markup=product_categories_manage_keyboard(
            categories,
            categories_layout=cats_layout,
            uncategorized_layout=uncat_layout,
        ),
    )


@router.callback_query(F.data == 'admin:product:category:add')
async def add_category_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.set_state(AdminProductStates.waiting_category_title)
    await state.update_data(category_mode='add')
    await callback.message.answer('عنوان دسته‌بندی جدید را بفرست:')


@router.callback_query(F.data.startswith('admin:product:category:manage:'))
async def manage_category(callback: CallbackQuery) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        service = ProductService(session)
        category = await service.get_category(category_id)
    if not category:
        await callback.message.answer('دسته‌بندی پیدا نشد.')
        return
    layout = category_layout(category)
    layout_text = 'دو ستونه' if layout == 'double' else 'تک ستونه'
    await callback.message.answer(
        (
            f'📁 دسته‌بندی: {category.get("title")}\n'
            f'وضعیت: {"فعال" if category.get("is_active", True) else "غیرفعال"}\n'
            f'نمایش محصولات این دسته: {layout_text}'
        ),
        reply_markup=product_category_manage_keyboard(
            category_id,
            bool(category.get('is_active', True)),
            layout=layout,
        ),
    )


@router.callback_query(F.data == 'admin:product:categories_layout')
async def categories_layout_prompt(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        current = await ProductService(session).get_categories_layout()
    await callback.message.answer(
        'نمایش لیست خودِ دسته‌بندی‌ها در منوی کاربر را انتخاب کن:',
        reply_markup=layout_choice_keyboard('admin:product:categories_layout:set', current=current),
    )


@router.callback_query(F.data.startswith('admin:product:categories_layout:set:'))
async def categories_layout_set(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    value = normalize_layout(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        await ProductService(session).set_categories_layout(value)
        await AdminService(session).log(
            callback.from_user.id,
            'set_categories_layout',
            'product_categories',
            value,
        )
    label = 'دو ستونه' if value == 'double' else 'تک ستونه'
    await callback.message.answer(f'نمایش لیست دسته‌بندی‌ها: {label} ✅')


@router.callback_query(F.data == 'admin:product:category:uncategorized_layout')
async def uncategorized_layout_prompt(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        current = await ProductService(session).get_uncategorized_layout()
    await callback.message.answer(
        'نمایش محصولات داخل بخش «بدون دسته» را انتخاب کن:',
        reply_markup=layout_choice_keyboard('admin:product:category:uncategorized_layout:set', current=current),
    )


@router.callback_query(F.data.startswith('admin:product:category:uncategorized_layout:set:'))
async def uncategorized_layout_set(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    value = normalize_layout(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        await ProductService(session).set_uncategorized_layout(value)
        await AdminService(session).log(
            callback.from_user.id,
            'set_uncategorized_layout',
            'product_categories',
            value,
        )
    label = 'دو ستونه' if value == 'double' else 'تک ستونه'
    await callback.message.answer(f'نمایش محصولات بدون دسته: {label} ✅')


@router.callback_query(F.data.startswith('admin:product:category:layout:set:'))
async def category_layout_set(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    parts = callback.data.split(':')
    # admin:product:category:layout:set:<cat_id>:<value>
    if len(parts) < 7:
        return
    category_id = parts[-2]
    value = normalize_layout(parts[-1])
    async with SessionLocal() as session:
        await ProductService(session).update_category(category_id, layout=value)
        await AdminService(session).log(
            callback.from_user.id,
            'set_category_layout',
            'product_category',
            f'{category_id}:{value}',
        )
    label = 'دو ستونه' if value == 'double' else 'تک ستونه'
    await callback.message.answer(f'نمایش محصولات این دسته: {label} ✅')


@router.callback_query(F.data.startswith('admin:product:category:layout:'))
async def category_layout_prompt(callback: CallbackQuery) -> None:
    # هندلر «set» قبلاً ثبت شده، بنابراین callbackهایی که با :set: ادامه دارند
    # هرگز به اینجا نمی‌رسند و نیاز به فیلتر اضافه نیست.
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    parts = callback.data.split(':')
    # admin:product:category:layout:<cat_id>  → ۵ بخش
    if len(parts) != 5:
        return
    category_id = parts[-1]
    async with SessionLocal() as session:
        category = await ProductService(session).get_category(category_id)
    if not category:
        await callback.message.answer('دسته‌بندی پیدا نشد.')
        return
    await callback.message.answer(
        f'نمایش محصولات داخل دسته‌بندی «{category.get("title")}» را انتخاب کن:',
        reply_markup=layout_choice_keyboard(
            f'admin:product:category:layout:set:{category_id}',
            current=category_layout(category),
        ),
    )


@router.callback_query(F.data.startswith('admin:product:category:toggle:'))
async def toggle_category(callback: CallbackQuery) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        await ProductService(session).update_category(category_id, toggle=True)
        await AdminService(session).log(callback.from_user.id, 'toggle_product_category', 'product_category', category_id)
    await callback.message.answer('وضعیت دسته‌بندی تغییر کرد ✅')


@router.callback_query(F.data.startswith('admin:product:category:delete:'))
async def delete_category(callback: CallbackQuery) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        await ProductService(session).update_category(category_id, delete=True)
        await AdminService(session).log(callback.from_user.id, 'delete_product_category', 'product_category', category_id)
    await callback.message.answer('دسته‌بندی از لیست فعال حذف شد ✅ محصولاتش حذف نمی‌شوند و به صورت داخلی باقی می‌مانند.')


@router.callback_query(F.data.startswith('admin:product:category:rename:'))
async def rename_category_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    await state.set_state(AdminProductStates.waiting_category_title)
    await state.update_data(category_mode='rename', category_id=category_id)
    await callback.message.answer('عنوان جدید دسته‌بندی را بفرست:')


@router.message(AdminProductStates.waiting_category_title)
async def save_category_title(message: Message, state: FSMContext) -> None:
    title = (message.text or '').strip()
    if not title:
        await message.answer('عنوان معتبر نیست.')
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        service = ProductService(session)
        if data.get('category_mode') == 'rename':
            category = await service.update_category(str(data.get('category_id')), title=title)
            action = 'rename_product_category'
        else:
            category = await service.create_category(title)
            action = 'create_product_category'
        await AdminService(session).log(message.from_user.id, action, 'product_category', str(category.get('id') if category else ''))
    await state.clear()
    await message.answer('دسته‌بندی ذخیره شد ✅')


@router.callback_query(F.data.startswith('admin:product:manage:'))
async def manage_product(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        categories = await service.list_categories(include_inactive=True)
        unused_count = await service.unused_delivery_count(product.id) if product and product.delivery_kind in AUTO_DELIVERY_KINDS else None
        variants = await service.list_variants(product.id, include_inactive=True) if product and is_variant_parent(product) else None
    if not product:
        await callback.message.answer('محصول پیدا نشد.')
        return
    cat_title = _category_title(categories, ProductService.product_category_id(product))
    await callback.message.answer(
        _product_summary(product, cat_title, unused_count, variants=variants),
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            (product.extra_settings or {}).get('deleted', False),
            product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )




@router.callback_query(F.data.startswith('admin:product:add_variant:'))
async def add_variant_to_parent(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    parent_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        parent = await service.get(parent_id)
    if not parent or not is_variant_parent(parent):
        await callback.message.answer('محصول مادر چندحالته پیدا نشد.')
        return
    await state.clear()
    await state.set_state(AdminProductStates.waiting_title)
    await state.update_data(mode='add_variant', parent_id=parent.id, category_id=ProductService.product_category_id(parent))
    await callback.message.answer(
        f'افزودن حالت جدید برای «{parent.title}»\n\n'
        'عنوان حالت/زیرمحصول را بفرست. مثال: «یک ماهه آماده» یا «شش ماهه روی ایمیل شخصی»'
    )


@router.callback_query(F.data.startswith('admin:product:variants:'))
async def product_variants_list(callback: CallbackQuery) -> None:
    await callback.answer()
    parent_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        parent = await service.get(parent_id)
        variants = await service.list_variants(parent_id, include_inactive=True)
    if not parent or not is_variant_parent(parent):
        await callback.message.answer('محصول مادر پیدا نشد.')
        return
    lines = [f'🧩 حالت‌های محصول: {parent.title}', '']
    if not variants:
        lines.append('هنوز حالتی ثبت نشده است.')
    else:
        for item in variants:
            state_text = 'فعال' if item.is_active else 'غیرفعال'
            qty_text = 'خرید تعدادی: فعال' if allow_quantity_purchase(item) else 'خرید تعدادی: غیرفعال'
            lines.append(f'• #{item.id} {item.title} | {product_price_display(item)} | {state_text} | {qty_text}')
    await callback.message.answer('\n'.join(lines), reply_markup=product_variants_admin_keyboard(parent.id, variants))


@router.callback_query(F.data.startswith('admin:product:multi_finish:'))
async def product_multi_finish(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parent_id = int(callback.data.split(':')[-1])
    await state.clear()
    async with SessionLocal() as session:
        service = ProductService(session)
        parent = await service.get(parent_id)
        categories = await service.list_categories(include_inactive=True)
        variants = await service.list_variants(parent_id, include_inactive=True)
    if not parent:
        await callback.message.answer('محصول مادر پیدا نشد.')
        return
    cat_title = _category_title(categories, ProductService.product_category_id(parent))
    await callback.message.answer(
        'ساخت محصول چندحالته تمام شد ✅\n\n' + _product_summary(parent, cat_title, variants=variants),
        reply_markup=product_manage_keyboard(parent.id, parent.is_active, is_variant_parent=True),
    )

@router.callback_query(F.data == 'admin:product:add')
async def add_product(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.clear()
    await state.update_data(mode='create')
    async with SessionLocal() as session:
        categories = await ProductService(session).list_categories()
    await callback.message.answer('دسته‌بندی محصول را انتخاب کن:', reply_markup=category_choice_keyboard(categories))




@router.callback_query(F.data == 'admin:product:add_multi')
async def add_multi_product(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.clear()
    await state.update_data(mode='create_multi_parent')
    async with SessionLocal() as session:
        categories = await ProductService(session).list_categories()
    await callback.message.answer('دسته‌بندی محصول چندحالته را انتخاب کن:', reply_markup=category_choice_keyboard(categories))

@router.callback_query(F.data.startswith('admin:product:select_category:'))
async def choose_product_category(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    await state.update_data(category_id=None if category_id == 'uncategorized' else category_id)
    await state.set_state(AdminProductStates.waiting_title)
    await callback.message.answer('عنوان محصول را بفرست. همین عنوان دقیقاً برای مشتری نمایش داده می‌شود:')


@router.message(AdminProductStates.waiting_title)
async def product_title(message: Message, state: FSMContext) -> None:
    title = (message.text or '').strip()
    if not title:
        await message.answer('عنوان معتبر نیست.')
        return
    await state.update_data(title=title)
    data = await state.get_data()
    await state.set_state(AdminProductStates.waiting_description)
    if data.get('mode') == 'create_multi_parent':
        await message.answer('توضیحات کلی محصول چندحالته را بفرست. این متن در صفحه اصلی محصول نمایش داده می‌شود:')
    elif data.get('mode') == 'add_variant':
        await message.answer('توضیحات مخصوص همین حالت/زیرمحصول را بفرست:')
    else:
        await message.answer('توضیحات محصول را بفرست:')


@router.message(AdminProductStates.waiting_description)
async def product_description(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    description = message.text or ''
    if data.get('mode') == 'create_multi_parent':
        async with SessionLocal() as session:
            service = ProductService(session)
            parent = await service.create_variant_parent(
                title=data['title'],
                slug='-'.join((data['title'] or '').lower().split()),
                description=description,
                category_id=data.get('category_id'),
            )
            await AdminService(session).log(message.from_user.id, 'create_multi_product_parent', 'product', str(parent.id), {'title': parent.title})
        await state.clear()
        await state.set_state(AdminProductStates.waiting_title)
        await state.update_data(mode='add_variant', parent_id=parent.id, category_id=data.get('category_id'))
        await message.answer(
            f'محصول چندحالته مادر #{parent.id} ساخته شد ✅\n\n'
            'حالا عنوان حالت اول را بفرست. مثال: «یک ماهه اکانت آماده» یا «شش ماهه روی ایمیل شخصی»'
        )
        return
    await state.update_data(description=description)
    await message.answer('قیمت این محصول/حالت را چطور وارد می‌کنی؟', reply_markup=price_currency_keyboard())


@router.callback_query(F.data.startswith('admin:product:price_currency:'))
async def choose_price_currency(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    currency = callback.data.split(':')[-1]
    if currency not in {'toman', 'usd'}:
        currency = 'toman'
    await state.update_data(price_currency=currency)
    await state.set_state(AdminProductStates.waiting_price)
    if currency == 'usd':
        await callback.message.answer('قیمت دلاری را وارد کن. مثال: 9.99')
    else:
        await callback.message.answer('قیمت محصول را به تومان وارد کن:')


@router.message(AdminProductStates.waiting_price)
async def product_price(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    currency = 'usd' if data.get('mode') == 'edit_dollar_price' else str(data.get('price_currency') or 'toman')
    try:
        price = Decimal((message.text or '').replace(',', '').strip())
        if price < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await message.answer('قیمت معتبر نیست. فقط عدد بفرست.')
        return
    if currency == 'usd':
        await state.update_data(usd_price=str(price))
        await state.set_state(AdminProductStates.waiting_usd_rate)
        await message.answer('نرخ هر ۱ دلار به تومان را وارد کن تا معادل تومانی برای پرداخت محاسبه شود. مثال: 60000')
        return
    await state.update_data(price=str(price), price_currency='toman')
    await message.answer('نوع محصول را انتخاب کن:', reply_markup=product_kind_keyboard())


@router.message(AdminProductStates.waiting_usd_rate)
async def product_usd_rate(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        rate = Decimal((message.text or '').replace(',', '').strip())
        if rate <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        await message.answer('نرخ دلار معتبر نیست. فقط عدد مثبت بفرست.')
        return
    usd_price = Decimal(str(data.get('usd_price') or '0'))
    toman_price = (usd_price * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    if data.get('mode') == 'edit_dollar_price':
        async with SessionLocal() as session:
            service = ProductService(session)
            product = await service.get(int(data['product_id']))
            if not product:
                await message.answer('محصول پیدا نشد.')
                await state.clear()
                return
            product = await service.set_dollar_price(product, usd_price, rate)
            await AdminService(session).log(message.from_user.id, 'edit_product_dollar_price', 'product', str(product.id), {'usd_price': str(usd_price), 'usd_rate': str(rate)})
        await state.clear()
        await message.answer(f'قیمت دلاری ذخیره شد ✅\nقیمت نمایش: {product_price_display(product)}')
        return
    await state.update_data(price=str(toman_price), usd_rate=str(rate), price_currency='usd')
    await message.answer(f'معادل تومانی محاسبه شد: {money(toman_price)}\nنوع محصول را انتخاب کن:', reply_markup=product_kind_keyboard())


@router.callback_query(F.data.startswith('admin:product:kind:'))
async def choose_product_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    kind = callback.data.split(':')[-1]
    data = await state.get_data()
    if data.get('mode') == 'edit_kind':
        async with SessionLocal() as session:
            product = await ProductService(session).get(int(data['product_id']))
            if product:
                await ProductService(session).update_field(product, 'kind', kind)
                await AdminService(session).log(callback.from_user.id, 'edit_product_kind', 'product', str(product.id))
        await state.clear()
        await callback.message.answer('نوع محصول ویرایش شد ✅')
        return
    await state.update_data(kind=kind)
    await callback.message.answer('شیوه تحویل را انتخاب کن:', reply_markup=delivery_kind_keyboard())


@router.callback_query(F.data.startswith('admin:product:delivery:'))
async def choose_delivery_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    delivery = callback.data.split(':')[-1]
    data = await state.get_data()
    if data.get('mode') == 'edit_delivery':
        selected_mode = 'manual'
        async with SessionLocal() as session:
            service = ProductService(session)
            product = await service.get(int(data['product_id']))
            if product:
                await service.update_field(product, 'delivery_kind', delivery)
                if delivery in AUTO_DELIVERY_KINDS:
                    await service.sync_auto_stock(product)
                    selected_mode = auto_text_delivery_mode(product)
                await AdminService(session).log(callback.from_user.id, 'edit_product_delivery', 'product', str(product.id))
        if delivery in AUTO_DELIVERY_KINDS:
            await state.update_data(mode='edit_auto_text_mode', product_id=int(data['product_id']))
            await callback.message.answer(
                'شیوه تحویل اتوتکست را انتخاب کن:\n\n'
                'اگر «تحویل خودکار» را بزنی، بعد از تایید پرداخت یا پرداخت خودکار، محتوا بدون نیاز به دکمه تحویل برای مشتری ارسال می‌شود.\n'
                'اگر «نمایش دکمه تحویل» را بزنی، ادمین باید بعد از بررسی روی تحویل سفارش بزند.',
                reply_markup=auto_text_delivery_mode_keyboard(selected_mode),
            )
            return
        await state.clear()
        await callback.message.answer('شیوه تحویل ویرایش شد ✅')
        return
    await state.update_data(delivery_kind=delivery, required_field_keys=[])
    if delivery in AUTO_DELIVERY_KINDS:
        await callback.message.answer(
            'برای این محصول اتوتکست، نحوه تحویل بعد از تایید پرداخت را انتخاب کن:',
            reply_markup=auto_text_delivery_mode_keyboard('manual'),
        )
        return
    await callback.message.answer('چه اطلاعاتی از مشتری لازم است؟ گزینه‌ها را انتخاب کن:', reply_markup=required_fields_keyboard([]))


@router.callback_query(F.data.startswith('admin:product:auto_text_mode:'))
async def choose_auto_text_delivery_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    mode = callback.data.split(':')[-1]
    if mode not in {'manual', 'auto'}:
        mode = 'manual'
    data = await state.get_data()
    if data.get('mode') == 'edit_auto_text_mode':
        async with SessionLocal() as session:
            service = ProductService(session)
            product = await service.get(int(data['product_id']))
            if not product:
                await callback.message.answer('محصول پیدا نشد.')
                await state.clear()
                return
            if product.delivery_kind not in AUTO_DELIVERY_KINDS:
                await callback.message.answer('این گزینه فقط برای محصولات اتوتکست قابل استفاده است.')
                await state.clear()
                return
            await service.set_auto_text_delivery_mode(product, mode)
            await AdminService(session).log(callback.from_user.id, 'edit_auto_text_delivery_mode', 'product', str(product.id), {'mode': mode})
        await state.clear()
        title = 'تحویل خودکار بعد از تایید پرداخت' if mode == 'auto' else 'نمایش دکمه تحویل برای ادمین'
        await callback.message.answer(f'حالت تحویل اتوتکست ذخیره شد ✅\n{title}')
        return
    await state.update_data(auto_text_delivery_mode=mode)
    await callback.message.answer('چه اطلاعاتی از مشتری لازم است؟ گزینه‌ها را انتخاب کن:', reply_markup=required_fields_keyboard([]))


@router.callback_query(F.data.startswith('admin:product:field:'))
async def toggle_required_field(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    data = await state.get_data()
    selected = list(data.get('required_field_keys') or [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(required_field_keys=selected)
    await callback.message.edit_reply_markup(reply_markup=required_fields_keyboard(selected))


async def _ask_product_stock(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminProductStates.waiting_stock)
    await message.answer('موجودی را وارد کن. برای نامحدود بنویس unlimited یا نامحدود. برای اتوتکست، موجودی نهایی از تعداد متن‌های تحویل محاسبه می‌شود:')


@router.callback_query(F.data == 'admin:product:fields:done')
async def required_fields_done(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    selected = list(data.get('required_field_keys') or [])
    if data.get('mode') == 'edit_required_fields':
        async with SessionLocal() as session:
            product = await ProductService(session).get(int(data['product_id']))
            if product:
                await ProductService(session).set_required_fields(product, selected)
                await AdminService(session).log(callback.from_user.id, 'edit_product_fields', 'product', str(product.id))
        await state.clear()
        await callback.message.answer('اطلاعات لازم مشتری ویرایش شد ✅ برای تغییر متن اختصاصی ایمیل/شماره از ویرایش محصول استفاده کن.')
        return

    prompt_keys = _prompt_field_keys(selected)
    if prompt_keys:
        await state.set_state(AdminProductStates.waiting_field_prompt)
        await state.update_data(field_prompt_keys=prompt_keys, field_prompt_index=0, field_prompts={})
        await callback.message.answer(_field_prompt_question(prompt_keys[0]))
        return
    await _ask_product_stock(callback.message, state)


@router.message(AdminProductStates.waiting_field_prompt)
async def product_field_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get('mode') == 'edit_field_prompt':
        product_id = int(data['product_id'])
        field_key = str(data['field_key'])
        prompt = (message.text or '').strip()
        async with SessionLocal() as session:
            service = ProductService(session)
            product = await service.get(product_id)
            if not product:
                await message.answer('محصول پیدا نشد.')
                await state.clear()
                return
            required_keys = {str(item.get('name') or item.get('type') or '').strip() for item in (product.required_fields or [])}
            if field_key not in required_keys:
                await message.answer('اول این فیلد را از بخش «اطلاعات لازم مشتری» برای محصول فعال کن، بعد متن اختصاصی‌اش را ویرایش کن.')
                await state.clear()
                return
            await service.set_required_field_prompt(product, field_key, prompt)
            await AdminService(session).log(message.from_user.id, 'edit_product_field_prompt', 'product', str(product.id), {'field': field_key})
        await state.clear()
        await message.answer('متن اختصاصی این محصول ذخیره شد ✅')
        return

    prompt_keys = list(data.get('field_prompt_keys') or [])
    index = int(data.get('field_prompt_index') or 0)
    prompts = dict(data.get('field_prompts') or {})
    if index < len(prompt_keys):
        value = (message.text or '').strip()
        if value and value != '-':
            prompts[prompt_keys[index]] = value
    index += 1
    if index < len(prompt_keys):
        await state.update_data(field_prompt_index=index, field_prompts=prompts)
        await message.answer(_field_prompt_question(prompt_keys[index]))
        return
    await state.update_data(field_prompts=prompts)
    await _ask_product_stock(message, state)


@router.message(AdminProductStates.waiting_stock)
async def product_stock(message: Message, state: FSMContext) -> None:
    raw = (message.text or '').strip().lower()
    try:
        stock = None if raw in {'unlimited', 'نامحدود', '-', ''} else int(raw)
    except ValueError:
        await message.answer('موجودی معتبر نیست. عدد یا unlimited بفرست.')
        return
    await state.update_data(stock=stock)
    await state.set_state(AdminProductStates.waiting_show_stock)
    await message.answer('آیا موجودی در توضیحات محصول برای مشتری نمایش داده شود؟', reply_markup=show_stock_choice_keyboard())


@router.callback_query(F.data.startswith('admin:product:show_stock:'))
async def product_show_stock_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.split(':')[-1]
    await state.update_data(show_stock_to_customer=(value == 'yes'))
    await state.set_state(AdminProductStates.waiting_allow_quantity)
    await callback.message.answer('آیا اجازه خرید با تعداد مورد نیاز برای این محصول/حالت فعال باشد؟', reply_markup=allow_quantity_choice_keyboard())


@router.callback_query(F.data.startswith('admin:product:allow_quantity:'))
async def product_allow_quantity_choice(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    value = callback.data.split(':')[-1]
    await state.update_data(allow_quantity_purchase=(value == 'yes'))
    data = await state.get_data()
    if str(data.get('delivery_kind')) == 'manual':
        await _create_product_from_state(callback.message, state, initial_payloads=[], file_id=None)
        return
    await state.set_state(AdminProductStates.waiting_delivery_payload)
    await callback.message.answer('متن‌های تحویل خودکار را بفرست. برای ثبت چند آیتم، بین هر آیتم یک خط --- بگذار. اگر فعلاً نداری یک خط تیره - بفرست:')

@router.message(AdminProductStates.waiting_delivery_payload)
async def product_payload(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    payload_text = message.text or message.caption or '-'
    # Current delivery model supports only manual and auto_text. Auto-text
    # inventory is always stored as plain text, not file/photo/video payloads.
    file_id = None
    payloads = _split_delivery_payload(payload_text)
    if data.get('mode') == 'add_delivery':
        product_id = int(data['product_id'])
        async with SessionLocal() as session:
            service = ProductService(session)
            product = await service.get(product_id)
            if not product:
                await message.answer('محصول پیدا نشد.')
                await state.clear()
                return
            if file_id:
                count = await service.add_delivery_items(product, [payload_text if payload_text != '-' else 'فایل تحویل'], file_id=file_id)
            else:
                count = await service.add_delivery_items(product, payloads)
            await service.sync_auto_stock(product)
            await AdminService(session).log(message.from_user.id, 'add_delivery_item', 'product', str(product.id), {'count': count})
        await state.clear()
        await message.answer(f'{count} محتوای تحویل اضافه شد ✅')
        return
    await _create_product_from_state(message, state, initial_payloads=payloads, file_id=file_id)


async def _create_product_from_state(message: Message, state: FSMContext, initial_payloads: list[str], file_id: str | None) -> None:
    data = await state.get_data()
    prompts = dict(data.get('field_prompts') or {})
    fields = []
    for key in data.get('required_field_keys') or []:
        item = {'name': key, 'label': REQUIRED_FIELD_TITLES.get(key, key), 'type': key}
        prompt = str(prompts.get(key) or '').strip()
        if prompt and prompt != '-':
            item['prompt'] = prompt
        fields.append(item)
    is_variant_flow = data.get('mode') == 'add_variant'
    parent_id = int(data['parent_id']) if is_variant_flow and data.get('parent_id') else None
    extra_settings = {'variant_parent_id': parent_id} if parent_id else None
    async with SessionLocal() as session:
        service = ProductService(session)
        parent = await service.get(parent_id) if parent_id else None
        category_id = data.get('category_id')
        if parent and not category_id:
            category_id = ProductService.product_category_id(parent)
        product = await service.create(
            title=data['title'],
            slug='-'.join((data['title'] or '').lower().split()),
            description=data.get('description') or '',
            price=Decimal(str(data['price'])),
            kind=data.get('kind') or 'digital',
            delivery_kind=data.get('delivery_kind') or 'manual',
            required_fields=fields,
            stock_count=data.get('stock'),
            category_id=category_id,
            auto_text_delivery_mode=data.get('auto_text_delivery_mode'),
            show_stock_to_customer=bool(data.get('show_stock_to_customer', False)),
            allow_quantity_purchase=bool(data.get('allow_quantity_purchase', False)),
            price_currency=data.get('price_currency') or 'toman',
            usd_price=data.get('usd_price'),
            usd_rate=data.get('usd_rate'),
            extra_settings=extra_settings,
        )
        count = 0
        if file_id:
            count = await service.add_delivery_items(product, [initial_payloads[0] if initial_payloads else 'فایل تحویل'], file_id=file_id)
        elif initial_payloads:
            count = await service.add_delivery_items(product, initial_payloads)
        if product.delivery_kind in AUTO_DELIVERY_KINDS:
            if count <= 0:
                product.stock_count = 0
                product.is_active = False
                await session.commit()
            else:
                await service.sync_auto_stock(product)
        action = 'create_variant_product' if is_variant_flow else 'create_product'
        await AdminService(session).log(message.from_user.id, action, 'product', str(product.id), {'title': product.title, 'parent_id': parent_id})
    await state.clear()
    if parent_id:
        await message.answer(
            f'حالت #{product.id} برای محصول مادر #{parent_id} ساخته شد ✅',
            reply_markup=multi_variant_next_keyboard(parent_id),
        )
        return
    await message.answer(
        f'محصول #{product.id} ساخته شد ✅',
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            is_auto_text=product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )


@router.callback_query(F.data.startswith('admin:toggle_product:'))
async def toggle_product(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_PRODUCTS):
            await callback.message.answer('دسترسی نداری.')
            return
        product = await ProductService(session).get(product_id)
        if not product:
            await callback.message.answer('محصول پیدا نشد.')
            return
        product = await ProductService(session).toggle(product)
        await AdminService(session).log(callback.from_user.id, 'toggle_product', 'product', str(product.id))
    await callback.message.answer(
        'وضعیت محصول تغییر کرد ✅',
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            is_auto_text=product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )


@router.callback_query(F.data.startswith('admin:delete_product:'))
async def delete_product(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
        if not product:
            await callback.message.answer('محصول پیدا نشد.')
            return
        await ProductService(session).soft_delete(product)
        await AdminService(session).log(callback.from_user.id, 'delete_product', 'product', str(product.id))
    await callback.message.answer('محصول حذف/غیرفعال شد ✅')


@router.callback_query(F.data.startswith('admin:product:edit:'))
async def edit_product(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    await callback.message.answer('کدام بخش ویرایش شود؟', reply_markup=product_edit_keyboard(product_id))



@router.callback_query(F.data.startswith('admin:product:edit_show_stock:'))
async def edit_show_stock_to_customer(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        if not product:
            await callback.message.answer('محصول پیدا نشد.')
            return
        product = await service.toggle_show_stock_to_customer(product)
        await AdminService(session).log(callback.from_user.id, 'edit_product_show_stock', 'product', str(product.id), {'show': show_stock_to_customer(product)})
    status = 'نمایش موجودی برای مشتری روشن شد ✅' if show_stock_to_customer(product) else 'نمایش موجودی برای مشتری خاموش شد ✅'
    await callback.message.answer(
        status,
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            is_auto_text=product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )



@router.callback_query(F.data.startswith('admin:product:edit_allow_quantity:'))
async def edit_allow_quantity(callback: CallbackQuery) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        if not product:
            await callback.message.answer('محصول پیدا نشد.')
            return
        product = await service.toggle_allow_quantity_purchase(product)
        await AdminService(session).log(callback.from_user.id, 'edit_product_allow_quantity', 'product', str(product.id), {'allow': allow_quantity_purchase(product)})
    status = 'خرید با تعداد مورد نیاز روشن شد ✅' if allow_quantity_purchase(product) else 'خرید با تعداد مورد نیاز خاموش شد ✅'
    await callback.message.answer(
        status,
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            is_auto_text=product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )


@router.callback_query(F.data.startswith('admin:product:edit_dollar_price:'))
async def edit_dollar_price(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
    if not product:
        await callback.message.answer('محصول پیدا نشد.')
        return
    if is_variant_parent(product):
        await callback.message.answer('قیمت محصول مادر چندحالته از روی حالت‌ها تعیین می‌شود. قیمت دلاری را روی خود حالت/زیرمحصول تنظیم کن.')
        return
    await state.set_state(AdminProductStates.waiting_price)
    await state.update_data(mode='edit_dollar_price', product_id=product_id, price_currency='usd')
    await callback.message.answer('قیمت دلاری جدید را وارد کن. مثال: 9.99')

@router.callback_query(F.data.startswith('admin:product:edit_field:'))
async def edit_field_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    product_id, field = parts[3], parts[4]
    await state.set_state(AdminProductStates.waiting_edit_value)
    await state.update_data(product_id=int(product_id), edit_field=field)
    await callback.message.answer(f'مقدار جدید {field} را بفرست:')


@router.message(AdminProductStates.waiting_edit_value)
async def save_edit_field(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        product = await ProductService(session).get(int(data['product_id']))
        if not product:
            await message.answer('محصول پیدا نشد.')
            await state.clear()
            return
        try:
            product = await ProductService(session).update_field(product, data['edit_field'], message.text or '')
        except Exception as exc:
            await message.answer(f'مقدار معتبر نیست: {exc}')
            return
        await AdminService(session).log(message.from_user.id, 'edit_product', 'product', str(product.id), {'field': data['edit_field']})
    await state.clear()
    await message.answer(
        'ویرایش انجام شد ✅',
        reply_markup=product_manage_keyboard(
            product.id,
            product.is_active,
            is_auto_text=product.delivery_kind in AUTO_DELIVERY_KINDS,
            is_variant_parent=is_variant_parent(product),
            variant_parent_id=variant_parent_id(product),
        ),
    )


@router.callback_query(F.data.startswith('admin:product:edit_category:'))
async def edit_category(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        categories = await service.list_categories()
        product = await service.get(product_id)
    selected = ProductService.product_category_id(product) if product else None
    await state.update_data(mode='edit_category', product_id=product_id)
    await callback.message.answer('دسته‌بندی جدید محصول را انتخاب کن:', reply_markup=category_choice_keyboard(categories, selected_id=selected, prefix='admin:product:edit_category_select'))


@router.callback_query(F.data.startswith('admin:product:edit_category_select:'))
async def edit_category_select(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    category_id = callback.data.split(':')[-1]
    data = await state.get_data()
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(int(data['product_id']))
        if product:
            await service.set_category(product, None if category_id == 'uncategorized' else category_id)
            await AdminService(session).log(callback.from_user.id, 'edit_product_category', 'product', str(product.id))
    await state.clear()
    await callback.message.answer('دسته‌بندی محصول ویرایش شد ✅')


@router.callback_query(F.data.startswith('admin:product:edit_kind:'))
async def edit_kind(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    await state.update_data(mode='edit_kind', product_id=product_id)
    await callback.message.answer('نوع جدید محصول را انتخاب کن:', reply_markup=product_kind_keyboard())


@router.callback_query(F.data.startswith('admin:product:edit_delivery:'))
async def edit_delivery(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    await state.update_data(mode='edit_delivery', product_id=product_id)
    await callback.message.answer('شیوه تحویل جدید را انتخاب کن:', reply_markup=delivery_kind_keyboard())


@router.callback_query(F.data.startswith('admin:product:edit_auto_mode:'))
async def edit_auto_text_mode(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
    if not product:
        await callback.message.answer('محصول پیدا نشد.')
        return
    if product.delivery_kind not in AUTO_DELIVERY_KINDS:
        await callback.message.answer('این گزینه فقط وقتی قابل استفاده است که شیوه تحویل محصول «تحویل خودکار متن» باشد.')
        return
    await state.update_data(mode='edit_auto_text_mode', product_id=product_id)
    await callback.message.answer(
        'حالت تحویل اتوتکست را انتخاب کن:',
        reply_markup=auto_text_delivery_mode_keyboard(auto_text_delivery_mode(product)),
    )


@router.callback_query(F.data.startswith('admin:product:edit_fields:'))
async def edit_required_fields(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        product = await ProductService(session).get(product_id)
    selected = [f.get('name') for f in (product.required_fields or [])] if product else []
    await state.update_data(mode='edit_required_fields', product_id=product_id, required_field_keys=selected)
    await callback.message.answer('اطلاعات لازم مشتری را انتخاب کن:', reply_markup=required_fields_keyboard(selected))


@router.callback_query(F.data.startswith('admin:product:edit_prompt:'))
async def edit_product_field_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    product_id = int(parts[3])
    field_key = parts[4]
    await state.set_state(AdminProductStates.waiting_field_prompt)
    await state.update_data(mode='edit_field_prompt', product_id=product_id, field_key=field_key)
    await callback.message.answer(_field_prompt_question(field_key))



def _format_unused_delivery_items(product, items: list, *, for_message: bool = False, limit_items: int | None = None) -> str:
    title = html.escape(product.title) if for_message else product.title
    lines = [
        '\u0645\u062d\u062a\u0648\u0627\u0647\u0627\u06cc \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0646\u0634\u062f\u0647 \u0627\u062a\u0648\u062a\u06a9\u0633\u062a',
        f'\u0645\u062d\u0635\u0648\u0644: #{product.id} {title}',
        f'\u062a\u0639\u062f\u0627\u062f \u0645\u062d\u062a\u0648\u0627\u0647\u0627\u06cc \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0646\u0634\u062f\u0647: {len(items)}',
        '',
    ]
    shown_items = items[:limit_items] if limit_items else items
    if not shown_items:
        lines.append('\u0647\u06cc\u0686 \u0645\u062d\u062a\u0648\u0627\u06cc \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0646\u0634\u062f\u0647\u200c\u0627\u06cc \u0628\u0631\u0627\u06cc \u0627\u06cc\u0646 \u0645\u062d\u0635\u0648\u0644 \u0648\u062c\u0648\u062f \u0646\u062f\u0627\u0631\u062f.')
    for index, item in enumerate(shown_items, 1):
        payload = (item.payload or '').strip() or ('\u0641\u0627\u06cc\u0644 \u062a\u062d\u0648\u06cc\u0644' if item.file_id else '\u2014')
        if item.file_id:
            payload = f'{payload}\nfile_id: {item.file_id}'
        if for_message:
            payload = html.escape(payload)
        lines.append(f'{index}. #{item.id}\n{payload}')
        lines.append('-' * 24)
    if limit_items and len(items) > limit_items:
        lines.append('\u0641\u0647\u0631\u0633\u062a \u06a9\u0627\u0645\u0644 \u062f\u0631 \u0641\u0627\u06cc\u0644 \u062a\u06a9\u0633\u062a \u0627\u0631\u0633\u0627\u0644 \u0634\u062f.')
    return '\n'.join(lines)


async def _send_unused_delivery_items(target: Message, product, items: list) -> None:
    limit_items = 20 if len(items) > 20 else None
    text = _format_unused_delivery_items(product, items, for_message=True, limit_items=limit_items)
    await target.answer(text[:3900], reply_markup=delivery_items_manage_keyboard(product.id))
    file_text = _format_unused_delivery_items(product, items, for_message=False)
    file = BufferedInputFile(file_text.encode('utf-8'), filename=f'auto_text_unused_product_{product.id}.txt')
    await target.answer_document(file, caption='\u0641\u0627\u06cc\u0644 \u062a\u06a9\u0633\u062a \u0645\u062d\u062a\u0648\u0627\u0647\u0627\u06cc \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0646\u0634\u062f\u0647')


@router.callback_query(F.data.startswith('admin:product:unused_delivery:'))
async def show_unused_delivery_items(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    product_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        if not product:
            await callback.message.answer('محصول پیدا نشد.')
            return
        if product.delivery_kind not in AUTO_DELIVERY_KINDS:
            await callback.message.answer('این گزینه فقط برای محصولات اتوتکست است.')
            return
        items = await service.list_unused_delivery_items(product.id)
    await _send_unused_delivery_items(callback.message, product, items)


@router.callback_query(F.data.startswith('admin:product:delete_delivery_prompt:'))
async def delete_delivery_item_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _has_access(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    product_id = int(callback.data.split(':')[-1])
    await state.set_state(AdminProductStates.waiting_delete_delivery_number)
    await state.update_data(mode='delete_delivery', product_id=product_id)
    await callback.message.answer('شماره محتوایی که می‌خواهی حذف شود را بفرست. فقط عدد همان ردیف را ارسال کن:')


@router.message(AdminProductStates.waiting_delete_delivery_number)
async def delete_delivery_item_by_number(message: Message, state: FSMContext) -> None:
    try:
        number = int((message.text or '').strip())
    except ValueError:
        await message.answer('شماره معتبر نیست. فقط عدد ردیف را بفرست.')
        return
    data = await state.get_data()
    product_id = int(data.get('product_id'))
    async with SessionLocal() as session:
        service = ProductService(session)
        product = await service.get(product_id)
        if not product:
            await message.answer('محصول پیدا نشد.')
            await state.clear()
            return
        if product.delivery_kind not in AUTO_DELIVERY_KINDS:
            await message.answer('این گزینه فقط برای محصولات اتوتکست است.')
            await state.clear()
            return
        deleted = await service.delete_unused_delivery_item_by_number(product, number)
        if not deleted:
            await message.answer('شماره واردشده در لیست محتواهای فروخته‌نشده وجود ندارد.')
            return
        await AdminService(session).log(message.from_user.id, 'delete_unused_delivery_item', 'product', str(product.id), {'number': number, 'delivery_item_id': deleted.get('id')})
        items = await service.list_unused_delivery_items(product.id)
    await state.clear()
    await message.answer(f'\u0645\u062d\u062a\u0648\u0627\u06cc \u0634\u0645\u0627\u0631\u0647 {number} \u062d\u0630\u0641 \u0634\u062f \u2705\n\u0644\u06cc\u0633\u062a \u0628\u0639\u062f \u0627\u0632 \u062d\u0630\u0641 \u062f\u0648\u0628\u0627\u0631\u0647 \u0634\u0645\u0627\u0631\u0647\u200c\u06af\u0630\u0627\u0631\u06cc \u0634\u062f:')
    await _send_unused_delivery_items(message, product, items)


@router.callback_query(F.data.startswith('admin:product:add_delivery:'))
async def add_delivery_item(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    product_id = int(callback.data.split(':')[-1])
    await state.set_state(AdminProductStates.waiting_delivery_payload)
    await state.update_data(mode='add_delivery', product_id=product_id)
    await callback.message.answer('متن‌های قابل تحویل را بفرست. برای چند آیتم، بین هر آیتم یک خط --- بگذار تا ربات هرکدام را جدا ذخیره کند:')
