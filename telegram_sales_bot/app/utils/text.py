from decimal import Decimal


def money(value: Decimal | int | float | str) -> str:
    amount = Decimal(str(value))
    return f'{amount:,.0f} تومان'
