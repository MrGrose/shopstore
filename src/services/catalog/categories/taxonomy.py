import re

from src.services.catalog.categories.l2_sets import (
    ACCESSORIES_PRODUCT_TYPES,
    APPAREL_L2,
    PADEL_RACKET_L2,
    RUNNING_L2,
    TENNIS_RACKET_L2,
)
from src.services.catalog.categories.l3_registry import (
    PADEL_RACKET_L3_TITLE_RULES,
    RUNNING_SHOE_L3_TITLE_RULES,
    TENNIS_SHOE_L3_TITLE_RULES,
)
from src.services.catalog.categories.sport_policy import resolve_storefront_sport
from src.utils.labels import TENNIS_SHOES_BASE_L2

_TENNIS_RACKET_L2_LOW = frozenset(name.lower() for name in TENNIS_RACKET_L2)
_TENNIS_SHOE_L1_HINTS = ("slipper", "sneaker", "trainer")


# Подбирает category_l3 по category_l2 и названию товара.
def infer_category_l3(
    category_l2: str | None,
    title: str | None = None,
) -> str | None:
    l2 = (category_l2 or "").strip()
    text = (title or "").strip()
    if not l2 or not text:
        return None

    rules: tuple[tuple[re.Pattern[str], str], ...]
    if l2 in PADEL_RACKET_L2:
        rules = PADEL_RACKET_L3_TITLE_RULES
    elif l2 in TENNIS_SHOES_BASE_L2:
        rules = TENNIS_SHOE_L3_TITLE_RULES
    elif l2 == "Running shoes":
        rules = RUNNING_SHOE_L3_TITLE_RULES
    else:
        return None

    for pattern, l3 in rules:
        if pattern.search(text):
            return l3
    return None


# Merchandise L1 для padel product_type.
def _padel_merchandise_l1(low: str, pt: str) -> str:
    if "shoe" in low:
        return "Padel shoes"
    if "racket" in low or pt == "Padel racket":
        return "Padel rackets"
    if "ball" in low:
        return "Padel balls"
    return "Padel"


# Merchandise L1 для tennis product_type по нормализованной строке.
def _tennis_merchandise_l1(low: str) -> str | None:
    if low in _TENNIS_RACKET_L2_LOW:
        return "Tennis rackets"
    if low in {"tennis shoes", "shoes"} or any(
        hint in low for hint in _TENNIS_SHOE_L1_HINTS
    ):
        return "Tennis shoes"
    if low == "tennis balls":
        return "Tennis balls"
    return None


# Merchandise L1 по import_collection_sport (fallback).
def _merchandise_l1_from_import_sport(import_sport: str) -> str | None:
    if import_sport == "Accessories":
        return "Accessories"
    if import_sport == "Running":
        return "Running"
    if import_sport == "Padel":
        return "Padel"
    if import_sport in {"Tennis", "Training", "Lifestyle"}:
        return "Tennis clothing"
    return import_sport or None


# Merchandise L1 для GraphQL-импорта (как item_category в GTM).
def resolve_merchandise_l1(
    product_type: str | None,
    import_collection_sport: str | None = None,
) -> str | None:
    pt = (product_type or "").strip()
    if not pt:
        return None
    low = pt.lower()
    if pt in ACCESSORIES_PRODUCT_TYPES or "pickleball" in low:
        return "Accessories"
    if low.startswith("padel"):
        return _padel_merchandise_l1(low, pt)
    if pt in RUNNING_L2 or (import_collection_sport == "Running" and "shoe" in low):
        return "Running shoes" if "shoe" in low else "Running"
    tennis_l1 = _tennis_merchandise_l1(low)
    if tennis_l1:
        return tennis_l1
    if pt in APPAREL_L2:
        if import_collection_sport == "Running":
            return "Running"
        if import_collection_sport == "Padel":
            return "Padel clothing"
        return "Tennis clothing"
    return _merchandise_l1_from_import_sport((import_collection_sport or "").strip())


# Top-категория витрины (sport_type); thin wrapper над sport_policy.
def resolve_storefront_sport_type(
    import_collection_sport: str | None = None,
    merchandise_l1: str | None = None,
    merchandise_l2: str | None = None,
    title: str | None = None,
    product_collections: list[tuple[str, str]] | None = None,
    product_type: str | None = None,
    supplier_taxonomy_sport: str | None = None,
) -> str | None:
    return resolve_storefront_sport(
        import_collection_sport=import_collection_sport,
        merchandise_l1=merchandise_l1,
        merchandise_l2=merchandise_l2,
        product_type=product_type,
        title=title,
        product_collections=product_collections,
        supplier_taxonomy_sport=supplier_taxonomy_sport,
    )
