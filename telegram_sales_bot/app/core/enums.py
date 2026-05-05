from enum import StrEnum


class ProductKind(StrEnum):
    SERVICE = 'service'
    DIGITAL = 'digital'
    FILE = 'file'
    CODE = 'code'
    SUBSCRIPTION = 'subscription'


class DeliveryKind(StrEnum):
    MANUAL = 'manual'
    AUTO_TEXT = 'auto_text'


class OrderStatus(StrEnum):
    NEW = 'new'
    WAITING_FOR_INFO = 'waiting_for_info'
    WAITING_FOR_PAYMENT = 'waiting_for_payment'
    PAID = 'paid'
    PENDING_MANUAL_REVIEW = 'pending_manual_review'
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    NEEDS_ATTENTION = 'needs_attention'


class PaymentStatus(StrEnum):
    INITIATED = 'initiated'
    WAITING_RECEIPT = 'waiting_receipt'
    PENDING_VERIFY = 'pending_verify'
    VERIFIED = 'verified'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class PaymentMethod(StrEnum):
    ZARINPAL = 'zarinpal'
    PLISIO = 'plisio'
    CARD_TO_CARD = 'card_to_card'
    CRYPTO_MANUAL = 'crypto_manual'
    WALLET = 'wallet'


class TicketStatus(StrEnum):
    OPEN = 'open'
    ANSWERED = 'answered'
    CLOSED = 'closed'


class BroadcastStatus(StrEnum):
    DRAFT = 'draft'
    SCHEDULED = 'scheduled'
    SENT = 'sent'
    FAILED = 'failed'
