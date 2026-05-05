from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting

DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    'texts': {
        'welcome': 'سلام 👋\nبه فروشگاه ما خوش آمدی. از منو محصولت را انتخاب کن.',
        'products_title': 'محصولات فعال:',
        'no_products': 'فعلاً محصول فعالی نداریم.',
        'choose_payment_method': 'روش پرداخت را انتخاب کن:',
        'discount_prompt': 'اگر کد تخفیف داری می‌توانی قبل از پرداخت وارد کنی.',
        'discount_ask_code': 'کد تخفیف را ارسال کن:',
        'discount_applied': '✅ کد تخفیف اعمال شد.\nمبلغ اولیه: {original_amount}\nتخفیف: {discount_amount}\nمبلغ نهایی: {final_amount}',
        'discount_invalid': 'کد تخفیف معتبر نیست یا برای این سفارش قابل استفاده نیست.',
        'order_completed': '✅ سفارش {order_number} تکمیل شد. ممنون از خریدت.',
        'payment_approved': '✅ پرداخت سفارش {order_number} تایید شد و سفارش در مرحله پردازش قرار گرفت.',
        'payment_rejected': '❌ رسید سفارش {order_number} تایید نشد. برای پیگیری با پشتیبانی پیام بده.',
        'payment_error': '❌ پرداخت با خطا روبه‌رو شد. دوباره تلاش کن یا به پشتیبانی پیام بده.',
        'support_text': 'برای ارتباط با پشتیبانی روی دکمه زیر بزن.',
        'support_button': 'ارتباط با پشتیبانی',
        'receipt_received': 'رسید ثبت شد ✅ بعد از بررسی ادمین نتیجه برایت ارسال می‌شود.',
        'force_join_message': 'برای استفاده از ربات باید اول در کانال/گروه‌های اجباری عضو شوی.',
        'force_join_success': 'عضویت تایید شد ✅',
        'force_join_failed': 'هنوز عضویت کامل نیست.',
        'force_phone_message': 'برای استفاده از ربات باید شماره تلفن اکانتت را با دکمه زیر ارسال کنی.',
        'force_phone_success': 'شماره شما تایید شد ✅',
        'request_email': 'لطفاً ایمیل خودت را ارسال کن:',
        'request_phone': 'لطفاً شماره تلفن خودت را ارسال کن:',
        'request_username': 'لطفاً آیدی/نام کاربری موردنظر را ارسال کن:',
        'request_note': 'لطفاً اطلاعات تکمیلی موردنیاز را ارسال کن:',
        'tutorials_title': 'آموزش‌های موجود:',
        'no_tutorials': 'فعلاً آموزشی ثبت نشده است.',
        'wallet_charge_ask_amount': 'مبلغ شارژ کیف پول را به تومان وارد کن:',
        'wallet_charge_receipt_received': 'رسید شارژ کیف پول ثبت شد ✅ بعد از تایید ادمین، موجودی اضافه می‌شود.',
        'wallet_charge_paid': '✅ شارژ کیف پول به مبلغ {amount} تایید شد. موجودی فعلی: {balance}',
        'wallet_charge_rejected': '❌ رسید شارژ کیف پول تایید نشد. برای پیگیری با پشتیبانی پیام بده.',
        'plisio_pay_message': 'برای پرداخت کریپتویی از لینک زیر استفاده کن:\n{invoice_url}\n\nمبلغ کریپتویی: {crypto_amount}\nارز: {currency}\nولت: {wallet_hash}\n{source_rate_line}',
        'crypto_manual_pay_message': '🪙 پرداخت با رمزارز\n\nشماره سفارش: {order_number}\nمبلغ قابل پرداخت: {amount}\n\nمعادل هر ارز به صورت خودکار با قیمت لحظه‌ای نوبیتکس محاسبه شده است. یکی از آدرس‌های زیر را انتخاب و پرداخت کن، سپس عکس رسید یا هش تراکنش را همینجا بفرست:\n\n{wallets_text}',
        'blocked_message': '⛔️ دسترسی شما به ربات مسدود شده است.',
        'new_user_admin_notification': '🆕 کاربر جدید وارد ربات شد.\nنام: {name}\nیوزرنیم: {username}\nآیدی: {telegram_id}\nمعرف: {referrer}',
        'user_blocked_bot_admin_notification': '🚫 کاربر ربات را بلاک یا حذف کرد.\nنام: {name}\nیوزرنیم: {username}\nآیدی: {telegram_id}',
        'referral_commission_received': '🎉 یک خرید از لینک زیرمجموعه‌گیری شما ثبت شد.\nسفارش: {order_number}\nپورسانت شما: {commission}\nموجودی فعلی: {balance}',
        'manual_wallet_charge': '✅ کیف پول شما توسط ادمین به مبلغ {amount} شارژ شد. موجودی فعلی: {balance}',
        'lottery_win': '🎁 تبریک! شما در قرعه‌کشی برنده شدید.\nهدیه: {prize_text}\nمبلغ افزوده‌شده به کیف پول: {amount}',
    },
    'menu': {
        'products': '🛍 محصولات',
        'tutorials': '🎬 آموزش‌ها',
        'orders': '📦 سفارش‌های من',
        'support': '☎️ پشتیبانی',
        'wallet': '💰 کیف پول',
        'referral': '👥 زیرمجموعه‌گیری',
        'admin_panel': '⚙️ پنل ادمین',
        'send_phone': '📱 ارسال شماره',
    },
    'features': {
        'sales_enabled': True,
        'tutorials_enabled': True,
        'ticket_enabled': False,
        'wallet_enabled': True,
        'referral_enabled': True,
        'lottery_enabled': True,
        'broadcast_enabled': True,
    },
    'notifications': {
        'new_user_enabled': True,
        'user_blocked_bot_enabled': True,
        'referral_commission_enabled': True,
    },
    'reports': {
        'daily_sales_enabled': False,
        'daily_sales_time': '23:55',
        'timezone': 'Europe/Istanbul',
        'last_daily_sales_date': None,
    },
    'product_categories': {
        'next_id': 2,
        # نمایش لیست خود دسته‌بندی‌ها در منوی کاربر: 'single' (تک‌ستونه) یا 'double' (دوستونه)
        'categories_layout': 'single',
        # نمایش محصولات داخل بخش «بدون دسته» (uncategorized)
        'uncategorized_layout': 'single',
        'items': [
            {'id': 'cat_1', 'title': 'عمومی', 'is_active': True, 'layout': 'single'},
        ],
    },
    'payments': {
        'enabled_methods': ['card_to_card'],
        'display_order': ['card_to_card', 'zarinpal', 'plisio', 'crypto_manual', 'wallet'],
        'default_method': 'card_to_card',
        'auto_start_single_method': True,
    },
    'card_to_card': {
        'card_number': '',
        'card_holder': '',
        'bank': '',
        'box_text': (
            '🏦 پرداخت کارت‌به‌کارت\n\n'
            'شماره سفارش: {order_number}\n'
            'مبلغ قابل پرداخت: {amount}\n\n'
            'شماره کارت: {card_number}\n'
            'به نام: {card_holder}\n'
            'بانک: {bank}\n\n'
            'بعد از واریز، عکس فیش یا کد پیگیری را همینجا ارسال کن.'
        ),
    },
    'zarinpal': {'merchant_id': '', 'callback_url': ''},
    'plisio': {
        'api_key': '',
        'source_currency': 'USD',
        'source_rate': 1,
        'auto_usdt_rate_enabled': False,
        'fallback_to_manual_rate_enabled': False,
        'show_source_rate': False,
        'display_label': '🪙 پرداخت کریپتویی آنلاین',
        'currency': 'BTC',
        'allowed_psys_cids': 'BTC,ETH,LTC,DOGE,USDT_TRX,USDT_BSC,USDT_ERC20',
        'callback_url': '',
        'expire_min': 60,
        'verify_callback': True,
    },
    'crypto_manual': {
        'wallets': [],
        'instructions': '',
        'display_label': '🪙 پرداخت با رمز ارز',
        'next_id': 1,
        'allowed_coins': ['TRX', 'USDT', 'TON'],
        'auto_convert_enabled': True,
        'show_unit_price': False,
    },
    'channels': {'enabled': False, 'required_channels': []},
    'phone_verification': {'enabled': False},
    'support': {'mode': 'username', 'support_username': ''},
    'backup': {'enabled': False, 'interval_hours': 24, 'last_sent_at': None},
    'referral': {
        'enabled': True,
        'reward_type': 'percent',
        'percent': 10,
        'fixed_amount': 0,
        'basis': 'paid_amount',
        'min_order_amount': 0,
        'max_commission': 0,
        'register_on': 'paid',
        'wallet_spend_enabled': True,
        'message_text': (
            'لینک دعوت شما:\n'
            '{referral_link}\n\n'
            '{reward_line}\n'
            'موجودی پورسانت/کیف پول: {wallet_balance}\n'
            'هر خرید موفق زیرمجموعه‌ها طبق تنظیمات فعلی، پورسانت ثبت می‌کند.'
        ),
    },
    'discounts': {'enabled': False, 'apply_button_enabled': True, 'stackable': False},
    'anti_spam': {
        'enabled': True,
        'max_messages': 8,
        'window_seconds': 10,
        'block_seconds': 30,
        'warn_text': 'لطفاً کمی آرام‌تر پیام بفرستید و چند ثانیه بعد دوباره تلاش کنید.',
    },
}


def _deep_merge(default: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(default)
    for key, value in (current or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        item = result.scalar_one_or_none()
        default_value = fallback if fallback is not None else DEFAULT_SETTINGS.get(key, {})
        if item:
            value = _deep_merge(default_value, item.value or {}) if isinstance(default_value, dict) else (item.value or {})
            if key == 'payments' and not value.get('_payment_methods_migrated_v2'):
                enabled = list(value.get('enabled_methods') or [])
                if 'card_to_card' not in enabled:
                    enabled.insert(0, 'card_to_card')
                display_order = list(value.get('display_order') or enabled)
                display_order = ['card_to_card'] + [method for method in display_order if method != 'card_to_card']
                for method in ['zarinpal', 'plisio', 'wallet']:
                    if method not in display_order:
                        display_order.append(method)
                value['enabled_methods'] = enabled
                value['display_order'] = display_order
                value['default_method'] = 'card_to_card' if 'card_to_card' in enabled else enabled[0]
                value['_payment_methods_migrated_v2'] = True
            if key == 'payments' and not value.get('_crypto_manual_method_added'):
                display_order = list(value.get('display_order') or value.get('enabled_methods') or [])
                if 'crypto_manual' not in display_order:
                    insert_at = display_order.index('wallet') if 'wallet' in display_order else len(display_order)
                    display_order.insert(insert_at, 'crypto_manual')
                value['display_order'] = display_order
                enabled = list(value.get('enabled_methods') or [])
                # رمزارز دستی عمداً به صورت پیش‌فرض فعال نمی‌شود.
                value['enabled_methods'] = [method for method in enabled if method]
                value['_crypto_manual_method_added'] = True
            if key == 'support':
                value['mode'] = 'username'
            if value != (item.value or {}):
                item.value = value
                await self.session.commit()
            return value
        value = deepcopy(default_value)
        self.session.add(Setting(key=key, value=value))
        await self.session.commit()
        return value

    async def set(self, key: str, value: dict[str, Any]) -> Setting:
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        item = result.scalar_one_or_none()
        if item:
            item.value = value
        else:
            item = Setting(key=key, value=value)
            self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item
