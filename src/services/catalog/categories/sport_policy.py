import re

from src.services.catalog.categories.l2_sets import RUNNING_L2
from src.services.catalog.categories.registries import (
    NON_STOREFRONT_IMPORT_SPORTS,
    SPORT_MERCHANDISE_L2,
    STOREFRONT_SPORTS,
    TENNIS_MERCHANDISE_L1_LOW,
)
from src.services.catalog.read.scope import CATALOG_TOP_ORDER
from src.utils.labels import normalize_sport_type

_RUN_TITLE_RE = re.compile(
    r"\b(?:"
    r"running|trail\s+run|"
    r"\w+run\s+(?:short|tight|bra|shirt|jacket|hoodie|tee)|"
    r"\brun\s+(?:short|tight|bra|shirt|jacket|hoodie|tee|high)"
    r")\b",
    re.IGNORECASE,
)
_RUNNER_FOOTWEAR_RE = re.compile(
    r"\brunner\b.*\b(?:slipper|sandal|flip\s*flop|flip-flop)\b",
    re.IGNORECASE,
)

_SPORT_MERCHANDISE_CHECK_ORDER: tuple[str, ...] = tuple(
    sport for sport in ("Padel", "Running", "Tennis") if sport in CATALOG_TOP_ORDER
)


# Признак беговой линейки в названии товара.
def title_suggests_running(title: str | None) -> bool:
    text = (title or "").strip()
    if not text:
        return False
    if _RUNNER_FOOTWEAR_RE.search(text):
        return False
    return bool(_RUN_TITLE_RE.search(text))


# Вид спорта из handles: все коллекции, padel приоритетнее tennis.
def sport_from_collection_handles(
    collections: list[tuple[str, str]] | None,
) -> str | None:
    if not collections:
        return None
    found: set[str] = set()
    for handle, _title in collections:
        low = handle.lower().strip()
        if low.startswith("padel"):
            found.add("Padel")
        elif low.startswith("running"):
            found.add("Running")
        elif low.startswith("tennis"):
            found.add("Tennis")
        elif low.startswith("accessories"):
            found.add("Tennis")
    if "Padel" in found:
        return "Padel"
    if "Running" in found:
        return "Running"
    if "Tennis" in found:
        return "Tennis"
    return None


# Есть ли коллекция с префиксом витринного спорта.
def _has_sport_collection(
    collections: list[tuple[str, str]] | None,
    sport: str,
) -> bool:
    if not collections:
        return False
    prefix = sport.lower()
    return any(
        handle.lower().strip().startswith(prefix) for handle, _title in collections
    )


# Strong signal: running merchandise / collections / title.
def _strong_running_sport(
    merchandise_l1: str,
    merchandise_l2: str,
    title: str | None,
    collections: list[tuple[str, str]] | None,
) -> str | None:
    l1_low = merchandise_l1.lower()
    if l1_low.startswith("running") or merchandise_l2 in RUNNING_L2:
        return "Running"
    if title_suggests_running(title):
        return "Running"
    coll_sport = sport_from_collection_handles(collections)
    if coll_sport == "Running":
        return "Running"
    return None


# Strong signal: sport-specific merchandise lines, product_type, collections.
def _strong_sport_from_merchandise(
    merchandise_l1: str,
    merchandise_l2: str,
    product_type: str,
    collections: list[tuple[str, str]] | None,
) -> str | None:
    l1_low = merchandise_l1.lower()
    l2_low = merchandise_l2.lower()
    pt_low = product_type.lower()
    for sport in _SPORT_MERCHANDISE_CHECK_ORDER:
        lines = SPORT_MERCHANDISE_L2.get(sport, frozenset())
        prefix = f"{sport.lower()} "
        if merchandise_l2 in lines or l2_low.startswith(prefix):
            return sport
        if pt_low.startswith(prefix) or product_type in lines:
            return sport
        if l1_low.startswith(prefix) and l1_low != sport.lower():
            return sport
        if _has_sport_collection(collections, sport):
            return sport
    return None


# Strong signal: tennis merchandise L1.
def _strong_tennis_sport(merchandise_l1: str) -> str | None:
    l1_low = merchandise_l1.lower()
    if l1_low.startswith("tennis") or l1_low in TENNIS_MERCHANDISE_L1_LOW:
        return "Tennis"
    return None


# sport_type для Training/Lifestyle/Pickleball и др. non-storefront import.
def _storefront_sport_for_non_storefront_import(
    coll_sport: str | None,
    merchandise_l2: str,
) -> str | None:
    if coll_sport in STOREFRONT_SPORTS:
        return coll_sport
    if merchandise_l2 in RUNNING_L2:
        return "Running"
    return "Tennis"


# Storefront sport: precedence policy (Phase A).
def resolve_storefront_sport(
    import_collection_sport: str | None = None,
    merchandise_l1: str | None = None,
    merchandise_l2: str | None = None,
    product_type: str | None = None,
    title: str | None = None,
    product_collections: list[tuple[str, str]] | None = None,
    supplier_taxonomy_sport: str | None = None,
) -> str | None:
    l1 = (merchandise_l1 or "").strip()
    l2 = (merchandise_l2 or "").strip()
    pt = (product_type or "").strip()
    import_sport = (import_collection_sport or "").strip()
    coll_sport = sport_from_collection_handles(product_collections)

    running = _strong_running_sport(l1, l2, title, product_collections)
    if running:
        return running

    sport_line = _strong_sport_from_merchandise(l1, l2, pt, product_collections)
    if sport_line:
        return sport_line

    tennis = _strong_tennis_sport(l1)
    if tennis:
        return "Tennis"

    if import_sport in STOREFRONT_SPORTS:
        return import_sport

    if coll_sport in STOREFRONT_SPORTS:
        return coll_sport

    taxonomy_sport = (
        normalize_sport_type(supplier_taxonomy_sport)
        or (supplier_taxonomy_sport or "").strip()
        or None
    )
    if taxonomy_sport:
        return taxonomy_sport

    if import_sport in NON_STOREFRONT_IMPORT_SPORTS:
        return _storefront_sport_for_non_storefront_import(coll_sport, l2)

    return None
