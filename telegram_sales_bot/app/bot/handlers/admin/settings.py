from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin import (
    admin_menu,
    anti_spam_settings_keyboard,
    backup_settings_keyboard,
    card_settings_keyboard,
    channels_settings_keyboard,
    crypto_manual_settings_keyboard,
    discount_code_keyboard,
    discount_max_uses_keyboard,
    discount_min_amount_keyboard,
    discount_per_user_limit_keyboard,
    discount_type_keyboard,
    discounts_settings_keyboard,
    menu_settings_keyboard,
    notification_settings_keyboard,
    payment_settings_keyboard,
    phone_settings_keyboard,
    plisio_settings_keyboard,
    referral_settings_keyboard,
    settings_main_keyboard,
    support_settings_keyboard,
    texts_settings_keyboard,
    tutorial_manage_keyboard,
    tutorial_type_keyboard,
    tutorials_admin_keyboard,
    zarinpal_settings_keyboard,
)
from app.bot.states.admin import AdminDiscountStates, AdminSettingsStates, AdminTutorialStates
from app.core.permissions import MANAGE_SETTINGS
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.backup_service import BackupService
from app.services.crypto_rate_service import SUPPORTED_CRYPTO_SYMBOLS, crypto_display_name, normalize_crypto_symbol
from app.services.discount_service import DiscountService
from app.services.settings_service import DEFAULT_SETTINGS, SettingsService
from app.services.tutorial_service import TutorialService
from app.utils.text import money

router = Router(name='admin_settings')

TEXT_KEYS = [
    ('welcome', 'خوشامدگویی'),
    ('products_title', 'عنوان لیست محصولات'),
    ('no_products', 'متن نبود محصول'),
    ('choose_payment_method', 'متن انتخاب پرداخت'),
    ('discount_prompt', 'دعوت به کد تخفیف'),
    ('discount_ask_code', 'درخواست کد تخفیف'),
    ('discount_applied', 'متن تخفیف موفق'),
    ('discount_invalid', 'متن تخفیف نامعتبر'),
    ('receipt_received', 'متن ثبت رسید'),
    ('payment_approved', 'متن تایید پرداخت'),
    ('payment_rejected', 'متن رد پرداخت'),
    ('payment_error', 'خطای پرداخت'),
    ('order_completed', 'متن تکمیل سفارش'),
    ('support_text', 'متن پشتیبانی'),
    ('support_button', 'دکمه پشتیبانی'),
    ('force_join_message', 'متن عضویت اجباری'),
    ('force_join_success', 'متن تایید عضویت'),
    ('force_join_failed', 'متن عضویت ناقص'),
    ('force_phone_message', 'متن اجبار شماره'),
    ('force_phone_success', 'متن تایید شماره'),
    ('request_email', 'درخواست ایمیل'),
    ('request_phone', 'درخواست شماره تلفن'),
    ('request_username', 'درخواست آیدی'),
    ('request_note', 'درخواست توضیحات'),
    ('tutorials_title', 'عنوان آموزش‌ها'),
    ('no_tutorials', 'نبود آموزش'),
    ('wallet_charge_ask_amount', 'درخواست مبلغ شارژ کیف پول'),
    ('wallet_charge_receipt_received', 'ثبت رسید شارژ کیف پول'),
    ('wallet_charge_paid', 'تایید شارژ کیف پول'),
    ('wallet_charge_rejected', 'رد شارژ کیف پول'),
    ('plisio_pay_message', 'متن پرداخت Plisio'),
    ('crypto_manual_pay_message', 'متن پرداخت رمزارز دستی'),
    ('blocked_message', 'متن کاربر مسدود'),
    ('new_user_admin_notification', 'اعلان ورود کاربر جدید'),
    ('user_blocked_bot_admin_notification', 'اعلان بلاک/حذف ربات'),
    ('referral_commission_received', 'اعلان پورسانت زیرمجموعه'),
    ('manual_wallet_charge', 'متن شارژ دستی کیف پول'),
    ('lottery_win', 'متن برنده قرعه‌کشی'),
]

MENU_KEYS = [
    ('products', 'دکمه محصولات'),
    ('tutorials', 'دکمه آموزش‌ها'),
    ('orders', 'دکمه سفارش‌های من'),
    ('support', 'دکمه پشتیبانی'),
    ('wallet', 'دکمه کیف پول'),
    ('referral', 'دکمه زیرمجموعه‌گیری'),
    ('admin_panel', 'دکمه پنل ادمین'),
    ('send_phone', 'دکمه ارسال شماره'),
]

NUMERIC_FIELDS = {
    'anti_spam': {'max_messages', 'window_seconds', 'block_seconds'},
    'referral': {'percent', 'fixed_amount', 'min_order_amount', 'max_commission'},
    'backup': {'interval_hours'},
    'plisio': {'source_rate', 'expire_min'},
}


def _yes_no(value: Any) -> str:
    return '✅ فعال' if value else '❌ غیرفعال'


def _parse_channels(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace('\n', ',').split(',') if part.strip()]


def _allowed_crypto_text() -> str:
    return 'TRX/ترون، USDT/تتر، TON/تون کوین'


def _parse_crypto_wallet(raw: str) -> dict[str, Any] | None:
    text = (raw or '').strip()
    if not text:
        return None
    # فرمت پیشنهادی: ارز | شبکه | آدرس | توضیح اختیاری
    if '|' in text:
        parts = [part.strip() for part in text.split('|')]
    else:
        parts = [part.strip() for part in text.splitlines() if part.strip()]
    if len(parts) < 3:
        return None
    symbol = normalize_crypto_symbol(parts[0])
    if symbol not in SUPPORTED_CRYPTO_SYMBOLS:
        return None
    return {
        'coin': crypto_display_name(symbol),
        'coin_symbol': symbol,
        'network': parts[1],
        'address': parts[2],
        'note': parts[3] if len(parts) > 3 else '',
        'is_active': True,
    }


def _wallets_summary(wallets: list[dict]) -> str:
    if not wallets:
        return 'هیچ آدرس ولتی ثبت نشده است.'
    lines: list[str] = []
    for idx, wallet in enumerate(wallets, 1):
        status = 'فعال' if wallet.get('is_active', True) else 'غیرفعال'
        symbol = normalize_crypto_symbol(wallet.get('coin_symbol') or wallet.get('coin'))
        coin = crypto_display_name(symbol) if symbol else (wallet.get('coin') or '—')
        lines.append(
            f'{idx}. #{wallet.get("id")} | {coin} | شبکه: {wallet.get("network") or "—"} | {status}\n'
            f'آدرس: {wallet.get("address") or "—"}'
        )
        if wallet.get('note'):
            lines.append(f'توضیح: {wallet.get("note")}')
    return '\n\n'.join(lines)


REFERRAL_TEXT_VARIABLES: list[tuple[str, str]] = [
    ('{referral_link}', 'لینک دعوت کامل کاربر'),
    ('{link}', 'همان لینک دعوت'),
    ('{referral_code}', 'کد دعوت کاربر'),
    ('{bot_username}', 'یوزرنیم ربات'),
    ('{reward_line}', 'خط آماده پاداش؛ درصدی یا مبلغ ثابت'),
    ('{percent}', 'درصد پورسانت'),
    ('{fixed_amount}', 'مبلغ ثابت پاداش با فرمت تومان'),
    ('{wallet_balance}', 'موجودی کیف پول/پورسانت کاربر'),
    ('{balance}', 'همان موجودی کیف پول/پورسانت'),
    ('{min_order_amount}', 'حداقل مبلغ سفارش برای پورسانت'),
    ('{max_commission}', 'سقف پورسانت'),
    ('{reward_type}', 'نوع پاداش: percent یا fixed'),
    ('{basis}', 'مبنای محاسبه: paid_amount یا original_amount'),
]


def _referral_text_help(current_text: str | None = None) -> str:
    default_text = str((DEFAULT_SETTINGS.get('referral') or {}).get('message_text') or '')
    lines = [
        'متن زیرمجموعه‌گیری را بفرست.',
        '',
        'داده خام متن پیش‌فرض:',
        default_text,
        '',
        'متغیرهای قابل استفاده:',
    ]
    lines.extend(f'{var} = {desc}' for var, desc in REFERRAL_TEXT_VARIABLES)
    if current_text and current_text != default_text:
        lines.extend(['', 'متن فعلی:', str(current_text)])
    return '\n'.join(lines)


def _tutorial_type_label(item: object) -> str:
    meta = getattr(item, 'metadata_json', None) or {}
    content_type = meta.get('content_type') or ('video' if getattr(item, 'video_file_id', '') else 'text')
    labels = {
        'text': 'متنی',
        'photo': 'عکسی',
        'photo_text': 'عکس با کپشن',
        'video': 'ویدیویی',
    }
    return labels.get(str(content_type), str(content_type))


async def _guard(callback: CallbackQuery) -> bool:
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(callback.from_user.id, MANAGE_SETTINGS):
            await callback.message.answer('دسترسی نداری.')
            return False
    return True


async def _guard_message(message: Message) -> bool:
    async with SessionLocal() as session:
        if not await AdminService(session).has_permission(message.from_user.id, MANAGE_SETTINGS):
            await message.answer('دسترسی نداری.')
            return False
    return True


async def _show_main(callback: CallbackQuery) -> None:
    async with SessionLocal() as session:
        service = SettingsService(session)
        features = await service.get('features')
        payments = await service.get('payments')
        channels = await service.get('channels')
        phone = await service.get('phone_verification')
        discounts = await service.get('discounts')
        backup = await service.get('backup')
        support = await service.get('support')
        notifications = await service.get('notifications')
    text = (
        '⚙️ تنظیمات ربات\n\n'
        f'فروش: {_yes_no(features.get("sales_enabled"))}\n'
        f'آموزش‌ها: {_yes_no(features.get("tutorials_enabled"))}\n'
        f'روش‌های پرداخت فعال: {", ".join(payments.get("enabled_methods") or [])}\n'
        f'عضویت اجباری: {_yes_no(channels.get("enabled"))}\n'
        f'شماره تلفن اجباری: {_yes_no(phone.get("enabled"))}\n'
        f'کد تخفیف: {_yes_no(discounts.get("enabled"))}\n'
        f'بکاپ خودکار: {_yes_no(backup.get("enabled"))}\n'
        f'پشتیبانی: {support.get("support_username") or "ثبت نشده"}\n'
        f'اعلان ورود کاربر: {_yes_no(notifications.get("new_user_enabled", True))}\n\n'
        'از گزینه‌های زیر هر بخش را مدیریت کن.'
    )
    await callback.message.answer(text, reply_markup=settings_main_keyboard())


@router.callback_query(F.data == 'admin:settings')
async def admin_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if not await _guard(callback):
        return
    await _show_main(callback)


@router.callback_query(F.data == 'admin:back:main')
async def back_to_admin(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    await callback.message.answer('پنل ادمین', reply_markup=admin_menu())


@router.callback_query(F.data == 'admin:set:payments')
async def payment_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        payments = await SettingsService(session).get('payments')
    enabled = payments.get('enabled_methods') or []
    await callback.message.answer(
        '💳 تنظیمات پرداخت\n\n'
        f'فعال‌ها: {", ".join(enabled) or "—"}\n'
        f'پیش‌فرض: {payments.get("default_method")}\n'
        'برای فعال/غیرفعال‌سازی هر روش روی آن بزن.',
        reply_markup=payment_settings_keyboard(enabled),
    )


@router.callback_query(F.data.startswith('admin:set:payments:toggle:'))
async def toggle_payment_method(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    method = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        service = SettingsService(session)
        payments = await service.get('payments')
        enabled = list(payments.get('enabled_methods') or [])
        if method in enabled:
            enabled.remove(method)
        else:
            enabled.append(method)
        if not enabled:
            enabled = ['card_to_card']
        payments['enabled_methods'] = enabled
        if payments.get('default_method') not in enabled:
            payments['default_method'] = enabled[0]
        await service.set('payments', payments)
    await callback.message.answer('تنظیمات پرداخت ذخیره شد ✅', reply_markup=payment_settings_keyboard(enabled))


async def _show_card(callback: CallbackQuery) -> None:
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('card_to_card')
    await callback.message.answer(
        '🏦 کارت‌به‌کارت\n\n'
        f'شماره کارت: {cfg.get("card_number") or "—"}\n'
        f'صاحب کارت: {cfg.get("card_holder") or "—"}\n'
        f'بانک: {cfg.get("bank") or "—"}\n\n'
        'برای ویرایش، گزینه را انتخاب کن.',
        reply_markup=card_settings_keyboard(),
    )


@router.callback_query(F.data == 'admin:set:card')
async def card_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if await _guard(callback):
        await _show_card(callback)


@router.callback_query(F.data.startswith('admin:set:card:edit:'))
async def edit_card(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='card_to_card', field=key, after='admin:set:card')
    await callback.message.answer('مقدار جدید را بفرست:')


@router.callback_query(F.data == 'admin:set:zarinpal')
async def zarinpal_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('zarinpal')
    await callback.message.answer(
        '🌐 تنظیمات زرین‌پال\n\n'
        f'Merchant ID: {cfg.get("merchant_id") or "—"}\n'
        f'Callback: {cfg.get("callback_url") or "—"}',
        reply_markup=zarinpal_settings_keyboard(),
    )


@router.callback_query(F.data.startswith('admin:set:zarinpal:edit:'))
async def edit_zarinpal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='zarinpal', field=key, after='admin:set:zarinpal')
    await callback.message.answer('مقدار جدید را بفرست:')


@router.callback_query(F.data == 'admin:set:plisio')
async def plisio_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('plisio')
    await callback.message.answer(
        '🪙 تنظیمات Plisio\n\n'
        f'API Key: {"ثبت شده" if cfg.get("api_key") else "—"}\n'
        f'عنوان دکمه برای مشتری: {cfg.get("display_label") or "🪙 پرداخت کریپتویی آنلاین"}\n'
        f'ارز مبدا: {cfg.get("source_currency") or "USD"}\n'
        f'نرخ دستی تومان به USD: {cfg.get("source_rate")}\n'
        f'دریافت خودکار نرخ USDT از نوبیتکس: {_yes_no(cfg.get("auto_usdt_rate_enabled", False))}\n'
        f'استفاده از نرخ دستی هنگام خطای نوبیتکس: {_yes_no(cfg.get("fallback_to_manual_rate_enabled", False))}\n'
        f'نمایش نرخ تبدیل به مشتری: {_yes_no(cfg.get("show_source_rate", False))}\n'
        f'ارز پیش‌فرض: {cfg.get("currency")}\n'
        f'ارزهای مجاز: {cfg.get("allowed_psys_cids")}\n'
        f'Callback: {cfg.get("callback_url") or "—"}\n'
        f'انقضا: {cfg.get("expire_min")} دقیقه\n'
        f'تایید امضا: {_yes_no(cfg.get("verify_callback", True))}',
        reply_markup=plisio_settings_keyboard(cfg),
    )


@router.callback_query(F.data.startswith('admin:set:plisio:edit:'))
async def edit_plisio(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='plisio', field=key, after='admin:set:plisio')
    prompts = {
        'display_label': 'عنوان دکمه‌ای که مشتری موقع انتخاب روش پرداخت می‌بیند را بفرست:',
        'source_rate': 'نرخ دستی هر ۱ USD/USDT به تومان را بفرست. وقتی حالت خودکار خاموش باشد یا گزینه «نرخ دستی هنگام خطای نوبیتکس» روشن باشد، از همین نرخ استفاده می‌شود:',
        'source_currency': 'ارز مبدا فیات را بفرست. برای حالت خودکار نوبیتکس بهتر است USD باشد:',
    }
    await callback.message.answer(prompts.get(key, 'مقدار جدید را بفرست:'))


@router.callback_query(F.data == 'admin:set:plisio:toggle_auto_usdt_rate')
async def toggle_plisio_auto_usdt_rate(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('plisio')
        cfg['auto_usdt_rate_enabled'] = not bool(cfg.get('auto_usdt_rate_enabled', False))
        await service.set('plisio', cfg)
        await AdminService(session).log(callback.from_user.id, 'toggle_plisio_auto_usdt_rate', 'setting', 'plisio', {'auto_usdt_rate_enabled': cfg['auto_usdt_rate_enabled']})
    status = 'فعال شد' if cfg.get('auto_usdt_rate_enabled') else 'غیرفعال شد'
    await callback.message.answer(f'دریافت خودکار نرخ USDT از نوبیتکس برای Plisio {status} ✅', reply_markup=plisio_settings_keyboard(cfg))


@router.callback_query(F.data == 'admin:set:plisio:toggle_fallback_manual_rate')
async def toggle_plisio_fallback_manual_rate(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('plisio')
        cfg['fallback_to_manual_rate_enabled'] = not bool(cfg.get('fallback_to_manual_rate_enabled', False))
        await service.set('plisio', cfg)
        await AdminService(session).log(callback.from_user.id, 'toggle_plisio_fallback_manual_rate', 'setting', 'plisio', {'fallback_to_manual_rate_enabled': cfg['fallback_to_manual_rate_enabled']})
    status = 'فعال شد' if cfg.get('fallback_to_manual_rate_enabled') else 'غیرفعال شد'
    await callback.message.answer(f'استفاده از نرخ دستی هنگام خطای نوبیتکس برای Plisio {status} ✅', reply_markup=plisio_settings_keyboard(cfg))


@router.callback_query(F.data == 'admin:set:plisio:toggle_show_source_rate')
async def toggle_plisio_show_source_rate(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('plisio')
        cfg['show_source_rate'] = not bool(cfg.get('show_source_rate', False))
        await service.set('plisio', cfg)
        await AdminService(session).log(callback.from_user.id, 'toggle_plisio_show_source_rate', 'setting', 'plisio', {'show_source_rate': cfg['show_source_rate']})
    status = 'فعال شد' if cfg.get('show_source_rate') else 'غیرفعال شد'
    await callback.message.answer(f'نمایش نرخ تبدیل Plisio به مشتری {status} ✅', reply_markup=plisio_settings_keyboard(cfg))


@router.callback_query(F.data == 'admin:set:plisio:toggle_verify')
async def toggle_plisio_verify(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('plisio')
        cfg['verify_callback'] = not bool(cfg.get('verify_callback', True))
        await service.set('plisio', cfg)
    await callback.message.answer('تنظیمات Plisio ذخیره شد ✅')


@router.callback_query(F.data == 'admin:set:crypto_manual')
async def crypto_manual_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('crypto_manual')
        payments = await SettingsService(session).get('payments')
    enabled = 'crypto_manual' in (payments.get('enabled_methods') or [])
    wallets = list(cfg.get('wallets') or [])
    await callback.message.answer(
        '🪙 پرداخت رمزارز دستی\n\n'
        f'وضعیت روش پرداخت در بخش پرداخت‌ها: {_yes_no(enabled)}\n'
        'برای فعال/غیرفعال کردن خود روش پرداخت، از مسیر «تنظیمات > پرداخت‌ها» گزینه پرداخت رمزارز دستی را روشن کن.\n'
        'تبدیل قیمت تومان به رمزارز با API عمومی نوبیتکس انجام می‌شود.\n'
        f'ارزهای مجاز: {_allowed_crypto_text()}\n'
        f'عنوان دکمه برای مشتری: {cfg.get("display_label") or "🪙 پرداخت با رمز ارز"}\n'
        f'نمایش قیمت هر واحد ارز به مشتری: {_yes_no(cfg.get("show_unit_price", False))}\n\n'
        f'متن راهنما: {cfg.get("instructions") or "—"}\n\n'
        f'آدرس‌های ثبت‌شده:\n{_wallets_summary(wallets)}',
        reply_markup=crypto_manual_settings_keyboard(wallets, cfg),
    )


@router.callback_query(F.data == 'admin:set:crypto_manual:add')
async def crypto_manual_add_wallet(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    await state.set_state(AdminSettingsStates.waiting_crypto_wallet)
    await callback.message.answer(
        'آدرس ولت را با این فرمت بفرست:\n\n'
        'نام ارز | شبکه | آدرس ولت | توضیح اختیاری\n\n'
        f'نام ارز فقط یکی از این‌ها باشد: {_allowed_crypto_text()}\n\n'
        'مثال‌ها:\nUSDT | TRC20 | TXxxxxxxxxxxxx | حداقل واریز ۱۰ دلار\nTRX | TRC20 | TXxxxxxxxxxxxx\nTON | TON | UQxxxxxxxxxxxx'
    )


@router.message(AdminSettingsStates.waiting_crypto_wallet)
async def crypto_manual_save_wallet(message: Message, state: FSMContext) -> None:
    if not await _guard_message(message):
        await state.clear()
        return
    wallet = _parse_crypto_wallet(message.text or '')
    if not wallet:
        await message.answer(f'فرمت معتبر نیست یا نام ارز مجاز نیست. نمونه: USDT | TRC20 | آدرس ولت | توضیح اختیاری\nارزهای مجاز: {_allowed_crypto_text()}')
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('crypto_manual')
        wallets = list(cfg.get('wallets') or [])
        next_id = int(cfg.get('next_id') or 1)
        wallet['id'] = next_id
        wallets.append(wallet)
        cfg['wallets'] = wallets
        cfg['next_id'] = next_id + 1
        await service.set('crypto_manual', cfg)
        await AdminService(session).log(message.from_user.id, 'add_crypto_wallet', 'setting', 'crypto_manual', {'wallet_id': next_id})
    await state.clear()
    await message.answer('آدرس ولت ذخیره شد ✅')


@router.callback_query(F.data == 'admin:set:crypto_manual:toggle_show_unit_price')
async def crypto_manual_toggle_show_unit_price(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('crypto_manual')
        cfg['show_unit_price'] = not bool(cfg.get('show_unit_price', False))
        wallets = list(cfg.get('wallets') or [])
        await service.set('crypto_manual', cfg)
        await AdminService(session).log(
            callback.from_user.id,
            'toggle_crypto_unit_price',
            'setting',
            'crypto_manual',
            {'show_unit_price': cfg['show_unit_price']},
        )
    status = 'فعال شد' if cfg.get('show_unit_price') else 'غیرفعال شد'
    await callback.message.answer(f'نمایش قیمت یک واحد ارز به مشتری {status} ✅', reply_markup=crypto_manual_settings_keyboard(wallets, cfg))


@router.callback_query(F.data.startswith('admin:set:crypto_manual:toggle:'))
async def crypto_manual_toggle_wallet(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    wallet_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('crypto_manual')
        wallets = list(cfg.get('wallets') or [])
        found = False
        for wallet in wallets:
            if int(wallet.get('id') or 0) == wallet_id:
                wallet['is_active'] = not bool(wallet.get('is_active', True))
                found = True
                break
        cfg['wallets'] = wallets
        await service.set('crypto_manual', cfg)
        await AdminService(session).log(callback.from_user.id, 'toggle_crypto_wallet', 'setting', 'crypto_manual', {'wallet_id': wallet_id})
    await callback.message.answer('وضعیت آدرس ولت تغییر کرد ✅' if found else 'آدرس ولت پیدا نشد.', reply_markup=crypto_manual_settings_keyboard(wallets, cfg))


@router.callback_query(F.data.startswith('admin:set:crypto_manual:delete:'))
async def crypto_manual_delete_wallet(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    wallet_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('crypto_manual')
        old_wallets = list(cfg.get('wallets') or [])
        wallets = [wallet for wallet in old_wallets if int(wallet.get('id') or 0) != wallet_id]
        cfg['wallets'] = wallets
        await service.set('crypto_manual', cfg)
        await AdminService(session).log(callback.from_user.id, 'delete_crypto_wallet', 'setting', 'crypto_manual', {'wallet_id': wallet_id})
    await callback.message.answer('آدرس ولت حذف شد ✅' if len(wallets) != len(old_wallets) else 'آدرس ولت پیدا نشد.', reply_markup=crypto_manual_settings_keyboard(wallets, cfg))


@router.callback_query(F.data.startswith('admin:set:crypto_manual:edit:'))
async def crypto_manual_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    field = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='crypto_manual', field=field, after='admin:set:crypto_manual')
    if field == 'display_label':
        await callback.message.answer('عنوان دکمه پرداخت دستی رمزارز که مشتری موقع انتخاب روش پرداخت می‌بیند را بفرست:')
    else:
        await callback.message.answer('متن راهنمای پرداخت رمزارز را بفرست. این متن بالای آدرس‌ها به مشتری نمایش داده می‌شود:')


@router.callback_query(F.data == 'admin:set:channels')
async def channels_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('channels')
    await callback.message.answer(
        '📢 عضویت اجباری\n\n'
        f'وضعیت: {_yes_no(cfg.get("enabled"))}\n'
        f'کانال/گروه‌ها:\n' + ('\n'.join(cfg.get('required_channels') or []) or '—'),
        reply_markup=channels_settings_keyboard(bool(cfg.get('enabled'))),
    )


@router.callback_query(F.data == 'admin:set:channels:toggle')
async def toggle_channels(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('channels')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('channels', cfg)
    await callback.message.answer('تنظیمات عضویت اجباری ذخیره شد ✅')


@router.callback_query(F.data == 'admin:set:channels:edit')
async def edit_channels(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='channels', field='required_channels', parser='channels', after='admin:set:channels')
    await callback.message.answer('لیست کانال/گروه‌ها را با کاما یا هرکدام در یک خط بفرست. مثال: @channel یا https://t.me/channel')


@router.callback_query(F.data == 'admin:set:phone')
async def phone_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('phone_verification')
    await callback.message.answer(f'📱 اجبار ارسال شماره تلفن: {_yes_no(cfg.get("enabled"))}', reply_markup=phone_settings_keyboard(bool(cfg.get('enabled'))))


@router.callback_query(F.data == 'admin:set:phone:toggle')
async def toggle_phone(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('phone_verification')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('phone_verification', cfg)
    await callback.message.answer('تنظیمات شماره تلفن اجباری ذخیره شد ✅')


@router.callback_query(F.data == 'admin:set:support')
async def support_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('support')
    await callback.message.answer(f'☎️ آیدی پشتیبانی فعلی: {cfg.get("support_username") or "—"}', reply_markup=support_settings_keyboard())


@router.callback_query(F.data.startswith('admin:set:support:edit:'))
async def edit_support(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='support', field=key, after='admin:set:support')
    await callback.message.answer('آیدی پشتیبانی را بفرست. مثال: @support یا https://t.me/support')


@router.callback_query(F.data == 'admin:set:tutorials')
async def tutorials_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        tutorials = await TutorialService(session).list_all()
    await callback.message.answer('🎓 مدیریت آموزش‌ها؛ می‌توانی آموزش متنی، عکسی، عکس با کپشن یا ویدیویی اضافه کنی:', reply_markup=tutorials_admin_keyboard(tutorials))


@router.callback_query(F.data == 'admin:tutorial:add')
async def tutorial_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminTutorialStates.waiting_title)
    await callback.message.answer('عنوان آموزش را بفرست:')


@router.message(AdminTutorialStates.waiting_title)
async def tutorial_title(message: Message, state: FSMContext) -> None:
    title = (message.text or '').strip()
    if not title:
        await message.answer('عنوان نمی‌تواند خالی باشد. عنوان آموزش را بفرست:')
        return
    await state.update_data(title=title)
    await state.set_state(AdminTutorialStates.waiting_type)
    await message.answer('نوع آموزش را انتخاب کن:', reply_markup=tutorial_type_keyboard())


@router.callback_query(F.data.startswith('admin:tutorial:type:'))
async def tutorial_type(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state != AdminTutorialStates.waiting_type.state:
        await callback.answer()
        return
    await callback.answer()
    content_type = callback.data.split(':')[-1]
    if content_type not in {'text', 'photo', 'photo_text', 'video'}:
        await callback.message.answer('نوع آموزش معتبر نیست.')
        return
    await state.update_data(content_type=content_type)
    await state.set_state(AdminTutorialStates.waiting_content)
    if content_type == 'text':
        await callback.message.answer('متن آموزش را بفرست:')
    elif content_type == 'photo':
        await callback.message.answer('عکس آموزش را ارسال کن. این حالت بدون کپشن برای مشتری نمایش داده می‌شود.')
    elif content_type == 'photo_text':
        await callback.message.answer('عکس آموزش را همراه کپشن بفرست. کپشن همان متن آموزشی مشتری خواهد بود.')
    else:
        await callback.message.answer('ویدیوی آموزش را ارسال کن. اگر کپشن هم بگذاری، همان کپشن زیر ویدیو برای مشتری نمایش داده می‌شود.')


@router.message(AdminTutorialStates.waiting_content)
async def tutorial_content(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    content_type = data.get('content_type')
    title = data.get('title') or 'آموزش'

    if content_type == 'text':
        text_content = (message.text or '').strip()
        if not text_content:
            await message.answer('برای آموزش متنی، متن آموزش را ارسال کن.')
            return
        create_kwargs = {
            'title': title,
            'description': text_content,
            'content_type': 'text',
            'text_content': text_content,
        }
    elif content_type == 'photo':
        if not message.photo:
            await message.answer('برای آموزش عکسی، لطفاً عکس ارسال کن.')
            return
        create_kwargs = {
            'title': title,
            'description': None,
            'content_type': 'photo',
            'photo_file_id': message.photo[-1].file_id,
        }
    elif content_type == 'photo_text':
        if not message.photo:
            await message.answer('برای عکس با کپشن، لطفاً عکس را همراه کپشن ارسال کن.')
            return
        caption = (message.caption or '').strip()
        if not caption:
            await message.answer('این نوع آموزش به کپشن نیاز دارد. عکس را همراه متن کپشن ارسال کن.')
            return
        create_kwargs = {
            'title': title,
            'description': caption,
            'content_type': 'photo_text',
            'text_content': caption,
            'photo_file_id': message.photo[-1].file_id,
        }
    elif content_type == 'video':
        if not message.video:
            await message.answer('برای آموزش ویدیویی، لطفاً فایل ویدیو را به صورت ویدیو ارسال کن.')
            return
        caption = (message.caption or '').strip()
        create_kwargs = {
            'title': title,
            'description': caption or title,
            'content_type': 'video',
            'text_content': caption or title,
            'video_file_id': message.video.file_id,
        }
    else:
        await state.clear()
        await message.answer('نوع آموزش مشخص نبود. دوباره از افزودن آموزش شروع کن.')
        return

    async with SessionLocal() as session:
        item = await TutorialService(session).create(**create_kwargs)
        await AdminService(session).log(message.from_user.id, 'create_tutorial', 'tutorial', str(item.id), {'content_type': content_type})
    await state.clear()
    await message.answer(f'آموزش #{item.id} ثبت شد ✅')


@router.callback_query(F.data.startswith('admin:tutorial:manage:'))
async def tutorial_manage(callback: CallbackQuery) -> None:
    await callback.answer()
    tutorial_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        item = await TutorialService(session).get(tutorial_id)
    if not item:
        await callback.message.answer('آموزش پیدا نشد.')
        return
    await callback.message.answer(
        f'🎓 #{item.id} {item.title}\n'
        f'نوع: {_tutorial_type_label(item)}\n'
        f'وضعیت: {_yes_no(item.is_active)}',
        reply_markup=tutorial_manage_keyboard(item.id, item.is_active),
    )


@router.callback_query(F.data.startswith('admin:tutorial:toggle:'))
async def tutorial_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    tutorial_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        item = await TutorialService(session).get(tutorial_id)
        if item:
            await TutorialService(session).toggle(item)
    await callback.message.answer('وضعیت آموزش تغییر کرد ✅')


@router.callback_query(F.data.startswith('admin:tutorial:delete:'))
async def tutorial_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    tutorial_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        item = await TutorialService(session).get(tutorial_id)
        if item:
            await TutorialService(session).delete(item)
    await callback.message.answer('آموزش حذف شد ✅')


@router.callback_query(F.data == 'admin:set:notifications')
async def notifications_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('notifications')
    await callback.message.answer(
        '🔔 تنظیمات اعلان‌ها\n\n'
        f'ورود کاربر جدید: {_yes_no(cfg.get("new_user_enabled", True))}\n'
        f'بلاک/حذف ربات: {_yes_no(cfg.get("user_blocked_bot_enabled", True))}\n'
        f'پورسانت زیرمجموعه: {_yes_no(cfg.get("referral_commission_enabled", True))}',
        reply_markup=notification_settings_keyboard(cfg),
    )


@router.callback_query(F.data.startswith('admin:set:notifications:toggle:'))
async def notifications_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    key = callback.data.split(':')[-1]
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('notifications')
        cfg[key] = not bool(cfg.get(key, True))
        await service.set('notifications', cfg)
        await AdminService(session).log(callback.from_user.id, 'toggle_notification', 'setting', key)
    await callback.message.answer('تنظیمات اعلان ذخیره شد ✅', reply_markup=notification_settings_keyboard(cfg))


@router.callback_query(F.data == 'admin:set:backup')
async def backup_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('backup')
    await callback.message.answer(
        '💾 بکاپ و ریستور\n\n'
        f'وضعیت بکاپ خودکار: {_yes_no(cfg.get("enabled"))}\n'
        f'بازه ارسال: هر {cfg.get("interval_hours")} ساعت\n'
        f'آخرین ارسال: {cfg.get("last_sent_at") or "—"}',
        reply_markup=backup_settings_keyboard(bool(cfg.get('enabled'))),
    )


@router.callback_query(F.data == 'admin:set:backup:toggle')
async def backup_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('backup')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('backup', cfg)
    await callback.message.answer('تنظیمات بکاپ ذخیره شد ✅')


@router.callback_query(F.data.startswith('admin:set:backup:edit:'))
async def backup_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='backup', field='interval_hours', after='admin:set:backup')
    await callback.message.answer('بازه ارسال خودکار بکاپ را برحسب ساعت بفرست:')


@router.callback_query(F.data == 'admin:set:backup:send_now')
async def backup_send_now(callback: CallbackQuery) -> None:
    await callback.answer('در حال ساخت بکاپ')
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        await BackupService(session).send_backup_to_admins(callback.bot, caption='💾 بکاپ دستی ربات')
    await callback.message.answer('بکاپ برای ادمین‌ها ارسال شد ✅')


@router.callback_query(F.data == 'admin:set:backup:restore')
async def backup_restore_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    await state.set_state(AdminSettingsStates.waiting_backup_restore)
    await callback.message.answer('فایل JSON بکاپ را ارسال کن تا ریستور شود. دقت کن داده‌های فعلی جایگزین می‌شوند.')


@router.message(AdminSettingsStates.waiting_backup_restore)
async def backup_restore_file(message: Message, state: FSMContext) -> None:
    if not message.document:
        await message.answer('لطفاً فایل JSON بکاپ را به صورت Document بفرست.')
        return

    filename = (message.document.file_name or '').lower()
    if filename and not filename.endswith('.json'):
        await message.answer('فایل بکاپ باید با فرمت JSON باشد.')
        return

    buffer = BytesIO()
    try:
        await message.bot.download(message.document, destination=buffer)
        raw = buffer.getvalue()
        if not raw.strip():
            await message.answer('فایل بکاپ خالی است.')
            return
        async with SessionLocal() as session:
            counts = await BackupService(session).restore_from_bytes(raw)
    except Exception as exc:
        await message.answer(f'ریستور انجام نشد ❌\nخطا: {exc}')
        return

    await state.clear()
    summary = '\n'.join(f'{k}: {v}' for k, v in counts.items())
    await message.answer('ریستور انجام شد ✅\n' + summary)


@router.callback_query(F.data == 'admin:set:discounts')
async def discounts_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('discounts')
    await callback.message.answer('🎟 تنظیمات کد تخفیف', reply_markup=discounts_settings_keyboard(bool(cfg.get('enabled')), bool(cfg.get('apply_button_enabled', True))))


@router.callback_query(F.data == 'admin:set:discounts:toggle')
async def discounts_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('discounts')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('discounts', cfg)
    await callback.message.answer('تنظیمات تخفیف ذخیره شد ✅')


@router.callback_query(F.data == 'admin:set:discounts:toggle_apply')
async def discounts_toggle_apply(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('discounts')
        cfg['apply_button_enabled'] = not bool(cfg.get('apply_button_enabled', True))
        await service.set('discounts', cfg)
    await callback.message.answer('گزینه اعمال کد ذخیره شد ✅')


@router.callback_query(F.data == 'admin:discount:create')
async def discount_create_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(AdminDiscountStates.waiting_code)
    await callback.message.answer('کد تخفیف را بفرست؛ مثلاً: OFF20')


@router.message(AdminDiscountStates.waiting_code)
async def discount_code_step(message: Message, state: FSMContext) -> None:
    code = (message.text or '').strip().upper()
    if not code or len(code) > 64 or ' ' in code:
        await message.answer('کد معتبر نیست. کد باید بدون فاصله باشد؛ مثلاً OFF20')
        return
    await state.update_data(discount_code=code)
    await message.answer('نوع تخفیف را انتخاب کن:', reply_markup=discount_type_keyboard())


@router.callback_query(F.data.startswith('admin:discount:type:'))
async def discount_type_step(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    discount_type = callback.data.split(':')[-1]
    if discount_type not in {'percent', 'fixed'}:
        await callback.message.answer('نوع تخفیف معتبر نیست.')
        return
    await state.update_data(discount_type=discount_type)
    await state.set_state(AdminDiscountStates.waiting_value)
    if discount_type == 'percent':
        await callback.message.answer('درصد تخفیف را فقط عدد بفرست؛ مثلاً 20')
    else:
        await callback.message.answer('مبلغ تخفیف ثابت را به تومان بفرست؛ مثلاً 50000')


@router.message(AdminDiscountStates.waiting_value)
async def discount_value_step(message: Message, state: FSMContext) -> None:
    raw = (message.text or '').replace(',', '').strip()
    try:
        value = Decimal(raw)
    except Exception:
        await message.answer('مقدار معتبر نیست. فقط عدد بفرست.')
        return
    data = await state.get_data()
    if data.get('discount_type') == 'percent' and (value <= 0 or value > 100):
        await message.answer('درصد باید بین 1 تا 100 باشد.')
        return
    if value <= 0:
        await message.answer('مقدار تخفیف باید بیشتر از صفر باشد.')
        return
    await state.update_data(discount_value=str(value))
    await state.set_state(AdminDiscountStates.waiting_max_uses)
    await message.answer('تعداد استفاده مجاز کل کد را انتخاب کن یا عدد دلخواه را بفرست:', reply_markup=discount_max_uses_keyboard())


async def _save_discount_max_uses(message: Message, state: FSMContext, raw_value: str) -> None:
    raw = raw_value.strip().lower()
    max_uses = None
    if raw not in {'unlimited', 'none', '-', 'نامحدود'}:
        try:
            max_uses = int(raw)
        except Exception:
            await message.answer('تعداد استفاده معتبر نیست. عدد بفرست یا نامحدود را انتخاب کن.')
            return
        if max_uses <= 0:
            await message.answer('تعداد استفاده باید بیشتر از صفر باشد، یا نامحدود را انتخاب کن.')
            return
    await state.update_data(discount_max_uses=max_uses)
    await state.set_state(AdminDiscountStates.waiting_per_user_limit)
    await message.answer('محدودیت استفاده برای هر کاربر را انتخاب کن:', reply_markup=discount_per_user_limit_keyboard())


@router.callback_query(F.data.startswith('admin:discount:max:'))
async def discount_max_uses_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _save_discount_max_uses(callback.message, state, callback.data.split(':')[-1])


@router.message(AdminDiscountStates.waiting_max_uses)
async def discount_max_uses_message(message: Message, state: FSMContext) -> None:
    await _save_discount_max_uses(message, state, message.text or '')


async def _save_discount_per_user_limit(message: Message, state: FSMContext, raw_value: str) -> None:
    try:
        per_user_limit = int(str(raw_value).strip())
    except Exception:
        await message.answer('محدودیت هر کاربر معتبر نیست.')
        return
    if per_user_limit < 0:
        await message.answer('عدد منفی معتبر نیست.')
        return
    await state.update_data(discount_per_user_limit=per_user_limit)
    await state.set_state(AdminDiscountStates.waiting_min_amount)
    await message.answer('حداقل مبلغ سفارش را انتخاب کن یا عدد دلخواه را بفرست:', reply_markup=discount_min_amount_keyboard())


@router.callback_query(F.data.startswith('admin:discount:userlimit:'))
async def discount_per_user_limit_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _save_discount_per_user_limit(callback.message, state, callback.data.split(':')[-1])


@router.message(AdminDiscountStates.waiting_per_user_limit)
async def discount_per_user_limit_message(message: Message, state: FSMContext) -> None:
    await _save_discount_per_user_limit(message, state, message.text or '')


async def _finish_discount_create(message: Message, state: FSMContext, raw_min_amount: str) -> None:
    try:
        min_amount = Decimal(str(raw_min_amount).replace(',', '').strip() or '0')
    except Exception:
        await message.answer('حداقل مبلغ سفارش معتبر نیست.')
        return
    if min_amount < 0:
        await message.answer('حداقل مبلغ نمی‌تواند منفی باشد.')
        return
    data = await state.get_data()
    async with SessionLocal() as session:
        item = await DiscountService(session).create_code(
            code=str(data['discount_code']),
            discount_type=str(data['discount_type']),
            discount_value=Decimal(str(data['discount_value'])),
            max_uses=data.get('discount_max_uses'),
            per_user_limit=int(data.get('discount_per_user_limit', 1)),
            min_order_amount=min_amount,
        )
    await state.clear()
    type_title = 'درصدی' if item.discount_type == 'percent' else 'مبلغ ثابت'
    await message.answer(
        f'کد تخفیف ساخته شد ✅\n'
        f'کد: {item.code}\n'
        f'نوع: {type_title}\n'
        f'مقدار: {item.discount_value}\n'
        f'تعداد استفاده کل: {item.max_uses or "نامحدود"}\n'
        f'محدودیت هر کاربر: {item.per_user_limit or "نامحدود"}\n'
        f'حداقل سفارش: {money(item.min_order_amount)}'
    )


@router.callback_query(F.data.startswith('admin:discount:min:'))
async def discount_min_amount_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _finish_discount_create(callback.message, state, callback.data.split(':')[-1])


@router.message(AdminDiscountStates.waiting_min_amount)
async def discount_min_amount_message(message: Message, state: FSMContext) -> None:
    await _finish_discount_create(message, state, message.text or '0')


@router.callback_query(F.data == 'admin:discount:list')
async def discount_list(callback: CallbackQuery) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        codes = await DiscountService(session).list_codes(limit=30)
    if not codes:
        await callback.message.answer('کد تخفیفی ثبت نشده است.')
        return
    for item in codes:
        text = (
            f'🎟 {item.code}\n'
            f'نوع: {item.discount_type} | مقدار: {item.discount_value}\n'
            f'استفاده: {item.used_count}/{item.max_uses or "نامحدود"}\n'
            f'حداقل سفارش: {money(item.min_order_amount)}\n'
            f'وضعیت: {_yes_no(item.is_active)}'
        )
        await callback.message.answer(text, reply_markup=discount_code_keyboard(item.id, item.is_active))


@router.callback_query(F.data.startswith('admin:discount:toggle:'))
async def discount_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    code_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        await DiscountService(session).toggle_code(code_id)
    await callback.message.answer('وضعیت کد تغییر کرد ✅')


@router.callback_query(F.data.startswith('admin:discount:delete:'))
async def discount_delete(callback: CallbackQuery) -> None:
    await callback.answer()
    code_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        await DiscountService(session).delete_code(code_id)
    await callback.message.answer('کد حذف/غیرفعال شد ✅')


@router.callback_query(F.data == 'admin:set:texts')
async def texts_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if await _guard(callback):
        await callback.message.answer('کدام متن ویرایش شود؟', reply_markup=texts_settings_keyboard(TEXT_KEYS))


@router.callback_query(F.data.startswith('admin:set:texts:edit:'))
async def edit_text(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='texts', field=key, after='admin:set:texts')
    await callback.message.answer('متن جدید را بفرست. می‌توانی از متغیرهای همان متن قبلی استفاده کنی.')


@router.callback_query(F.data == 'admin:set:menu')
async def menu_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if await _guard(callback):
        await callback.message.answer('کدام دکمه منو ویرایش شود؟', reply_markup=menu_settings_keyboard(MENU_KEYS))


@router.callback_query(F.data.startswith('admin:set:menu:edit:'))
async def edit_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='menu', field=key, after='admin:set:menu')
    await callback.message.answer('عنوان جدید دکمه را بفرست:')


@router.callback_query(F.data == 'admin:set:anti_spam')
async def anti_spam_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('anti_spam')
    await callback.message.answer(
        f'🛡 ضداسپم: {_yes_no(cfg.get("enabled"))}\n'
        f'حداکثر پیام: {cfg.get("max_messages")} در {cfg.get("window_seconds")} ثانیه\n'
        f'مدت بلاک: {cfg.get("block_seconds")} ثانیه',
        reply_markup=anti_spam_settings_keyboard(bool(cfg.get('enabled'))),
    )


@router.callback_query(F.data == 'admin:set:anti_spam:toggle')
async def anti_spam_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('anti_spam')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('anti_spam', cfg)
    await callback.message.answer('تنظیمات ضداسپم ذخیره شد ✅')


@router.callback_query(F.data.startswith('admin:set:anti_spam:edit:'))
async def anti_spam_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='anti_spam', field=key, after='admin:set:anti_spam')
    await callback.message.answer('مقدار جدید را بفرست:')


@router.callback_query(F.data == 'admin:set:referral')
async def referral_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        cfg = await SettingsService(session).get('referral')
    await callback.message.answer(
        f'👥 زیرمجموعه‌گیری: {_yes_no(cfg.get("enabled"))}\n'
        f'نوع پاداش: {cfg.get("reward_type")}\n'
        f'درصد: {cfg.get("percent")} | مبلغ ثابت: {cfg.get("fixed_amount")}\n'
        f'مبنا: {cfg.get("basis")}',
        reply_markup=referral_settings_keyboard(bool(cfg.get('enabled'))),
    )


@router.callback_query(F.data == 'admin:set:referral:toggle')
async def referral_toggle(callback: CallbackQuery) -> None:
    await callback.answer()
    if not await _guard(callback):
        return
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get('referral')
        cfg['enabled'] = not bool(cfg.get('enabled'))
        await service.set('referral', cfg)
    await callback.message.answer('تنظیمات زیرمجموعه‌گیری ذخیره شد ✅')


@router.callback_query(F.data.startswith('admin:set:referral:edit:'))
async def referral_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    key = callback.data.split(':')[-1]
    await state.set_state(AdminSettingsStates.waiting_value)
    await state.update_data(setting_key='referral', field=key, after='admin:set:referral')
    if key == 'message_text':
        async with SessionLocal() as session:
            cfg = await SettingsService(session).get('referral')
        await callback.message.answer(_referral_text_help(str(cfg.get('message_text') or '')))
    else:
        await callback.message.answer('مقدار جدید را بفرست:')


@router.message(AdminSettingsStates.waiting_value)
async def save_setting_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    setting_key = data['setting_key']
    field = data['field']
    raw = message.text or ''
    parser = data.get('parser')
    if parser == 'channels':
        value: Any = _parse_channels(raw)
    elif field in NUMERIC_FIELDS.get(setting_key, set()):
        try:
            value = Decimal(raw.replace(',', '').strip()) if setting_key in {'referral', 'plisio'} and field not in {'expire_min'} else int(raw.strip())
        except Exception:
            await message.answer('عدد معتبر نیست.')
            return
        if isinstance(value, Decimal):
            value = float(value) if field == 'source_rate' else int(value) if value == value.to_integral() else float(value)
    else:
        value = raw
    async with SessionLocal() as session:
        service = SettingsService(session)
        cfg = await service.get(setting_key)
        cfg[field] = value
        if setting_key == 'support':
            cfg['mode'] = 'username'
        await service.set(setting_key, cfg)
        await AdminService(session).log(message.from_user.id, 'edit_setting', 'setting', setting_key, {'field': field})
    await state.clear()
    await message.answer('تنظیمات ذخیره شد ✅')
