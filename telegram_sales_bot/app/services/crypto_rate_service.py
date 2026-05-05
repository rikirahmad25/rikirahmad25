from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
from html import escape
from typing import Any

import httpx

NOBITEX_BASE_URL = 'https://apiv2.nobitex.ir'
NOBITEX_MARKET_STATS_PATH = '/market/stats'
NOBITEX_ORDERBOOK_PATH = '/v3/orderbook/{symbol}IRT'
RIAL_PER_TOMAN = Decimal('10')

SUPPORTED_CRYPTO_SYMBOLS = {'TRX', 'USDT', 'TON'}
COIN_SRC_CURRENCY = {
    'TRX': 'trx',
    'USDT': 'usdt',
    'TON': 'ton',
}
COIN_TITLES = {
    'TRX': 'ترون',
    'USDT': 'تتر',
    'TON': 'تون کوین',
}
COIN_DECIMAL_STEPS = {
    'TRX': Decimal('0.000001'),
    'USDT': Decimal('0.0001'),
    'TON': Decimal('0.000001'),
}
COIN_ALIASES = {
    'TRX': 'TRX',
    'TRON': 'TRX',
    'ترون': 'TRX',
    'USDT': 'USDT',
    'TETHER': 'USDT',
    'تتر': 'USDT',
    'TON': 'TON',
    'TONCOIN': 'TON',
    'TON COIN': 'TON',
    'تون': 'TON',
    'تون کوین': 'TON',
}


def normalize_crypto_symbol(value: Any) -> str | None:
    text = str(value or '').strip().replace('‌', ' ')
    if not text:
        return None
    upper = text.upper().replace('-', ' ').replace('_', ' ')
    compact = upper.replace(' ', '')
    direct = COIN_ALIASES.get(text) or COIN_ALIASES.get(upper) or COIN_ALIASES.get(compact)
    if direct:
        return direct
    tokens = upper.replace('(', ' ').replace(')', ' ').replace('/', ' ').replace('|', ' ').split()
    for token in tokens:
        found = COIN_ALIASES.get(token)
        if found:
            return found
    return None


def crypto_display_name(symbol: str | None) -> str:
    symbol = normalize_crypto_symbol(symbol) or str(symbol or '').upper()
    title = COIN_TITLES.get(symbol, symbol or '—')
    return f'{title} ({symbol})' if symbol else '—'


def wallet_coin_symbol(wallet: dict[str, Any]) -> str | None:
    return normalize_crypto_symbol(wallet.get('coin_symbol') or wallet.get('coin') or wallet.get('currency'))


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _format_toman(value: Decimal | str | int | float | None) -> str:
    amount = _decimal(value)
    if amount is None:
        return '—'
    if amount == amount.to_integral():
        return f'{int(amount):,}'
    text = f'{amount:,.2f}'.rstrip('0').rstrip('.')
    return text


def _format_crypto_amount(value: Decimal, symbol: str) -> str:
    step = COIN_DECIMAL_STEPS.get(symbol, Decimal('0.000001'))
    rounded = value.quantize(step, rounding=ROUND_UP)
    text = format(rounded, 'f').rstrip('0').rstrip('.')
    return text or '0'


async def _fetch_orderbook_price(client: httpx.AsyncClient, symbol: str) -> Decimal | None:
    url = NOBITEX_BASE_URL + NOBITEX_ORDERBOOK_PATH.format(symbol=symbol)
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    candidates: list[Any] = [data.get('lastTradePrice')]
    asks = data.get('asks') or []
    bids = data.get('bids') or []
    if asks and isinstance(asks[0], (list, tuple)) and asks[0]:
        candidates.append(asks[0][0])
    if bids and isinstance(bids[0], (list, tuple)) and bids[0]:
        candidates.append(bids[0][0])
    valid = [price for price in (_decimal(item) for item in candidates) if price and price > 0]
    if not valid:
        return None
    # Nobitex IRT orderbook symbols are reported against rls in market metadata; product prices are stored in toman.
    return valid[0] / RIAL_PER_TOMAN


async def fetch_nobitex_toman_prices(symbols: list[str]) -> dict[str, Decimal]:
    requested = []
    for symbol in symbols:
        normalized = normalize_crypto_symbol(symbol)
        if normalized in SUPPORTED_CRYPTO_SYMBOLS and normalized not in requested:
            requested.append(normalized)
    if not requested:
        return {}

    timeout = httpx.Timeout(8.0, connect=5.0)
    headers = {'User-Agent': 'TraderBot/TelegramSalesBot'}
    prices: dict[str, Decimal] = {}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        src_currency = ','.join(COIN_SRC_CURRENCY[symbol] for symbol in requested)
        try:
            response = await client.get(
                NOBITEX_BASE_URL + NOBITEX_MARKET_STATS_PATH,
                params={'srcCurrency': src_currency, 'dstCurrency': 'rls'},
            )
            response.raise_for_status()
            payload = response.json()
            stats = payload.get('stats') or {}
            for symbol in requested:
                src = COIN_SRC_CURRENCY[symbol]
                found_key = ''
                item = None
                for key in (f'{src}-rls', f'{src}-irt'):
                    if key in stats:
                        found_key = key
                        item = stats[key]
                        break
                if item is None:
                    for key, value in stats.items():
                        if str(key).lower().startswith(f'{src}-'):
                            found_key = str(key).lower()
                            item = value
                            break
                if not isinstance(item, dict):
                    continue
                latest = _decimal(item.get('latest') or item.get('dayClose') or item.get('bestSell') or item.get('bestBuy'))
                if not latest or latest <= 0:
                    continue
                if found_key.endswith('-irt'):
                    prices[symbol] = latest
                else:
                    # The documented market/stats endpoint returns rls by default; product prices are stored in toman.
                    prices[symbol] = latest / RIAL_PER_TOMAN
        except Exception:
            # Fall back to per-market orderbook below.
            pass

        missing = [symbol for symbol in requested if symbol not in prices]
        for symbol in missing:
            try:
                price = await _fetch_orderbook_price(client, symbol)
            except Exception:
                price = None
            if price and price > 0:
                prices[symbol] = price
    return prices


async def build_crypto_payment_options(
    amount_toman: Decimal | int | str | float,
    wallets: list[dict[str, Any]],
    *,
    show_unit_price: bool = False,
    auto_convert_enabled: bool = True,
) -> dict[str, Any]:
    amount = Decimal(str(amount_toman or 0))
    enriched_wallets: list[dict[str, Any]] = []
    symbols: list[str] = []
    for wallet in wallets:
        symbol = wallet_coin_symbol(wallet)
        if symbol in SUPPORTED_CRYPTO_SYMBOLS and symbol not in symbols:
            symbols.append(symbol)

    prices: dict[str, Decimal] = {}
    errors: list[str] = []
    if auto_convert_enabled and symbols:
        try:
            prices = await fetch_nobitex_toman_prices(symbols)
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')

    for wallet in wallets:
        item = dict(wallet)
        symbol = wallet_coin_symbol(item)
        if symbol:
            item['coin_symbol'] = symbol
            item['coin'] = COIN_TITLES.get(symbol, symbol)
        price = prices.get(symbol or '')
        if symbol in SUPPORTED_CRYPTO_SYMBOLS and price and price > 0 and amount > 0:
            crypto_amount = amount / price
            item['crypto_amount'] = _format_crypto_amount(crypto_amount, symbol)
            item['unit_price_toman'] = str(price)
            item['unit_price_toman_display'] = _format_toman(price)
        elif auto_convert_enabled and symbol in SUPPORTED_CRYPTO_SYMBOLS:
            item['quote_error'] = 'قیمت لحظه‌ای از نوبیتکس دریافت نشد.'
        elif symbol not in SUPPORTED_CRYPTO_SYMBOLS:
            item['quote_error'] = 'این ارز برای تبدیل خودکار مجاز نیست.'
        enriched_wallets.append(item)

    return {
        'wallets': enriched_wallets,
        'quote': {
            'provider': 'nobitex',
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'amount_toman': str(amount),
            'show_unit_price': bool(show_unit_price),
            'rates_toman': {symbol: str(price) for symbol, price in prices.items()},
            'errors': errors,
        },
    }


def format_crypto_wallet_copy_text(wallet: dict[str, Any] | None) -> str:
    wallet = wallet or {}
    symbol = wallet_coin_symbol(wallet)
    coin_text = crypto_display_name(symbol or wallet.get('coin'))
    network = escape(str(wallet.get('network') or '—'))
    address = escape(str(wallet.get('address') or '—'))
    text = f'📋 آدرس ولت {escape(str(coin_text))}\nشبکه: {network}\n\n<code>{address}</code>'
    if wallet.get('crypto_amount') and symbol:
        text += f'\n\nمعادل قابل پرداخت: {escape(str(wallet.get("crypto_amount")))} {escape(str(symbol))}'
    return text


def format_crypto_wallets_text(wallets: list[dict[str, Any]] | None, *, show_unit_price: bool = False) -> str:
    if not wallets:
        return 'آدرس ولت فعالی ثبت نشده است.'
    lines: list[str] = []
    for idx, wallet in enumerate(wallets, 1):
        symbol = wallet_coin_symbol(wallet)
        coin_text = crypto_display_name(symbol or wallet.get('coin'))
        network = escape(str(wallet.get('network') or '—'))
        address = escape(str(wallet.get('address') or '—'))
        lines.append(f'{idx}. ارز: {escape(str(coin_text))} | شبکه: {network}')
        if wallet.get('crypto_amount') and symbol:
            lines.append(f'معادل قابل پرداخت: {wallet.get("crypto_amount")} {symbol}')
        elif wallet.get('quote_error'):
            lines.append(f'معادل قابل پرداخت: {escape(str(wallet.get("quote_error")))}')
        if show_unit_price and wallet.get('unit_price_toman_display') and symbol:
            lines.append(f'قیمت هر ۱ {symbol}: {wallet.get("unit_price_toman_display")} تومان')
        lines.append(f'آدرس ولت:\n<code>{address}</code>')
        if wallet.get('note'):
            lines.append(f'توضیح: {escape(str(wallet.get("note")))}')
        lines.append('')
    return '\n'.join(lines).strip()
