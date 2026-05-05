from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_env: str = 'dev'
    app_debug: bool = True

    bot_token: str
    bot_username: str = 'my_sales_bot'
    owner_telegram_id: int

    database_url: str
    redis_url: str = 'redis://127.0.0.1:6379/0'

    api_base_url: str = 'http://127.0.0.1:8000'
    api_host: str = '0.0.0.0'
    api_port: int = 8000
    webhook_secret: str = 'change-me'

    default_currency: str = 'IRT'
    order_auto_cancel_minutes: int = 30
    order_admin_alert_minutes: int = 20

    force_join_channels: str = ''
    require_phone: bool = False
    only_ir_phone: bool = True

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    zarinpal_merchant_id: str | None = None
    zarinpal_callback_url: str | None = None

    card_to_card_number: str | None = None
    card_to_card_holder: str | None = None
    card_to_card_bank: str | None = None

    @property
    def force_join_channel_list(self) -> List[str]:
        return [item.strip() for item in self.force_join_channels.split(',') if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
