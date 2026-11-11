from dataclasses import dataclass
from typing import Any, Mapping, Sequence


# Возвращает количество доступного товара для покупки.
def variant_buyable_qty(
    inventory_quantity: int,
    available: bool,
    available_quantity: int | None = None,
) -> int:
    if available_quantity is not None:
        return max(0, int(available_quantity))
    if not available:
        return 0
    return max(0, int(inventory_quantity))


# Проверяет, доступен ли вариант для покупки.
def variant_is_buyable(
    inventory_quantity: int,
    available: bool,
    available_quantity: int | None = None,
) -> bool:
    return variant_buyable_qty(inventory_quantity, available, available_quantity) > 0


# SQL-выражение для фильтрации доступных вариантов.
def variant_buyable_sql_clause(variant_model: Any) -> Any:
    from sqlalchemy import and_

    # DB facets: available_quantity is computed at read time, not a column.
    return and_(
        variant_model.available.is_(True),
        variant_model.inventory_quantity > 0,
    )


@dataclass(frozen=True, slots=True)
class BuyerStockBadge:
    text: str
    extra_class: str


def _fmt_option(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text or ""


def _variant_in_stock(variant: Mapping[str, Any]) -> bool:
    available_raw = variant.get("available")
    if available_raw is False:
        return False
    available = True if available_raw is None else bool(available_raw)
    return variant_is_buyable(
        int(variant.get("inventory_quantity") or 0),
        available,
        variant.get("available_quantity"),
    )


def _option_keys(variants: Sequence[Mapping[str, Any]]) -> list[str]:
    keys: list[str] = []
    for key in ("option1", "option2", "option3"):
        if any(_fmt_option(v.get(key)) for v in variants):
            keys.append(key)
    return keys


def _matches_selection(
    variant: Mapping[str, Any], selection: Mapping[str, str]
) -> bool:
    for key, value in selection.items():
        if not value:
            continue
        if _fmt_option(variant.get(key)) != value:
            return False
    return True


def _find_matching_variant(
    variants: Sequence[Mapping[str, Any]], selection: Mapping[str, str]
) -> Mapping[str, Any] | None:
    for v in variants:
        if _matches_selection(v, selection):
            return v
    return None


def _is_value_available(
    variants: Sequence[Mapping[str, Any]],
    option_keys: Sequence[str],
    selection: Mapping[str, str],
    key: str,
    value: str,
) -> bool:
    next_sel = {**selection, key: value}
    return any(
        _variant_in_stock(v)
        and all(
            (not next_sel.get(ok) or _fmt_option(v.get(ok)) == next_sel[ok])
            for ok in option_keys
        )
        for v in variants
    )


# Дефолтный вариант как в storefront-variants.js (первые доступные чипы по порядку).
def pick_default_storefront_variant_qty(
    variants: Sequence[Mapping[str, Any]],
) -> int:
    if not variants:
        return 0
    rows = [dict(v) for v in variants]
    option_keys = _option_keys(rows)
    if not option_keys:
        v0 = rows[0]
        return int(v0.get("inventory_quantity") or 0) if _variant_in_stock(v0) else 0

    ordered_values: dict[str, list[str]] = {k: [] for k in option_keys}
    for v in rows:
        for key in option_keys:
            val = _fmt_option(v.get(key))
            if val and val not in ordered_values[key]:
                ordered_values[key].append(val)

    selection: dict[str, str] = {}
    for key in option_keys:
        values = ordered_values[key]
        if not values:
            continue
        chosen = values[0]
        if not _is_value_available(rows, option_keys, selection, key, chosen):
            fallback = next(
                (
                    x
                    for x in values
                    if _is_value_available(rows, option_keys, selection, key, x)
                ),
                "",
            )
            chosen = fallback or chosen
        selection[key] = chosen

    match = _find_matching_variant(rows, selection)
    if not match:
        return 0
    if not _variant_in_stock(match):
        return 0
    if match.get("available_quantity") is not None:
        return int(match.get("available_quantity") or 0)
    return int(match.get("inventory_quantity") or 0)


def buyer_stock_badge(
    available_qty: int,
    ok_from_qty: int,
    low_min_qty: int,
    label_in_stock: str,
    label_low: str,
    label_last: str,
    label_out: str,
) -> BuyerStockBadge:
    # Подпись по qty: в наличии / мало / последний / нет (пороги в коде).
    q = max(0, int(available_qty))
    ok_from = max(1, int(ok_from_qty))
    low_min = max(1, min(int(low_min_qty), ok_from - 1))
    if q <= 0:
        return BuyerStockBadge(text=label_out, extra_class="out-of-stock")
    if q < low_min:
        return BuyerStockBadge(text=label_last, extra_class="stock-badge--last")
    if q < ok_from:
        return BuyerStockBadge(text=label_low, extra_class="stock-badge--low")
    return BuyerStockBadge(text=label_in_stock, extra_class="")


def storefront_stock_status_key(available_qty: int) -> str:
    from src.core.config import settings

    badge = buyer_stock_badge(
        available_qty,
        ok_from_qty=settings.STOCK_OK_FROM_QTY,
        low_min_qty=settings.STOCK_LOW_MIN_QTY,
        label_in_stock=settings.STOCK_LABEL_IN_STOCK,
        label_low=settings.STOCK_LABEL_LOW,
        label_last=settings.STOCK_LABEL_LAST,
        label_out=settings.STOCK_LABEL_OUT,
    )
    if badge.extra_class == "out-of-stock":
        return "out_of_stock"
    if badge.extra_class == "stock-badge--last":
        return "last"
    if badge.extra_class == "stock-badge--low":
        return "low"
    return "in_stock"


def stock_display_client_dict(
    *,
    ok_from_qty: int,
    low_min_qty: int,
    label_in_stock: str,
    label_low: str,
    label_last: str,
    label_out: str,
) -> dict[str, Any]:
    # Конфиг для window.__STOCK_DISPLAY__ / Mini App.
    return {
        "okFromQty": ok_from_qty,
        "lowMinQty": low_min_qty,
        "labels": {
            "inStock": label_in_stock,
            "low": label_low,
            "last": label_last,
            "out": label_out,
        },
    }
