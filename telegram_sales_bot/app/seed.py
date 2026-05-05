from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.bootstrap import init_db
from app.config import get_settings
from app.core.permissions import ROLE_TEMPLATES
from app.db.models import AdminRole, AdminUser, Product, Setting
from app.db.session import SessionLocal
from app.services.settings_service import DEFAULT_SETTINGS

settings = get_settings()


async def seed() -> None:
    await init_db()
    async with SessionLocal() as session:
        for slug, perms in ROLE_TEMPLATES.items():
            result = await session.execute(select(AdminRole).where(AdminRole.slug == slug))
            role = result.scalar_one_or_none()
            if not role:
                session.add(
                    AdminRole(
                        slug=slug,
                        title=slug.replace('_', ' ').title(),
                        permissions=perms,
                        is_system=True,
                    )
                )
            elif role.is_system:
                role.permissions = perms

        for key, value in DEFAULT_SETTINGS.items():
            result = await session.execute(select(Setting).where(Setting.key == key))
            if not result.scalar_one_or_none():
                session.add(Setting(key=key, value=value))

        await session.commit()

        role_result = await session.execute(select(AdminRole).where(AdminRole.slug == 'owner'))
        owner_role = role_result.scalar_one()

        admin_result = await session.execute(select(AdminUser).where(AdminUser.telegram_id == settings.owner_telegram_id))
        if not admin_result.scalar_one_or_none():
            session.add(AdminUser(telegram_id=settings.owner_telegram_id, role_id=owner_role.id, is_active=True))

        demo_product = await session.execute(select(Product).where(Product.slug == 'demo-auto-text'))
        if not demo_product.scalar_one_or_none():
            session.add(
                Product(
                    title='پلن نمونه اتوتکست',
                    slug='demo-auto-text',
                    description='نمونه محصول برای تست تحویل خودکار',
                    price=10000,
                    kind='service',
                    delivery_kind='auto_text',
                    required_fields=[{'name': 'email', 'label': 'ایمیل', 'type': 'email'}],
                    stock_count=10,
                    is_active=True,
                    auto_delivery_payload={'text': 'کد نمونه: DEMO-123-456'},
                )
            )
        await session.commit()
    print('Seed completed.')


if __name__ == '__main__':
    asyncio.run(seed())
