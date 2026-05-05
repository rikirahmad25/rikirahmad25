from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters import MenuTextFilter
from app.bot.keyboards.admin import topup_review_keyboard
from app.bot.keyboards.user import DEFAULT_MENU_LABELS, wallet_keyboard, wallet_payment_methods_keyboard, wallet_topup_receipt_actions_keyboard
from app.bot.states.order import WalletTopupStates
from app.core.enums import PaymentMethod, PaymentStatus
from app.db.session import SessionLocal
from app.services.admin_service import AdminService
from app.services.crypto_rate_service import SUPPORTED_CRYPTO_SYMBOLS, build_crypto_payment_options, format_crypto_wallet_copy_text, format_crypto_wallets_text, wallet_coin_symbol
from app.services.payments.plisio import PlisioProvider
from app.services.payments.zarinpal import ZarinPalProvider
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.services.wallet_topup_service import WalletTopupService
from app.utils.text import money

router = Router(name='wallet')


def _crypto_wallets_text(wallets: list[dict[str, Any]] | None, *, show_unit_price: bool = False) -> str:
    return format_crypto_wallets_text(wallets, show_unit_price=show_unit_price)


def _custom_payment_titles(plisio_cfg: dict[str, Any] | None = None, crypto_manual_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    titles: dict[str, str] = {}
    plisio_label = str((plisio_cfg or {}).get('display_label') or '').strip()
    crypto_manual_label = str((crypto_manual_cfg or {}).get('display_label') or '').strip()
    if plisio_label:
        titles[PaymentMethod.PLISIO.value] = plisio_label
    if crypto_manual_label:
        titles[PaymentMethod.CRYPTO_MANUAL.value] = crypto_manual_label
    return titles


def _format_plisio_pay_text(template: str, invoice_url: str, extra: dict[str, Any], **context: Any) -> str:
    source_rate_line = str(extra.get('_source_rate_line') or '').strip()
    values = {
        'invoice_url': invoice_url or '—',
        'crypto_amount': extra.get('invoice_total_sum') or extra.get('amount') or extra.get('pending_amount') or '—',
        'currency': extra.get('currency') or extra.get('psys_cid') or '—',
        'wallet_hash': extra.get('wallet_hash') or 'در لینک پرداخت نمایش داده می‌شود',
        'source_amount': extra.get('_source_amount') or extra.get('source_amount') or '—',
        'source_rate': extra.get('_source_rate_toman_display') or extra.get('_source_rate_toman') or '—',
        'source_rate_toman': extra.get('_source_rate_toman_display') or extra.get('_source_rate_toman') or '—',
        'source_rate_line': source_rate_line,
        'source_rate_mode': extra.get('_source_rate_mode') or '—',
        'source_rate_error': extra.get('_source_rate_error') or '',
    }
    values.update(context)
    text = template.format(**values)
    if source_rate_line and source_rate_line not in text:
        text += f'\n\n{source_rate_line}'
    return text


def _menu_text_values(menu_labels: dict[str, Any] | None) -> set[str]:
    values = set(DEFAULT_MENU_LABELS.values())
    values.update(str(value) for value in (menu_labels or {}).values() if value)
    return {value.strip() for value in values if value and value.strip()}


def _looks_like_menu_or_command(text: str | None, menu_labels: dict[str, Any] | None) -> bool:
    value = (text or '').strip()
    if not value:
        return False
    return value.startswith('/') or value in _menu_text_values(menu_labels)


def _append_note(current: str | None, new_note: str) -> str:
    current = (current or '').strip()
    return (current + '\n' + new_note).strip() if current else new_note


def _topup_payment_methods(payments: dict[str, Any]) -> list[str]:
    enabled_methods = list(payments.get('enabled_methods') or ['card_to_card'])
    display_order = list(payments.get('display_order') or enabled_methods)
    enabled = [m for m in display_order if m in enabled_methods and m != 'wallet']
    return enabled or ['card_to_card']


def _active_crypto_wallets(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    wallets: list[dict[str, Any]] = []
    for wallet in cfg.get('wallets') or []:
        if not isinstance(wallet, dict) or not wallet.get('address') or not wallet.get('is_active', True):
            continue
        symbol = wallet_coin_symbol(wallet)
        if symbol not in SUPPORTED_CRYPTO_SYMBOLS:
            continue
        item = dict(wallet)
        item['coin_symbol'] = symbol
        wallets.append(item)
    return wallets


def _topup_caption(topup, status_line: str | None = None) -> str:
    text = (
        '🧾 رسید شارژ کیف پول\n'
        f'شماره شارژ: {topup.topup_number}\n'
        f'کاربر: {topup.user.first_name or "—"} (@{topup.user.username or "—"})\n'
        f'آیدی تلگرام: {topup.user.telegram_id}\n'
        f'مبلغ: {money(topup.amount)}'
    )
    if topup.receipt_text:
        text += f'\nتوضیح رسید: {topup.receipt_text}'
    if status_line:
        text += f'\n\n{status_line}'
    return text[:1024]


async def _send_topup_review(bot, session, topup) -> None:
    admin_ids = await AdminService(session).get_admin_telegram_ids()
    messages: list[dict[str, Any]] = []
    errors: list[str] = []
    caption = _topup_caption(topup)
    receipt_type = (topup.metadata_json or {}).get('receipt_content_type')
    for admin_id in admin_ids:
        try:
            if topup.receipt_file_id and receipt_type == 'document':
                sent = await bot.send_document(admin_id, document=topup.receipt_file_id, caption=caption, reply_markup=topup_review_keyboard(topup.id))
                content_type = 'document'
            elif topup.receipt_file_id:
                sent = await bot.send_photo(admin_id, photo=topup.receipt_file_id, caption=caption, reply_markup=topup_review_keyboard(topup.id))
                content_type = 'photo'
            else:
                sent = await bot.send_message(admin_id, caption, reply_markup=topup_review_keyboard(topup.id))
                content_type = 'text'
            messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': content_type})
        except Exception as exc:
            errors.append(f'{admin_id}: {type(exc).__name__}: {exc}')
            try:
                sent = await bot.send_message(admin_id, (caption + '\n\n⚠️ ارسال فایل رسید خطا داد، اما درخواست شارژ در پنل قابل بررسی است.')[:3900], reply_markup=topup_review_keyboard(topup.id))
                messages.append({'chat_id': admin_id, 'message_id': sent.message_id, 'content_type': 'text'})
            except Exception as fallback_exc:
                errors.append(f'{admin_id} fallback: {type(fallback_exc).__name__}: {fallback_exc}')
    meta = dict(topup.metadata_json or {})
    meta['review_messages'] = messages
    if errors:
        meta['review_send_errors'] = errors[-20:]
    topup.metadata_json = meta
    await session.commit()


@router.message(MenuTextFilter('wallet', '💰 کیف پول'))
async def wallet_menu(message: Message) -> None:
    async with SessionLocal() as session:
        user = await UserService(session).get_or_create(message.from_user.id, message.from_user.first_name, message.from_user.last_name, message.from_user.username)
    await message.answer(f'💰 موجودی کیف پول شما: {money(user.wallet_balance or 0)}', reply_markup=wallet_keyboard())


@router.callback_query(F.data == 'wallet:topup')
async def wallet_topup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    async with SessionLocal() as session:
        texts = await SettingsService(session).get('texts')
    await state.set_state(WalletTopupStates.waiting_amount)
    await callback.message.answer(texts.get('wallet_charge_ask_amount', 'مبلغ شارژ کیف پول را به تومان وارد کن:'))


@router.message(WalletTopupStates.waiting_amount)
async def wallet_topup_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = Decimal((message.text or '').replace(',', '').strip())
        if amount <= 0:
            raise InvalidOperation
    except Exception:
        await message.answer('مبلغ معتبر نیست. فقط عدد مثبت بفرست.')
        return
    async with SessionLocal() as session:
        user = await UserService(session).get_or_create(message.from_user.id, message.from_user.first_name, message.from_user.last_name, message.from_user.username)
        topup = await WalletTopupService(session).create(user, amount)
        settings_service = SettingsService(session)
        payments = await settings_service.get('payments')
        plisio_cfg = await settings_service.get('plisio')
        crypto_manual_cfg = await settings_service.get('crypto_manual')
    await state.update_data(topup_id=topup.id)
    enabled = _topup_payment_methods(payments)
    if payments.get('auto_start_single_method', True) and len(enabled) == 1:
        await _start_topup_payment(message, state, topup.id, enabled[0])
        return
    titles = _custom_payment_titles(plisio_cfg, crypto_manual_cfg)
    await message.answer('روش پرداخت شارژ کیف پول را انتخاب کن:', reply_markup=wallet_payment_methods_keyboard(enabled, titles=titles))


@router.callback_query(F.data.startswith('wallet:pay:'))
async def wallet_pay_method(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    topup_id = data.get('topup_id')
    if not topup_id:
        await callback.message.answer('درخواست شارژ فعال پیدا نشد.')
        return
    method = callback.data.split(':')[-1]
    await _start_topup_payment(callback.message, state, int(topup_id), method)


@router.callback_query(F.data == 'wallet:cancel')
async def wallet_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer('لغو شد')
    await state.clear()
    await callback.message.answer('عملیات شارژ کیف پول لغو شد.')


async def _start_topup_payment(message: Message, state: FSMContext, topup_id: int, method: str) -> None:
    async with SessionLocal() as session:
        topup = await WalletTopupService(session).get(topup_id)
        if not topup:
            await message.answer('درخواست شارژ پیدا نشد.')
            return
        texts = await SettingsService(session).get('texts')
        if method == PaymentMethod.CARD_TO_CARD.value:
            cfg = await SettingsService(session).get('card_to_card')
            topup.method = PaymentMethod.CARD_TO_CARD.value
            topup.status = PaymentStatus.WAITING_RECEIPT.value
            await session.commit()
            box = cfg.get('box_text') or ''
            await state.set_state(WalletTopupStates.waiting_payment_receipt)
            await state.update_data(topup_id=topup.id)
            await message.answer(
                box.format(
                    order_number=topup.topup_number,
                    amount=money(topup.amount),
                    raw_amount=topup.amount,
                    card_number=cfg.get('card_number') or '',
                    card_holder=cfg.get('card_holder') or '',
                    bank=cfg.get('bank') or '',
                ),
                reply_markup=wallet_topup_receipt_actions_keyboard(topup.id),
            )
            return
        if method == PaymentMethod.CRYPTO_MANUAL.value:
            cfg = await SettingsService(session).get('crypto_manual')
            wallets = _active_crypto_wallets(cfg)
            if not wallets:
                await message.answer('آدرس ولت فعالی برای پرداخت رمزارز ثبت نشده است.')
                return
            show_unit_price = bool(cfg.get('show_unit_price', False))
            crypto_options = await build_crypto_payment_options(
                topup.amount,
                wallets,
                show_unit_price=show_unit_price,
                auto_convert_enabled=bool(cfg.get('auto_convert_enabled', True)),
            )
            wallets = list(crypto_options.get('wallets') or wallets)
            topup.method = PaymentMethod.CRYPTO_MANUAL.value
            topup.status = PaymentStatus.WAITING_RECEIPT.value
            meta = dict(topup.metadata_json or {})
            meta['wallets'] = wallets
            meta['crypto_quote'] = crypto_options.get('quote') or {}
            topup.metadata_json = meta
            await session.commit()
            wallets_text = _crypto_wallets_text(wallets, show_unit_price=show_unit_price)
            instructions = str(cfg.get('instructions') or '').strip()
            template = texts.get('crypto_manual_pay_message') or '🪙 پرداخت با رمزارز\n\nشماره سفارش: {order_number}\nمبلغ قابل پرداخت: {amount}\n\n{wallets_text}'
            pay_text = template.format(
                order_number=topup.topup_number,
                amount=money(topup.amount),
                raw_amount=topup.amount,
                wallets_text=wallets_text,
                instructions=instructions,
                crypto_quote_errors='، '.join((crypto_options.get('quote') or {}).get('errors') or []),
            )
            if instructions and instructions not in pay_text:
                pay_text += f'\n\n{instructions}'
            await state.set_state(WalletTopupStates.waiting_payment_receipt)
            await state.update_data(topup_id=topup.id)
            await message.answer(pay_text[:3900], reply_markup=wallet_topup_receipt_actions_keyboard(topup.id, wallets=wallets))
            return
        if method == PaymentMethod.ZARINPAL.value:
            result = await ZarinPalProvider(session).create_wallet_topup(topup)
            if not result.success:
                await message.answer(result.message)
                return
            await state.clear()
            await message.answer('برای پرداخت شارژ کیف پول از لینک زیر استفاده کن:', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='پرداخت زرین‌پال', url=result.payment_url)]]))
            return
        if method == PaymentMethod.PLISIO.value:
            result = await PlisioProvider(session).create_wallet_topup(topup)
            if not result.success:
                reply_markup = None
                if (result.extra or {}).get('error_code') == 'plisio_min_amount':
                    reply_markup = wallet_topup_receipt_actions_keyboard(topup.id)
                await message.answer(result.message, reply_markup=reply_markup)
                return
            extra = result.extra or {}
            invoice_url = result.payment_url or extra.get('invoice_url') or '—'
            template = texts.get('plisio_pay_message') or 'برای پرداخت کریپتویی از لینک زیر استفاده کن:\n{invoice_url}'
            text = _format_plisio_pay_text(
                template,
                invoice_url,
                extra,
                order_number=topup.topup_number,
                amount=money(topup.amount),
                raw_amount=topup.amount,
            )
            keyboard = None
            if result.payment_url:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='پرداخت کریپتویی', url=result.payment_url)]])
            await state.clear()
            await message.answer(text, reply_markup=keyboard)
            return
    await message.answer('این روش پرداخت برای شارژ کیف پول پشتیبانی نمی‌شود.')


@router.callback_query(F.data.startswith('wallet:copy_wallet:'))
async def copy_topup_crypto_wallet(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    try:
        topup_id = int(parts[-2])
        index = int(parts[-1]) - 1
    except (TypeError, ValueError):
        await callback.message.answer('آدرس ولت پیدا نشد.')
        return
    async with SessionLocal() as session:
        topup = await WalletTopupService(session).get(topup_id)
    if not topup or not topup.user or topup.user.telegram_id != callback.from_user.id:
        await callback.message.answer('این آدرس برای شارژ کیف پول شما پیدا نشد.')
        return
    wallets = list((topup.metadata_json or {}).get('wallets') or [])
    if index < 0 or index >= len(wallets):
        await callback.message.answer('آدرس ولت پیدا نشد.')
        return
    await callback.message.answer(format_crypto_wallet_copy_text(wallets[index]))


@router.callback_query(F.data.startswith('wallet:back_payment:'))
async def wallet_back_to_payment_methods(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    topup_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        service = WalletTopupService(session)
        topup = await service.get(topup_id)
        if not topup:
            await state.clear()
            await callback.message.answer('درخواست شارژ پیدا نشد.')
            return
        if topup.status == PaymentStatus.PENDING_VERIFY.value:
            await callback.message.answer('رسید این شارژ قبلاً ثبت شده و در انتظار بررسی ادمین است؛ امکان برگشت وجود ندارد.')
            return
        if topup.status == PaymentStatus.VERIFIED.value:
            await callback.message.answer('این شارژ قبلاً تایید شده است.')
            return
        if topup.status == PaymentStatus.CANCELLED.value:
            await state.clear()
            await callback.message.answer('این درخواست شارژ قبلاً لغو شده است.')
            return
        topup.status = PaymentStatus.INITIATED.value
        topup.method = None
        meta = dict(topup.metadata_json or {})
        meta['internal_note'] = _append_note(meta.get('internal_note'), 'کاربر از مرحله ارسال رسید به انتخاب روش پرداخت کیف پول برگشت.')
        topup.metadata_json = meta
        settings_service = SettingsService(session)
        payments = await settings_service.get('payments')
        plisio_cfg = await settings_service.get('plisio')
        crypto_manual_cfg = await settings_service.get('crypto_manual')
        await session.commit()
    enabled = _topup_payment_methods(payments)
    titles = _custom_payment_titles(plisio_cfg, crypto_manual_cfg)
    await state.set_state(WalletTopupStates.waiting_payment_receipt)
    await state.update_data(topup_id=topup_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('روش پرداخت شارژ کیف پول را دوباره انتخاب کن:', reply_markup=wallet_payment_methods_keyboard(enabled, titles=titles))


@router.callback_query(F.data.startswith('wallet:cancel_topup:'))
async def wallet_cancel_topup_from_receipt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    topup_id = int(callback.data.split(':')[-1])
    async with SessionLocal() as session:
        topup = await WalletTopupService(session).get(topup_id)
        if not topup:
            await state.clear()
            await callback.message.answer('درخواست شارژ پیدا نشد.')
            return
        if topup.status == PaymentStatus.PENDING_VERIFY.value:
            await callback.message.answer('رسید این شارژ قبلاً ثبت شده و در انتظار بررسی ادمین است؛ امکان لغو از اینجا وجود ندارد.')
            return
        if topup.status == PaymentStatus.VERIFIED.value:
            await callback.message.answer('این شارژ قبلاً تایید شده است.')
            return
        if topup.status == PaymentStatus.CANCELLED.value:
            await state.clear()
            await callback.message.answer('این درخواست شارژ قبلاً لغو شده است.')
            return
        topup.status = PaymentStatus.CANCELLED.value
        meta = dict(topup.metadata_json or {})
        meta['internal_note'] = _append_note(meta.get('internal_note'), 'کاربر شارژ کیف پول را در مرحله ارسال رسید لغو کرد.')
        topup.metadata_json = meta
        await session.commit()
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer('درخواست شارژ کیف پول لغو شد و رسیدی برای ادمین ساخته نشد ✅')


@router.message(WalletTopupStates.waiting_payment_receipt)
async def wallet_topup_receipt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    raw_topup_id = data.get('topup_id')
    if not raw_topup_id:
        await message.answer('درخواست شارژ فعال پیدا نشد. لطفاً شارژ کیف پول را دوباره شروع کن.')
        await state.clear()
        return
    topup_id = int(raw_topup_id)
    text = message.caption or message.text or ''
    receipt_content_type = 'text'
    file_id = message.photo[-1].file_id if message.photo else None
    if file_id:
        receipt_content_type = 'photo'
    if not file_id and message.document:
        file_id = message.document.file_id
        receipt_content_type = 'document'
    async with SessionLocal() as session:
        topup_service = WalletTopupService(session)
        settings_service = SettingsService(session)
        topup = await topup_service.get(topup_id)
        texts = await settings_service.get('texts')
        menu_labels = await settings_service.get('menu')
        if not topup:
            await message.answer('درخواست شارژ پیدا نشد.')
            await state.clear()
            return
        if not file_id and _looks_like_menu_or_command(text, menu_labels):
            await message.answer(
                'این پیام شبیه دکمه منو/دستور ربات است و به عنوان رسید شارژ ثبت نشد.\n'
                'لطفاً عکس فیش، فایل رسید یا هش/کد پیگیری پرداخت را ارسال کن؛ یا از دکمه‌های زیر برای برگشت و لغو استفاده کن.',
                reply_markup=wallet_topup_receipt_actions_keyboard(topup.id),
            )
            return
        if not file_id and not (text or '').strip():
            await message.answer(
                'رسید معتبر دریافت نشد. لطفاً عکس فیش، فایل رسید یا هش/کد پیگیری پرداخت را ارسال کن.',
                reply_markup=wallet_topup_receipt_actions_keyboard(topup.id),
            )
            return
        topup = await topup_service.set_pending_receipt(topup, text, file_id)
        meta = dict(topup.metadata_json or {})
        meta['receipt_content_type'] = receipt_content_type
        topup.metadata_json = meta
        await session.commit()
        await _send_topup_review(message.bot, session, topup)
    await state.clear()
    await message.answer(texts.get('wallet_charge_receipt_received', 'رسید شارژ کیف پول ثبت شد ✅'))
