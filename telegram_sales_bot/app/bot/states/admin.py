from aiogram.fsm.state import State, StatesGroup


class AdminProductStates(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_price = State()
    waiting_usd_rate = State()
    waiting_stock = State()
    waiting_show_stock = State()
    waiting_allow_quantity = State()
    waiting_delivery_payload = State()
    waiting_delete_delivery_number = State()
    waiting_edit_value = State()
    waiting_category_title = State()
    waiting_field_prompt = State()


class AdminBroadcastStates(StatesGroup):
    waiting_content = State()
    waiting_direct_target = State()
    waiting_direct_content = State()


class AdminSettingsStates(StatesGroup):
    waiting_value = State()
    waiting_crypto_wallet = State()
    waiting_backup_restore = State()


class AdminDiscountStates(StatesGroup):
    waiting_create = State()
    waiting_code = State()
    waiting_value = State()
    waiting_max_uses = State()
    waiting_per_user_limit = State()
    waiting_min_amount = State()


class AdminTutorialStates(StatesGroup):
    waiting_title = State()
    waiting_type = State()
    waiting_content = State()
    # نام‌های قدیمی برای سازگاری داخلی نگه داشته شده‌اند.
    waiting_description = State()
    waiting_video = State()


class AdminOrderStates(StatesGroup):
    waiting_search = State()
    waiting_manual_delivery_text = State()


class AdminManageStates(StatesGroup):
    waiting_new_admin_identifier = State()
    waiting_user_identifier = State()
    waiting_wallet_user_identifier = State()
    waiting_wallet_amount = State()


class AdminLotteryStates(StatesGroup):
    waiting_draw = State()
