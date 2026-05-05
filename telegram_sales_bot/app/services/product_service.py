from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DeliveryKind
from app.db.models import DeliveryItem, Product
from app.services.settings_service import SettingsService
from app.utils.text import money

# Only manual and auto_text are supported in the current product flow.
AUTO_DELIVERY_KINDS = {DeliveryKind.AUTO_TEXT.value}

AUTO_TEXT_DELIVERY_MODE_MANUAL = 'manual'
AUTO_TEXT_DELIVERY_MODE_AUTO = 'auto'
AUTO_TEXT_DELIVERY_MODES = {AUTO_TEXT_DELIVERY_MODE_MANUAL, AUTO_TEXT_DELIVERY_MODE_AUTO}

PRICE_CURRENCY_TOMAN = 'toman'
PRICE_CURRENCY_USD = 'usd'
PRICE_CURRENCIES = {PRICE_CURRENCY_TOMAN, PRICE_CURRENCY_USD}

# گزینه‌های نمایش (تک‌ستونه/دوستونه) برای دسته‌بندی‌ها و محصولات داخل دسته‌بندی.
LAYOUT_SINGLE = 'single'
LAYOUT_DOUBLE = 'double'
LAYOUTS = {LAYOUT_SINGLE, LAYOUT_DOUBLE}


def normalize_layout(value: Any, default: str = LAYOUT_SINGLE) -> str:
    """Return a valid layout string ('single' or 'double')."""
    text = str(value or '').strip().lower()
    if text in LAYOUTS:
        return text
    if default in LAYOUTS:
        return default
    return LAYOUT_SINGLE


def category_layout(category: dict | None, default: str = LAYOUT_SINGLE) -> str:
    """Layout to use for products inside a single category."""
    if not isinstance(category, dict):
        return normalize_layout(None, default)
    return normalize_layout(category.get('layout'), default)


def layout_columns(layout: str) -> int:
    return 2 if normalize_layout(layout) == LAYOUT_DOUBLE else 1


def _extra(product: Product) -> dict[str, Any]:
    return dict(getattr(product, 'extra_settings', None) or {})


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_decimal(value: Any, default: Decimal = Decimal('0')) -> Decimal:
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, TypeError, ValueError):
        return default


def _format_decimal(value: Decimal | int | float | str) -> str:
    amount = _as_decimal(value)
    if amount == amount.to_integral_value():
        return f'{amount:,.0f}'
    return f'{amount:,.2f}'.rstrip('0').rstrip('.')


def auto_text_delivery_mode(product: Product) -> str:
    """Return how an auto-text product should be delivered after payment."""
    extra = _extra(product)
    value = str(extra.get('auto_text_delivery_mode') or '').strip().lower()
    if value in AUTO_TEXT_DELIVERY_MODES:
        return value
    if bool(extra.get('auto_deliver_after_payment')):
        return AUTO_TEXT_DELIVERY_MODE_AUTO
    return AUTO_TEXT_DELIVERY_MODE_MANUAL


def should_auto_deliver_after_payment(product: Product) -> bool:
    return (
        getattr(product, 'delivery_kind', None) == DeliveryKind.AUTO_TEXT.value
        and auto_text_delivery_mode(product) == AUTO_TEXT_DELIVERY_MODE_AUTO
    )


def auto_text_delivery_mode_title(product: Product) -> str:
    return 'تحویل خودکار بعد از تایید پرداخت' if should_auto_deliver_after_payment(product) else 'نمایش دکمه تحویل برای ادمین'


def show_stock_to_customer(product: Product) -> bool:
    return bool(_extra(product).get('show_stock_to_customer', False))


def allow_quantity_purchase(product: Product) -> bool:
    return bool(_extra(product).get('allow_quantity_purchase', False))


def is_variant_parent(product: Product) -> bool:
    return bool(_extra(product).get('is_variant_parent'))


def variant_parent_id(product: Product) -> int | None:
    value = _extra(product).get('variant_parent_id')
    return _to_int(value)


def is_variant_product(product: Product) -> bool:
    return variant_parent_id(product) is not None


def product_price_currency(product: Product) -> str:
    value = str(_extra(product).get('price_currency') or PRICE_CURRENCY_TOMAN).strip().lower()
    return value if value in PRICE_CURRENCIES else PRICE_CURRENCY_TOMAN


def product_price_display(product: Product, quantity: int = 1) -> str:
    qty = max(1, int(quantity or 1))
    toman_total = _as_decimal(getattr(product, 'price', 0)) * Decimal(qty)
    extra = _extra(product)
    if product_price_currency(product) == PRICE_CURRENCY_USD:
        usd_price = _as_decimal(extra.get('usd_price'))
        if usd_price > 0:
            usd_total = usd_price * Decimal(qty)
            return f'{_format_decimal(usd_total)} دلار | معادل {money(toman_total)}'
    return money(toman_total)


def order_quantity(order: Any) -> int:
    fields = dict(getattr(order, 'user_fields', None) or {})
    quantity = _to_int(fields.get('_quantity'), 1) or 1
    return max(1, quantity)


def product_has_enough_stock(product: Product, quantity: int = 1) -> bool:
    quantity = max(1, int(quantity or 1))
    stock = getattr(product, 'stock_count', None)
    return stock is None or stock >= quantity


def product_max_quantity(product: Product) -> int | None:
    stock = getattr(product, 'stock_count', None)
    if stock is None:
        return None
    return max(0, int(stock))


class ProductService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = SettingsService(session)

    def _not_deleted(self, product: Product) -> bool:
        return not (product.extra_settings or {}).get('deleted')

    def _is_customer_available(self, product: Product) -> bool:
        if not product.is_active or not self._not_deleted(product):
            return False
        if is_variant_parent(product):
            return True
        if product.stock_count is not None and product.stock_count <= 0:
            return False
        return True

    @staticmethod
    def product_category_id(product: Product) -> str | None:
        value = (product.extra_settings or {}).get('category_id')
        return str(value) if value else None

    async def list_categories(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        cfg = await self.settings.get('product_categories')
        items = [dict(item) for item in (cfg.get('items') or [])]
        if include_inactive:
            return items
        return [item for item in items if item.get('is_active', True)]

    async def create_category(self, title: str) -> dict[str, Any]:
        cfg = await self.settings.get('product_categories')
        next_id = int(cfg.get('next_id') or 1)
        item = {
            'id': f'cat_{next_id}',
            'title': title.strip() or f'دسته {next_id}',
            'is_active': True,
            'layout': LAYOUT_SINGLE,
        }
        cfg['next_id'] = next_id + 1
        cfg['items'] = list(cfg.get('items') or []) + [item]
        await self.settings.set('product_categories', cfg)
        return item

    async def get_category(self, category_id: str) -> dict[str, Any] | None:
        for item in await self.list_categories(include_inactive=True):
            if str(item.get('id')) == str(category_id):
                return item
        return None

    async def update_category(
        self,
        category_id: str,
        *,
        title: str | None = None,
        toggle: bool = False,
        delete: bool = False,
        layout: str | None = None,
    ) -> dict[str, Any] | None:
        cfg = await self.settings.get('product_categories')
        items = list(cfg.get('items') or [])
        updated = None
        for item in items:
            if str(item.get('id')) == str(category_id):
                if title is not None:
                    item['title'] = title.strip() or item.get('title') or category_id
                if toggle:
                    item['is_active'] = not bool(item.get('is_active', True))
                if delete:
                    item['is_active'] = False
                    item['deleted'] = True
                if layout is not None:
                    item['layout'] = normalize_layout(layout)
                updated = item
                break
        cfg['items'] = items
        await self.settings.set('product_categories', cfg)
        return updated

    async def get_categories_layout(self) -> str:
        cfg = await self.settings.get('product_categories')
        return normalize_layout(cfg.get('categories_layout'))

    async def set_categories_layout(self, layout: str) -> str:
        cfg = await self.settings.get('product_categories')
        cfg['categories_layout'] = normalize_layout(layout)
        await self.settings.set('product_categories', cfg)
        return cfg['categories_layout']

    async def get_uncategorized_layout(self) -> str:
        cfg = await self.settings.get('product_categories')
        return normalize_layout(cfg.get('uncategorized_layout'))

    async def set_uncategorized_layout(self, layout: str) -> str:
        cfg = await self.settings.get('product_categories')
        cfg['uncategorized_layout'] = normalize_layout(layout)
        await self.settings.set('product_categories', cfg)
        return cfg['uncategorized_layout']

    async def category_counts(self, customer_visible: bool = False) -> dict[str, int]:
        result = await self.session.execute(select(Product).order_by(Product.id.desc()))
        products = list(result.scalars().all())
        active_parent_ids: set[int] = set()
        if customer_visible:
            for product in products:
                parent_id = variant_parent_id(product)
                if parent_id and self._is_customer_available(product):
                    active_parent_ids.add(parent_id)
        counts: dict[str, int] = {}
        for product in products:
            if not self._not_deleted(product) or is_variant_product(product):
                continue
            if customer_visible:
                if not product.is_active:
                    continue
                if is_variant_parent(product):
                    if product.id not in active_parent_ids:
                        continue
                elif product.stock_count is not None and product.stock_count <= 0:
                    continue
            key = self.product_category_id(product) or 'uncategorized'
            counts[key] = counts.get(key, 0) + 1
        return counts

    async def list_active(self, category_id: str | None = None) -> list[Product]:
        result = await self.session.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.id.desc()))
        products = list(result.scalars().all())
        active_parent_ids: set[int] = set()
        for product in products:
            parent_id = variant_parent_id(product)
            if parent_id and self._is_customer_available(product):
                active_parent_ids.add(parent_id)
        filtered: list[Product] = []
        for product in products:
            if is_variant_product(product) or not self._not_deleted(product):
                continue
            if is_variant_parent(product):
                if product.id not in active_parent_ids:
                    continue
            elif product.stock_count is not None and product.stock_count <= 0:
                continue
            if category_id is not None:
                pid = self.product_category_id(product) or 'uncategorized'
                if pid != category_id:
                    continue
            filtered.append(product)
        return filtered

    async def list_all(self, include_deleted: bool = False, category_id: str | None = None) -> list[Product]:
        result = await self.session.execute(select(Product).order_by(Product.id.desc()))
        products = list(result.scalars().all())
        if not include_deleted:
            products = [p for p in products if self._not_deleted(p)]
        if category_id is not None:
            products = [p for p in products if (self.product_category_id(p) or 'uncategorized') == category_id]
        return products

    async def list_variants(self, parent_id: int, include_inactive: bool = False) -> list[Product]:
        result = await self.session.execute(select(Product).order_by(Product.id.asc()))
        variants: list[Product] = []
        for product in result.scalars().all():
            if variant_parent_id(product) != int(parent_id):
                continue
            if not self._not_deleted(product):
                continue
            if not include_inactive and not self._is_customer_available(product):
                continue
            variants.append(product)
        return variants

    async def get(self, product_id: int) -> Product | None:
        result = await self.session.execute(select(Product).where(Product.id == product_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        title: str,
        slug: str,
        description: str,
        price: Decimal,
        kind: str,
        delivery_kind: str,
        required_fields: list[dict[str, Any]] | None = None,
        stock_count: int | None = None,
        category_id: str | None = None,
        auto_text_delivery_mode: str | None = None,
        show_stock_to_customer: bool = False,
        allow_quantity_purchase: bool = False,
        price_currency: str | None = None,
        usd_price: Decimal | str | None = None,
        usd_rate: Decimal | str | None = None,
        extra_settings: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> Product:
        base_slug = slug or '-'.join((title or 'product').lower().split())
        slug_value = base_slug
        suffix = 1
        while True:
            result = await self.session.execute(select(Product).where(Product.slug == slug_value))
            if not result.scalar_one_or_none():
                break
            suffix += 1
            slug_value = f'{base_slug}-{suffix}'
        extra: dict[str, Any] = {}
        extra['show_stock_to_customer'] = bool(show_stock_to_customer)
        extra['allow_quantity_purchase'] = bool(allow_quantity_purchase)
        currency = str(price_currency or PRICE_CURRENCY_TOMAN).strip().lower()
        if currency not in PRICE_CURRENCIES:
            currency = PRICE_CURRENCY_TOMAN
        extra['price_currency'] = currency
        if currency == PRICE_CURRENCY_USD:
            extra['usd_price'] = str(usd_price or '0')
            extra['usd_rate'] = str(usd_rate or '0')
        if category_id and category_id != 'uncategorized':
            extra['category_id'] = category_id
        if delivery_kind == DeliveryKind.AUTO_TEXT.value:
            mode = str(auto_text_delivery_mode or AUTO_TEXT_DELIVERY_MODE_MANUAL).strip().lower()
            if mode not in AUTO_TEXT_DELIVERY_MODES:
                mode = AUTO_TEXT_DELIVERY_MODE_MANUAL
            extra['auto_text_delivery_mode'] = mode
            extra['auto_deliver_after_payment'] = mode == AUTO_TEXT_DELIVERY_MODE_AUTO
        extra.update(extra_settings or {})
        product = Product(
            title=title,
            slug=slug_value,
            description=description,
            price=price,
            kind=kind,
            delivery_kind=delivery_kind,
            required_fields=required_fields or [],
            stock_count=stock_count,
            is_active=is_active,
            extra_settings=extra,
        )
        self.session.add(product)
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def create_variant_parent(
        self,
        title: str,
        slug: str,
        description: str,
        category_id: str | None = None,
    ) -> Product:
        return await self.create(
            title=title,
            slug=slug,
            description=description,
            price=Decimal('0'),
            kind='digital',
            delivery_kind=DeliveryKind.MANUAL.value,
            required_fields=[],
            stock_count=None,
            category_id=category_id,
            show_stock_to_customer=False,
            allow_quantity_purchase=False,
            extra_settings={'is_variant_parent': True},
            is_active=True,
        )

    async def toggle(self, product: Product) -> Product:
        product.is_active = not product.is_active
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def soft_delete(self, product: Product) -> Product:
        extra = dict(product.extra_settings or {})
        extra['deleted'] = True
        product.extra_settings = extra
        product.is_active = False
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def update_field(self, product: Product, field: str, value: Any) -> Product:
        if field == 'price':
            value = Decimal(str(value).replace(',', '').strip())
            extra = dict(product.extra_settings or {})
            if extra.get('price_currency') == PRICE_CURRENCY_USD:
                # Editing the direct price from the old edit screen means a toman price.
                # Clear dollar metadata so customer display stays correct.
                extra['price_currency'] = PRICE_CURRENCY_TOMAN
                extra.pop('usd_price', None)
                extra.pop('usd_rate', None)
                product.extra_settings = extra
        elif field == 'stock_count':
            if str(value).strip().lower() in {'', '-', 'unlimited', 'نامحدود'}:
                value = None
            else:
                value = int(value)
        elif field in {'title', 'description', 'kind', 'delivery_kind'}:
            value = str(value)
        else:
            raise ValueError('Unsupported product field')
        setattr(product, field, value)
        if field == 'delivery_kind':
            extra = dict(product.extra_settings or {})
            if value == DeliveryKind.AUTO_TEXT.value and str(extra.get('auto_text_delivery_mode') or '') not in AUTO_TEXT_DELIVERY_MODES:
                extra['auto_text_delivery_mode'] = AUTO_TEXT_DELIVERY_MODE_MANUAL
                extra['auto_deliver_after_payment'] = False
            product.extra_settings = extra
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def set_auto_text_delivery_mode(self, product: Product, mode: str) -> Product:
        mode = str(mode or AUTO_TEXT_DELIVERY_MODE_MANUAL).strip().lower()
        if mode not in AUTO_TEXT_DELIVERY_MODES:
            mode = AUTO_TEXT_DELIVERY_MODE_MANUAL
        extra = dict(product.extra_settings or {})
        extra['auto_text_delivery_mode'] = mode
        # Keep the legacy boolean in sync for old code/backups that may inspect it.
        extra['auto_deliver_after_payment'] = mode == AUTO_TEXT_DELIVERY_MODE_AUTO
        product.extra_settings = extra
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def set_show_stock_to_customer(self, product: Product, show: bool) -> Product:
        extra = dict(product.extra_settings or {})
        extra['show_stock_to_customer'] = bool(show)
        product.extra_settings = extra
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def toggle_show_stock_to_customer(self, product: Product) -> Product:
        return await self.set_show_stock_to_customer(product, not show_stock_to_customer(product))

    async def set_allow_quantity_purchase(self, product: Product, allow: bool) -> Product:
        extra = dict(product.extra_settings or {})
        extra['allow_quantity_purchase'] = bool(allow)
        product.extra_settings = extra
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def toggle_allow_quantity_purchase(self, product: Product) -> Product:
        return await self.set_allow_quantity_purchase(product, not allow_quantity_purchase(product))

    async def set_dollar_price(self, product: Product, usd_price: Decimal, usd_rate: Decimal) -> Product:
        usd_price = Decimal(str(usd_price))
        usd_rate = Decimal(str(usd_rate))
        toman_price = (usd_price * usd_rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        extra = dict(product.extra_settings or {})
        extra['price_currency'] = PRICE_CURRENCY_USD
        extra['usd_price'] = str(usd_price)
        extra['usd_rate'] = str(usd_rate)
        product.extra_settings = extra
        product.price = toman_price
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def set_category(self, product: Product, category_id: str | None) -> Product:
        extra = dict(product.extra_settings or {})
        if category_id and category_id != 'uncategorized':
            extra['category_id'] = category_id
        else:
            extra.pop('category_id', None)
        product.extra_settings = extra
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def set_required_fields(self, product: Product, field_keys: list[str], prompts: dict[str, str] | None = None) -> Product:
        titles = {
            'email': 'ایمیل',
            'phone': 'شماره تلفن',
            'username': 'آیدی/نام کاربری',
            'note': 'توضیحات',
        }
        existing_prompts = {
            str(item.get('name') or item.get('type')): str(item.get('prompt') or '').strip()
            for item in (product.required_fields or [])
            if (item.get('name') or item.get('type')) and item.get('prompt')
        }
        prompts = prompts or {}
        items: list[dict[str, Any]] = []
        for key in field_keys:
            item = {'name': key, 'label': titles.get(key, key), 'type': key}
            prompt = str(prompts.get(key) or existing_prompts.get(key) or '').strip()
            if prompt and prompt != '-':
                item['prompt'] = prompt
            items.append(item)
        product.required_fields = items
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def set_required_field_prompt(self, product: Product, field_key: str, prompt: str | None) -> Product:
        field_key = str(field_key).strip()
        prompt = (prompt or '').strip()
        updated: list[dict[str, Any]] = []
        for field in (product.required_fields or []):
            item = dict(field)
            key = str(item.get('name') or item.get('type') or '').strip()
            if key == field_key:
                if prompt and prompt != '-':
                    item['prompt'] = prompt
                else:
                    item.pop('prompt', None)
            updated.append(item)
        # Do not add a required field just because its prompt was edited.
        # The admin must explicitly enable the field from "اطلاعات لازم مشتری".
        product.required_fields = updated
        await self.session.commit()
        await self.session.refresh(product)
        return product

    async def consume_stock(self, product: Product, quantity: int = 1) -> None:
        if product.stock_count is None:
            return
        quantity = max(1, int(quantity or 1))
        product.stock_count = max(0, product.stock_count - quantity)
        if product.stock_count == 0:
            product.is_active = False
        await self.session.commit()

    async def add_delivery_item(self, product: Product, payload: str, file_id: str | None = None) -> DeliveryItem:
        item = DeliveryItem(product_id=product.id, payload=payload, file_id=file_id)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        if product.delivery_kind in AUTO_DELIVERY_KINDS:
            await self.sync_auto_stock(product)
        return item

    async def add_delivery_items(self, product: Product, payloads: list[str], file_id: str | None = None) -> int:
        count = 0
        for payload in payloads:
            text = (payload or '').strip()
            if not text and not file_id:
                continue
            self.session.add(DeliveryItem(product_id=product.id, payload=text or 'فایل تحویل', file_id=file_id))
            count += 1
        if count:
            await self.session.commit()
            await self.sync_auto_stock(product)
        return count

    async def unused_delivery_count(self, product_id: int) -> int:
        result = await self.session.execute(
            select(func.count(DeliveryItem.id)).where(DeliveryItem.product_id == product_id, DeliveryItem.is_used.is_(False))
        )
        return int(result.scalar_one() or 0)

    async def list_unused_delivery_items(self, product_id: int) -> list[DeliveryItem]:
        result = await self.session.execute(
            select(DeliveryItem)
            .where(DeliveryItem.product_id == product_id, DeliveryItem.is_used.is_(False))
            .order_by(DeliveryItem.id.asc())
        )
        return list(result.scalars().all())

    async def get_unused_delivery_items(self, product_id: int, limit: int) -> list[DeliveryItem]:
        result = await self.session.execute(
            select(DeliveryItem)
            .where(DeliveryItem.product_id == product_id, DeliveryItem.is_used.is_(False))
            .order_by(DeliveryItem.id.asc())
            .limit(max(1, int(limit or 1)))
        )
        return list(result.scalars().all())

    async def delete_unused_delivery_item_by_number(self, product: Product, number: int) -> dict[str, Any] | None:
        items = await self.list_unused_delivery_items(product.id)
        if number < 1 or number > len(items):
            return None
        item = items[number - 1]
        snapshot = {'id': item.id, 'payload': item.payload, 'file_id': item.file_id}
        await self.session.delete(item)
        await self.session.commit()
        await self.sync_auto_stock(product)
        return snapshot

    async def sync_auto_stock(self, product: Product) -> None:
        if product.delivery_kind not in AUTO_DELIVERY_KINDS:
            return
        count = await self.unused_delivery_count(product.id)
        product.stock_count = count
        if count <= 0:
            product.is_active = False
        else:
            product.is_active = True
        await self.session.commit()
        await self.session.refresh(product)

    async def get_unused_delivery_item(self, product_id: int) -> DeliveryItem | None:
        # There can be many unused auto-text inventory rows for one product.
        # Fetch only the first available row; using scalar_one_or_none() here
        # crashes with "Multiple rows were found" when stock has 2+ items.
        result = await self.session.execute(
            select(DeliveryItem)
            .where(DeliveryItem.product_id == product_id, DeliveryItem.is_used.is_(False))
            .order_by(DeliveryItem.id.asc())
            .limit(1)
        )
        return result.scalars().first()
