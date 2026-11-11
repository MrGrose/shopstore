from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

# Тип для определения тональности изменения цены.
PriceDeltaTone = Literal["higher", "lower", "same"]


# Статус автопроверки TP для одной позиции (без префикса «Автопроверка TP»).
def format_supplier_check_status(raw: Mapping[str, object]) -> str:
    found = raw.get("found") is True
    inventory = raw.get("inventory_quantity")
    available = raw.get("available")
    if found:
        if inventory is not None:
            return f"вариант найден, {inventory} шт."
        if available is True:
            return "вариант найден, в наличии"
        return "вариант найден"
    return "вариант не найден"


# Текст сравнения цены TP с ценой в заказе.
def format_supplier_check_price_delta_text(
    supplier_price_eur: object,
    captured_price_eur: object,
    eur_delta_abs: object,
) -> tuple[PriceDeltaTone, str] | None:
    if not supplier_price_eur or not captured_price_eur or not eur_delta_abs:
        return None
    try:
        tp_value = Decimal(str(supplier_price_eur))
        captured_value = Decimal(str(captured_price_eur))
    except Exception:
        return None
    if tp_value > captured_value:
        return "higher", f"дороже на {eur_delta_abs} EUR"
    if tp_value < captured_value:
        return "lower", f"дешевле на {eur_delta_abs} EUR"
    return "same", "цена без изменений"


# Полная строка цены TP для TG и admin UI.
def format_supplier_check_price_line(raw: Mapping[str, object]) -> str | None:
    price = raw.get("supplier_price_eur")
    if not price:
        return None
    captured = raw.get("captured_price_eur")
    delta = raw.get("eur_delta_abs")
    price_line = f"Цена TP: {price} EUR"
    if captured:
        price_line += f" (у нас — {captured} EUR)"
    delta_info = (
        format_supplier_check_price_delta_text(price, captured, delta)
        if captured
        else None
    )
    if delta_info is not None:
        price_line += f" · {delta_info[1]}"
    return price_line


# Добавляет display-поля для admin partial и TG.
def enrich_supplier_check_display(raw: Mapping[str, object]) -> dict[str, object]:
    enriched = dict(raw)
    enriched["status_text"] = format_supplier_check_status(raw)
    price = raw.get("supplier_price_eur")
    captured = raw.get("captured_price_eur")
    delta = raw.get("eur_delta_abs")
    enriched["price_line_text"] = format_supplier_check_price_line(raw)
    if price:
        prefix = f"Цена TP: {price} EUR"
        if captured:
            prefix += f" (у нас — {captured} EUR)"
        enriched["price_prefix_text"] = prefix
    delta_info = (
        format_supplier_check_price_delta_text(price, captured, delta)
        if price and captured
        else None
    )
    if delta_info is not None:
        tone, delta_text = delta_info
        enriched["price_delta_tone"] = tone
        enriched["price_delta_text"] = delta_text
    return enriched
