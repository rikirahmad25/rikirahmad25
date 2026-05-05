import re

IR_PHONE_REGEX = re.compile(r'^(?:\+98|0)?9\d{9}$')


def normalize_iran_phone(phone: str) -> str:
    digits = re.sub(r'[^\d+]', '', phone)
    if digits.startswith('+98'):
        return '0' + digits[3:]
    if digits.startswith('98'):
        return '0' + digits[2:]
    return digits


def is_valid_iran_phone(phone: str) -> bool:
    return bool(IR_PHONE_REGEX.match(normalize_iran_phone(phone)))
