from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import PlainSerializer


# Форматирует сумму в EUR для админки (2 знака после запятой).
def format_eur(value: Decimal | int | float | str | None) -> str:
    if value is None:
        return "0.00"
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# Форматирует сумму в RUB для админки (2 знака после запятой).
def format_rub(value: Decimal | int | float | str | None) -> str:
    return format_eur(value)


# Разбивает целую часть числа по три цифры (узкий пробел).
def _group_integer_digits(value: int) -> str:
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if len(digits) <= 3:
        return f"{sign}{digits}"
    parts: list[str] = []
    while digits:
        parts.append(digits[-3:])
        digits = digits[:-3]
    return sign + "\u00a0".join(reversed(parts))


# Форматирует целое число с группировкой тысяч (0 остаётся «0»).
def format_grouped_count(value: int | None) -> str:
    if value is None:
        return "0"
    return _group_integer_digits(int(value))


# Форматирует целое число для финансового отчёта (0 → «—»).
def format_finance_count(value: int | None) -> str:
    if value is None or value == 0:
        return "—"
    return _group_integer_digits(int(value))


# Форматирует decimal с группировкой тысяч и запятой в дробной части.
def format_grouped_amount(value: Decimal, places: int = 2) -> str:
    quantized = value.quantize(
        Decimal("0." + "0" * places),
        rounding=ROUND_HALF_UP,
    )
    text = format(quantized, "f")
    if "." in text:
        int_part, frac_part = text.split(".", 1)
    else:
        int_part, frac_part = text, ""
    grouped = _group_integer_digits(int(int_part))
    if places <= 0:
        return grouped
    return f"{grouped},{frac_part}"


# Форматирует сумму в RUB для ячеек финансового отчёта (0 → «—»).
def format_finance_rub(
    value: Decimal | int | float | str | None,
    with_symbol: bool = True,
) -> str:
    if value is None:
        return "—"
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal_value == 0:
        return "—"
    amount = format_grouped_amount(decimal_value)
    if not with_symbol:
        return amount
    return f"{amount}\u00a0₽"


# Доля part от whole в процентах для summary-карточек.
def finance_margin_percent(
    part: Decimal | int | float | str | None,
    whole: Decimal | int | float | str | None,
) -> str | None:
    if part is None or whole is None:
        return None
    part_value = part if isinstance(part, Decimal) else Decimal(str(part))
    whole_value = whole if isinstance(whole, Decimal) else Decimal(str(whole))
    if whole_value == 0:
        return None
    pct = (part_value / whole_value * Decimal("100")).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    text = format(pct, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


# Средний чек: оборот / число заказов для summary-карточек.
def finance_avg_order_rub(
    turnover: Decimal | int | float | str | None,
    orders_count: int | None,
) -> str | None:
    if orders_count is None or orders_count <= 0:
        return None
    turnover_value = (
        turnover if isinstance(turnover, Decimal) else Decimal(str(turnover or 0))
    )
    if turnover_value == 0:
        return None
    avg = (turnover_value / Decimal(int(orders_count))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return format_finance_rub(avg)


# Округляет денежное значение вверх до целых рублей.
def ceil_rub(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return decimal_value.to_integral_value(rounding=ROUND_CEILING)


# Сериализует сумму в рублях в JSON строкой целых рублей (без float в ответе API).
def serialize_rub_money_json(value: Any) -> str:
    if value is None:
        return "0"
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    normalized = ceil_rub(decimal_value) or Decimal("0")
    return str(int(normalized))


# Decimal в ответах API: в Python — Decimal, в JSON — строка целых рублей.
RubMoneyJSON = Annotated[
    Decimal,
    PlainSerializer(serialize_rub_money_json, return_type=str, when_used="json"),
]
