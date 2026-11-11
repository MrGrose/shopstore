import json
import re
from pathlib import Path
from typing import Any

DEFAULT_JSON_PATH = Path(__file__).resolve().parent / "shoe_size" / "shoe-sizes.json"

AUDIENCE_ORDER: tuple[str, ...] = ("men", "women", "kids", "unisex")

AUDIENCE_LABEL_RU: dict[str, str] = {
    "men": "Мужские",
    "women": "Женские",
    "kids": "Детские",
    "unisex": "Унисекс",
}

# Допустимые EU-границы секции: скрейп часто копирует одну линейку на kids/men/women.
AUDIENCE_EU_RANGE: dict[str, tuple[float, float]] = {
    "kids": (16.0, 40.0),
    "women": (34.0, 43.5),
    "men": (36.0, 50.0),
    "unisex": (36.0, 50.0),
}

_EU_RANGE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$")
_EU_FRACTION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s+(\d+)\s*/\s*(\d+)$")
_EU_SIMPLE_RE = re.compile(r"^\d+(?:\.\d+)?$")


# Нормализует бренд для lookup в shoe-sizes.json.
def normalize_brand(brand: str | None) -> str:
    return (brand or "").strip().lower()


# Нормализует EU-размер для дедупликации строк charts.
def normalize_eu_simple(eu: str | None) -> str:
    return (eu or "").strip().lower().replace(",", ".")


# Парсит EU как отрезок: "42.5" → (42.5, 42.5), "36 2/3" → дробь, "17-18" → диапазон.
def parse_eu_span(eu: str | None) -> tuple[float, float] | None:
    text = normalize_eu_simple(eu)
    if not text:
        return None
    range_match = _EU_RANGE_RE.fullmatch(text)
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        if high < low:
            low, high = high, low
        return low, high
    fraction_match = _EU_FRACTION_RE.fullmatch(text)
    if fraction_match:
        value = float(fraction_match.group(1)) + int(fraction_match.group(2)) / int(
            fraction_match.group(3)
        )
        return value, value
    if _EU_SIMPLE_RE.fullmatch(text):
        value = float(text)
        return value, value
    return None


# True, если EU строки попадает в диапазон audience.
def eu_allowed_for_audience(audience: str, eu: str | None) -> bool:
    bounds = AUDIENCE_EU_RANGE.get(audience)
    if bounds is None:
        return True
    span = parse_eu_span(eu)
    if span is None:
        return False
    low, high = span
    return low >= bounds[0] and high <= bounds[1]


# Форматирует см для отображения в RU (26,5).
def format_cm_ru(value: float) -> str:
    text = f"{value:.1f}".replace(".", ",")
    if text.endswith(",0"):
        return text[:-2]
    return text


# Загружает shoe-sizes.json и индексирует строки по brand_norm.
def _load_charts_by_brand_norm() -> dict[str, list[dict[str, Any]]]:
    if not DEFAULT_JSON_PATH.is_file():
        return {}
    payload = json.loads(DEFAULT_JSON_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("shoe-sizes.json должен быть JSON-массивом")
    grouped: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or "").strip()
        audience = str(item.get("audience") or "").strip()
        eu = str(item.get("eu") or "").strip()
        foot_length_cm = item.get("foot_length_cm")
        if not brand or audience not in AUDIENCE_LABEL_RU or not eu:
            continue
        if foot_length_cm is None:
            continue
        if not eu_allowed_for_audience(audience, eu):
            continue
        brand_norm = normalize_brand(brand)
        row_key = (brand_norm, audience, normalize_eu_simple(eu))
        grouped.setdefault(brand_norm, {})[row_key] = {
            "brand": brand,
            "audience": audience,
            "eu": eu,
            "uk": str(item.get("uk") or "").strip() or None,
            "us": str(item.get("us") or "").strip() or None,
            "foot_length_cm": float(foot_length_cm),
        }
    return {brand_norm: list(rows.values()) for brand_norm, rows in grouped.items()}


CHARTS_BY_BRAND_NORM: dict[str, list[dict[str, Any]]] = _load_charts_by_brand_norm()


# Проверяет, есть ли таблица размеров для бренда.
def brand_has_size_chart(brand: str | None) -> bool:
    norm = normalize_brand(brand)
    if not norm:
        return False
    return bool(CHARTS_BY_BRAND_NORM.get(norm))


# Возвращает таблицу размеров бренда, сгруппированную по audience.
def get_brand_size_chart(brand: str | None) -> dict[str, Any] | None:
    norm = normalize_brand(brand)
    if not norm:
        return None
    rows = CHARTS_BY_BRAND_NORM.get(norm)
    if not rows:
        return None
    sections: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        audience = str(row["audience"])
        sections.setdefault(audience, []).append(
            {
                **row,
                "foot_length_cm_label": format_cm_ru(float(row["foot_length_cm"])),
            }
        )
    for audience_rows in sections.values():
        audience_rows.sort(key=lambda row: float(row["foot_length_cm"]))
    audiences = [key for key in AUDIENCE_ORDER if key in sections]
    display_brand = str(rows[0]["brand"])
    return {
        "brand": display_brand,
        "brand_norm": norm,
        "audiences": audiences,
        "sections": sections,
        "audience_labels": AUDIENCE_LABEL_RU,
    }
