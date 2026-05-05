from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.bootstrap import init_db
from app.db.models import AdminRole, AdminUser
from app.db.session import SessionLocal


async def main() -> None:
    if len(sys.argv) < 3:
        print('Usage: python -m app.seed_admin TELEGRAM_ID ROLE_SLUG')
        return
    telegram_id = int(sys.argv[1])
    role_slug = sys.argv[2]
    await init_db()
    async with SessionLocal() as session:
        role_result = await session.execute(select(AdminRole).where(AdminRole.slug == role_slug))
        role = role_result.scalar_one_or_none()
        if not role:
            print(f'Role not found: {role_slug}')
            return
        existing = await session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
        admin = existing.scalar_one_or_none()
        if admin:
            admin.role_id = role.id
            admin.is_active = True
        else:
            session.add(AdminUser(telegram_id=telegram_id, role_id=role.id, is_active=True))
        await session.commit()
    print('Admin saved.')


if __name__ == '__main__':
    asyncio.run(main())
