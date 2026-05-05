from __future__ import annotations

import random
import string
from datetime import datetime


def generate_order_number(prefix: str = 'ORD') -> str:
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    tail = ''.join(random.choices(string.digits, k=4))
    return f'{prefix}-{ts}-{tail}'


def generate_referral_code(prefix: str = 'RF') -> str:
    token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f'{prefix}{token}'
