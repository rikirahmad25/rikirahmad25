from __future__ import annotations

from app.core.enums import PaymentMethod
from app.db.models import User
from app.services.payments.base import PaymentProvider
from app.services.payments.card_to_card import CardToCardProvider
from app.services.payments.crypto_manual import CryptoManualProvider
from app.services.payments.plisio import PlisioProvider
from app.services.payments.wallet import WalletProvider
from app.services.payments.zarinpal import ZarinPalProvider


class PaymentRegistry:
    def __init__(self, session, user: User | None = None):
        self.session = session
        self.user = user

    def get(self, method: str) -> PaymentProvider:
        if method == PaymentMethod.CARD_TO_CARD.value:
            return CardToCardProvider(self.session)
        if method == PaymentMethod.CRYPTO_MANUAL.value:
            return CryptoManualProvider(self.session)
        if method == PaymentMethod.WALLET.value:
            if not self.user:
                raise ValueError('Wallet provider requires a user.')
            return WalletProvider(self.session, self.user)
        if method == PaymentMethod.ZARINPAL.value:
            return ZarinPalProvider(self.session)
        if method == PaymentMethod.PLISIO.value:
            return PlisioProvider(self.session)
        raise ValueError(f'Unknown payment method: {method}')
