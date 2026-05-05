from aiogram.fsm.state import State, StatesGroup


class CheckoutStates(StatesGroup):
    collecting_fields = State()
    waiting_discount_code = State()
    waiting_payment_receipt = State()


class WalletTopupStates(StatesGroup):
    waiting_amount = State()
    waiting_payment_receipt = State()
