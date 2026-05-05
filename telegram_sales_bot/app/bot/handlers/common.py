from __future__ import annotations

from sqlalchemy import select
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Contact, Message

from app.bot.filters import MenuTextFilter
from app.bot.helpers import is_user_joined, should_require_phone
from app.bot.keyboards.admin import admin_menu
from app.bot.keyboards.user import join_channels_keyboard, main_menu, phone_request_keyboard
from app.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.phone import is_valid_iran_phone, normalize_iran_phone

settings = get_settings()
router = Router(name='common')


async def _user_context(telegram_user, start_code: str | None = None):
    async with SessionLocal() as session:
        user_service = UserService(session)
        admin_service = AdminService(session)
        settings_service = SettingsService(session)
        db_user = await user_service.get_or_create(
            telegram_id=telegram_user.id,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            username=telegram_user.username,
        )
        if start_code and not db_user.referred_by_user_id:
            result = await session.execute(select(User).where(User.referral_code == start_code))
            referrer = result.scalar_one_or_none()
            if referrer:
                await user_service.set_referrer(db_user, referrer)
        texts = await settings_service.get('texts')
        menu_labels = await settings_service.get('menu')
        features = await settings_service.get('features')
        channels_cfg = await settings_service.get('channels')
        channels = channels_cfg.get('required_channels') or [] if channels_cfg.get('enabled') else []
        is_admin = await admin_service.is_admin(telegram_user.id)
    need_phone = await should_require_phone(db_user)
    return db_user, texts, menu_labels, features, channels, is_admin, need_phone




async def _maybe_notify_new_user(bot, db_user: User) -> None:
    meta = dict(db_user.metadata_json or {})
    if meta.get('new_user_notified') is not False:
        return
    async with SessionLocal() as session:
        user = await UserService(session).get_by_telegram_id(db_user.telegram_id)
        if not user:
            return
        notifications = await SettingsService(session).get('notifications')
        if not notifications.get('new_user_enabled', True):
            user.metadata_json = {**(user.metadata_json or {}), 'new_user_notified': True}
            await session.commit()
            return
        texts = await SettingsService(session).get('texts')
        referrer_text = '—'
        if user.referred_by_user_id:
            referrer = await session.get(User, user.referred_by_user_id)
            if referrer:
                referrer_text = f'{referrer.first_name or "—"} (@{referrer.username or "—"}) | {referrer.telegram_id}'
        name = ' '.join(part for part in [user.first_name, user.last_name] if part) or '—'
        text = (texts.get('new_user_admin_notification') or 'کاربر جدید: {telegram_id}').format(
            name=name,
            username=f'@{user.username}' if user.username else '—',
            telegram_id=user.telegram_id,
            referrer=referrer_text,
        )
        user.metadata_json = {**(user.metadata_json or {}), 'new_user_notified': True}
        await session.commit()
        await NotificationService(session).notify_admins(bot, text)

async def _send_home(message: Message, start_code: str | None = None) -> None:
    _db_user, texts, menu_labels, features, channels, is_admin, need_phone = await _user_context(message.from_user, start_code)
    if _db_user.is_blocked:
        await message.answer(texts.get('blocked_message') or 'دسترسی شما مسدود شده است.')
        return
    await _maybe_notify_new_user(message.bot, _db_user)
    if channels and not await is_user_joined(message.bot, message.from_user.id):
        await message.answer(texts.get('force_join_message', 'برای استفاده از ربات باید اول عضو شوی.'), reply_markup=join_channels_keyboard(channels))
        return
    if need_phone:
        await message.answer(texts.get('force_phone_message', 'شماره تلفن را ارسال کن.'), reply_markup=phone_request_keyboard(menu_labels))
        return
    await message.answer(texts.get('welcome', 'خوش آمدی'), reply_markup=main_menu(is_admin=is_admin, labels=menu_labels, features=features))


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    start_args = (message.text or '').split(maxsplit=1)
    start_code = start_args[1].strip() if len(start_args) > 1 else None
    await _send_home(message, start_code)


@router.callback_query(F.data == 'check_join')
async def check_join_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    _db_user, texts, menu_labels, features, channels, is_admin, need_phone = await _user_context(callback.from_user)
    if channels and not await is_user_joined(callback.bot, callback.from_user.id):
        await callback.message.answer(texts.get('force_join_failed', 'هنوز عضویت کامل نیست.'), reply_markup=join_channels_keyboard(channels))
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(texts.get('force_join_success', 'عضویت تایید شد ✅'))
    if need_phone:
        await callback.message.answer(texts.get('force_phone_message', 'شماره تلفن را ارسال کن.'), reply_markup=phone_request_keyboard(menu_labels))
        return
    await callback.message.answer(texts.get('welcome', 'خوش آمدی'), reply_markup=main_menu(is_admin=is_admin, labels=menu_labels, features=features))


@router.callback_query(F.data == 'noop:join_link_missing')
async def join_link_missing(callback: CallbackQuery) -> None:
    await callback.answer('برای این مورد لینک عمومی ثبت نشده است.', show_alert=True)


@router.message(F.contact)
async def phone_contact_handler(message: Message) -> None:
    contact: Contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer('لطفاً فقط شماره خودت را ارسال کن.')
        return
    normalized = normalize_iran_phone(contact.phone_number)
    if settings.only_ir_phone and not is_valid_iran_phone(normalized):
        await message.answer('فقط شماره موبایل ایران قابل قبول است.')
        return
    async with SessionLocal() as session:
        user_service = UserService(session)
        settings_service = SettingsService(session)
        db_user = await user_service.get_or_create(message.from_user.id, message.from_user.first_name, message.from_user.last_name, message.from_user.username)
        texts = await settings_service.get('texts')
        if db_user.is_blocked:
            await message.answer(texts.get('blocked_message') or 'دسترسی شما مسدود شده است.')
            return
        db_user.phone_number = normalized
        db_user.is_phone_verified = True
        await session.commit()
    await message.answer(texts.get('force_phone_success', 'شماره شما تایید شد ✅'))
    await _send_home(message)


@router.message(MenuTextFilter('admin_panel', '⚙️ پنل ادمین'))
async def admin_panel_message(message: Message) -> None:
    async with SessionLocal() as session:
        admin_service = AdminService(session)
        if not await admin_service.is_admin(message.from_user.id):
            await message.answer('دسترسی نداری.')
            return
    await message.answer('پنل ادمین', reply_markup=admin_menu())
