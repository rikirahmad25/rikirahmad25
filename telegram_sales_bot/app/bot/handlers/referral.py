from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.bot.filters import MenuTextFilter
from app.config import get_settings
from app.db.session import SessionLocal
from app.services.settings_service import SettingsService
from app.services.user_service import UserService
from app.utils.text import money

router = Router(name='referral')
settings = get_settings()


def _render_referral_text(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace('{' + key + '}', str(value))
    return result


@router.message(MenuTextFilter('referral', '👥 زیرمجموعه‌گیری'))
async def referral_view(message: Message) -> None:
    async with SessionLocal() as session:
        user = await UserService(session).get_by_telegram_id(message.from_user.id)
        ref_cfg = await SettingsService(session).get('referral')
    if not user:
        await message.answer('ابتدا /start را بزن.')
        return
    if not ref_cfg.get('enabled', True):
        await message.answer('سیستم زیرمجموعه‌گیری فعلاً غیرفعال است.')
        return
    link = f'https://t.me/{settings.bot_username}?start={user.referral_code}'
    reward_type = ref_cfg.get('reward_type', 'percent')
    if reward_type == 'fixed':
        reward_line = f"پاداش هر خرید موفق: {money(ref_cfg.get('fixed_amount', 0))}"
    else:
        reward_line = f"درصد پورسانت از خرید موفق: {ref_cfg.get('percent', 10)}٪"
    template = ref_cfg.get('message_text') or (
        'لینک دعوت شما:\n'
        '{referral_link}\n\n'
        '{reward_line}\n'
        'موجودی پورسانت/کیف پول: {wallet_balance}\n'
        'هر خرید موفق زیرمجموعه‌ها طبق تنظیمات فعلی، پورسانت ثبت می‌کند.'
    )
    values = {
        'referral_link': link,
        'link': link,
        'referral_code': user.referral_code,
        'bot_username': settings.bot_username,
        'reward_line': reward_line,
        'reward_type': str(reward_type),
        'percent': str(ref_cfg.get('percent', 10)),
        'fixed_amount': money(ref_cfg.get('fixed_amount', 0)),
        'wallet_balance': money(user.wallet_balance or 0),
        'balance': money(user.wallet_balance or 0),
        'min_order_amount': money(ref_cfg.get('min_order_amount', 0)),
        'max_commission': money(ref_cfg.get('max_commission', 0)),
        'basis': str(ref_cfg.get('basis', 'paid_amount')),
    }
    await message.answer(_render_referral_text(str(template), values))
