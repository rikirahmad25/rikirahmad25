from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import ALL_PERMISSIONS, ROLE_TEMPLATES
from app.db.models import AdminActivity, AdminRole, AdminUser

settings = get_settings()


class AdminService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_default_roles(self) -> None:
        changed = False
        for slug, perms in ROLE_TEMPLATES.items():
            result = await self.session.execute(select(AdminRole).where(AdminRole.slug == slug))
            role = result.scalar_one_or_none()
            if not role:
                self.session.add(AdminRole(slug=slug, title=slug.replace('_', ' ').title(), permissions=perms, is_system=True))
                changed = True
            elif role.is_system and set(role.permissions or []) != set(perms):
                role.permissions = perms
                changed = True
        if changed:
            await self.session.commit()

    async def is_admin(self, telegram_id: int) -> bool:
        if telegram_id == settings.owner_telegram_id:
            return True
        result = await self.session.execute(
            select(AdminUser)
            .where(AdminUser.telegram_id == telegram_id, AdminUser.is_active.is_(True))
            .options(selectinload(AdminUser.role))
        )
        return result.scalar_one_or_none() is not None

    async def has_permission(self, telegram_id: int, permission: str) -> bool:
        if telegram_id == settings.owner_telegram_id:
            return True
        result = await self.session.execute(
            select(AdminUser)
            .where(AdminUser.telegram_id == telegram_id, AdminUser.is_active.is_(True))
            .options(selectinload(AdminUser.role))
        )
        admin = result.scalar_one_or_none()
        if not admin:
            return False
        if not admin.role:
            return False
        perms = admin.role.permissions or []
        return permission in perms or 'owner' in perms or set(ALL_PERMISSIONS).issubset(set(perms))

    async def log(self, telegram_id: int, action: str, target_type: str | None = None, target_id: str | None = None, details: dict | None = None) -> None:
        self.session.add(
            AdminActivity(
                admin_telegram_id=telegram_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details or {},
            )
        )
        await self.session.commit()

    async def get_admin_telegram_ids(self) -> list[int]:
        result = await self.session.execute(select(AdminUser).where(AdminUser.is_active.is_(True)))
        admins = result.scalars().all()
        ids = [settings.owner_telegram_id]
        ids.extend([a.telegram_id for a in admins if a.telegram_id not in ids])
        return ids

    async def list_roles(self) -> list[AdminRole]:
        await self.ensure_default_roles()
        result = await self.session.execute(select(AdminRole).order_by(AdminRole.id.asc()))
        return result.scalars().all()

    async def get_role_by_slug(self, slug: str) -> AdminRole | None:
        await self.ensure_default_roles()
        result = await self.session.execute(select(AdminRole).where(AdminRole.slug == slug))
        return result.scalar_one_or_none()

    async def list_admins(self) -> list[AdminUser]:
        await self.ensure_default_roles()
        result = await self.session.execute(select(AdminUser).options(selectinload(AdminUser.role)).order_by(AdminUser.id.desc()))
        return result.scalars().all()

    async def get_admin(self, admin_id: int) -> AdminUser | None:
        result = await self.session.execute(select(AdminUser).where(AdminUser.id == admin_id).options(selectinload(AdminUser.role)))
        return result.scalar_one_or_none()

    async def upsert_admin(self, telegram_id: int, role_slug: str, active: bool = True) -> AdminUser:
        role = await self.get_role_by_slug(role_slug)
        if not role:
            raise ValueError('نقش پیدا نشد.')
        result = await self.session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
        admin = result.scalar_one_or_none()
        if admin:
            admin.role_id = role.id
            admin.is_active = active
        else:
            admin = AdminUser(telegram_id=telegram_id, role_id=role.id, is_active=active)
            self.session.add(admin)
        await self.session.commit()
        await self.session.refresh(admin)
        return admin

    async def change_role(self, admin_id: int, role_slug: str) -> AdminUser | None:
        role = await self.get_role_by_slug(role_slug)
        admin = await self.get_admin(admin_id)
        if not role or not admin:
            return None
        admin.role_id = role.id
        await self.session.commit()
        await self.session.refresh(admin)
        return admin

    async def toggle_admin(self, admin_id: int) -> AdminUser | None:
        admin = await self.get_admin(admin_id)
        if not admin:
            return None
        admin.is_active = not admin.is_active
        await self.session.commit()
        await self.session.refresh(admin)
        return admin
