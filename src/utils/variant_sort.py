import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from src.utils.labels import (
    _GRIP_SIZE_OPTION_VALUES,
    OPTION_VALUE_LABELS_RU,
    resolve_variant_option_label,
)

_SIZE_LITERAL_ORDER: dict[str, Decimal] = {
    "xxs": Decimal("10"),
    "xs": Decimal("20"),
    "s": Decimal("30"),
    "m": Decimal("40"),
    "l": Decimal("50"),
    "xl": Decimal("60"),
    "xxl": Decimal("70"),
    "2xl": Decimal("70"),
    "3xl": Decimal("80"),
    "4xl": Decimal("90"),
}


# Парсит строку размера поставщика в числовой ключ сортировки.
def parse_variant_option_sort_key(
    option_key: str,
    value: str | None,
    category_l2: str | None = None,
) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    label = resolve_variant_option_label(
        option_key,
        category_l2=category_l2,
        option_values=[raw],
    )
    if label in {"Цвет", "Поверхность", "Струны", "Опция", "Опция 3"}:
        return None

    lowered = raw.lower().replace("-", " ")
    if lowered in OPTION_VALUE_LABELS_RU:
        return None
    if lowered in _GRIP_SIZE_OPTION_VALUES:
        return Decimal(int(lowered))
    letter_key = lowered.replace(" ", "")
    if letter_key in _SIZE_LITERAL_ORDER:
        return _SIZE_LITERAL_ORDER[letter_key]

    normalized = raw.replace(",", ".")
    fraction_match = re.match(r"^(\d+)\s+(\d+)/(\d+)$", normalized, flags=re.IGNORECASE)
    if fraction_match:
        base = Decimal(fraction_match.group(1))
        numerator = Decimal(fraction_match.group(2))
        denominator = Decimal(fraction_match.group(3))
        if denominator != 0:
            return base + numerator / denominator

    range_match = re.match(
        r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$",
        normalized,
    )
    if range_match:
        try:
            return Decimal(range_match.group(1))
        except InvalidOperation:
            return None

    decimal_match = re.match(r"^(\d+(?:\.\d+)?)$", normalized)
    if decimal_match:
        try:
            return Decimal(decimal_match.group(1))
        except InvalidOperation:
            return None
    return None


# Записывает option*_sort_key на вариант при импорте/обновлении.
def apply_variant_option_sort_keys(
    variant: object,
    category_l2: str | None,
) -> None:
    for option_key in ("option1", "option2", "option3"):
        raw = getattr(variant, option_key, None)
        parsed = parse_variant_option_sort_key(
            option_key,
            str(raw) if raw is not None else None,
            category_l2=category_l2,
        )
        setattr(variant, f"{option_key}_sort_key", parsed)


# Сортирует уникальные значения option по сохранённым sort_key вариантов.
def sort_option_values_from_variants(
    variants: Sequence[object],
    option_key: str,
    values: list[str],
) -> list[str]:
    if len(values) <= 1:
        return list(values)

    sort_attr = f"{option_key}_sort_key"
    sort_by_value: dict[str, Decimal] = {}
    for variant in variants:
        text = str(getattr(variant, option_key, None) or "").strip()
        if not text or text in sort_by_value:
            continue
        stored = getattr(variant, sort_attr, None)
        if stored is not None:
            sort_by_value[text] = Decimal(str(stored))

    if not sort_by_value or not all(value in sort_by_value for value in values):
        return list(values)
    return sorted(values, key=lambda value: sort_by_value[value])
