from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin import ROLE_TITLES, admin_item_keyboard, admins_menu_keyboard, role_select_keyboard
from app.bot.states.admin import AdminManageStates
from app.config import get_settings
from app.core.permissions import MANAGE_ADMINS
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.user_service import UserService

router = Router(name='admin_admins')
settings = get_settings()


async def _guard(telegram_id: int) -> bool:
    async with SessionLocal() as session:
        return await AdminService(session).has_permission(telegram_id, MANAGE_ADMINS)


def _admin_text(admin) -> str:
    role_title = getattr(admin.role, 'title', None) or getattr(admin.role, 'slug', '—')
    return (
        f'👮‍♂️ ادمین #{admin.id}\n'
        f'آیدی تلگرام: {admin.telegram_id}\n'
        f'سطح دسترسی: {role_title}\n'
        f'وضعیت: {"فعال" if admin.is_active else "غیرفعال"}'
    )


@router.callback_query(F.data == 'admin:admins')
async def admins_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await callback.message.answer(
        '👮‍♂️ مدیریت ادمین‌ها\n\nاز این بخش می‌توانی ادمین جدید اضافه کنی و سطح دسترسی او را تعیین کنی.',
        reply_markup=admins_menu_keyboard(),
    )


@router.callback_query(F.data == 'admin:admins:add')
async def add_admin_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    await state.set_state(AdminManageStates.waiting_new_admin_identifier)
    await callback.message.answer('آیدی عددی تلگرام ادمین جدید را بفرست. اگر کاربر قبلاً ربات را استارت کرده، می‌توانی یوزرنیم او را هم بفرستی.')


@router.message(AdminManageStates.waiting_new_admin_identifier)
async def add_admin_identifier(message: Message, state: FSMContext) -> None:
    if not await _guard(message.from_user.id):
        await message.answer('دسترسی نداری.')
        await state.clear()
        return
    raw = (message.text or '').strip()
    telegram_id: int | None = int(raw) if raw.isdigit() else None
    if telegram_id is None:
        async with SessionLocal() as session:
            user = await UserService(session).find(raw)
            telegram_id = user.telegram_id if user else None
    if telegram_id is None:
        await message.answer('کاربر پیدا نشد. آیدی عددی تلگرام را بفرست یا مطمئن شو کاربر قبلاً ربات را استارت کرده باشد.')
        return
    await state.update_data(new_admin_telegram_id=telegram_id)
    await message.answer('سطح دسترسی ادمین را انتخاب کن:', reply_markup=role_select_keyboard())


@router.callback_query(F.data.startswith('admin:admins:add_role:'))
async def add_admin_role(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    role_slug = callback.data.split(':')[-1]
    data = await state.get_data()
    telegram_id = data.get('new_admin_telegram_id')
    if not telegram_id:
        await callback.message.answer('آیدی ادمین جدید پیدا نشد. دوباره از افزودن ادمین شروع کن.')
        return
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        admin = await admin_service.upsert_admin(int(telegram_id), role_slug, active=True)
        await admin_service.log(callback.from_user.id, 'upsert_admin', 'admin_user', str(admin.id), {'role': role_slug})
    await state.clear()
    await callback.message.answer(f'ادمین ذخیره شد ✅\nآیدی: {telegram_id}\nسطح دسترسی: {ROLE_TITLES.get(role_slug, role_slug)}')


@router.callback_query(F.data == 'admin:admins:list')
async def list_admins(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    async with SessionLocal() as session:
        admins = await AdminService(session).list_admins()
    await callback.message.answer(f'مالک اصلی از env: {settings.owner_telegram_id}\nادمین‌های ثبت‌شده در دیتابیس: {len(admins)}')
    if not admins:
        return
    for admin in admins:
        await callback.message.answer(_admin_text(admin), reply_markup=admin_item_keyboard(admin.id, admin.is_active))


@router.callback_query(F.data.startswith('admin:admins:toggle:'))
async def toggle_admin(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    admin_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        admin = await AdminService(session).toggle_admin(admin_id)
        if admin:
            await AdminService(session).log(callback.from_user.id, 'toggle_admin', 'admin_user', str(admin.id))
    if not admin:
        await callback.message.answer('ادمین پیدا نشد.')
        return
    await callback.message.answer('وضعیت ادمین تغییر کرد ✅\n' + _admin_text(admin), reply_markup=admin_item_keyboard(admin.id, admin.is_active))


@router.callback_query(F.data.startswith('admin:admins:change_role:'))
async def change_admin_role_prompt(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    admin_id = int(callback.data.split(':')[-1])
    await callback.message.answer('سطح دسترسی جدید را انتخاب کن:', reply_markup=role_select_keyboard(admin_id))


@router.callback_query(F.data.startswith('admin:admins:role:'))
async def change_admin_role(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback.from_user.id):
        await callback.message.answer('دسترسی نداری.')
        return
    parts = callback.data.split(':')
    admin_id = int(parts[3])
    role_slug = parts[4]
    async with SessionLocal() as session:
        admin = await AdminService(session).change_role(admin_id, role_slug)
        if admin:
            await AdminService(session).log(callback.from_user.id, 'change_admin_role', 'admin_user', str(admin.id), {'role': role_slug})
    if not admin:
        await callback.message.answer('ادمین یا نقش پیدا نشد.')
        return
    await callback.message.answer('سطح دسترسی تغییر کرد ✅\n' + _admin_text(admin), reply_markup=admin_item_keyboard(admin.id, admin.is_active))
