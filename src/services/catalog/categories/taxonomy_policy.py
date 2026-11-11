import re
from dataclasses import dataclass
from typing import Any

from src.services.catalog.categories.l2_sets import (
    ACCESSORIES_PRODUCT_TYPES,
    APPAREL_CORE_L2,
    RUNNING_ACCESSORIES_NAV_L2,
    TENNIS_ACCESSORIES_NAV_L2,
)
from src.services.catalog.categories.registries import (
    ACCESSORY_COLLECTION_MARKERS,
    APPAREL_COLLECTION_HANDLE_MARKERS,
    APPAREL_L2_BY_COLLECTION_HANDLE_SUFFIX,
    APPAREL_PARENT_BY_SPORT,
    COLLECTION_HANDLE_FRAGMENT_TO_L2,
    COLLECTION_HANDLE_FRAGMENT_TO_L3,
    COMPRESSION_SLEEVE_SIGNALS,
    ITEM_CATEGORY3_TO_L2,
    MERCHANDISE_L1_LABELS,
    NAV_L2_BY_SPORT,
    ORPHAN_L2_NORMALIZATION,
    PARENT_APPAREL_BUCKETS,
    PRODUCT_TYPE_IN_PARENT_TO_L2,
    RUNNING_ACCESSORIES_HANDLE_FRAGMENT_TO_L3,
    RUNNING_ACCESSORIES_PRODUCT_TYPE_TO_L3,
    RUNNING_TOPS_TO_SHIRTS_FRAGMENT,
    STOREFRONT_SPORTS,
    TENNIS_ACCESSORIES_HANDLE_FRAGMENT_TO_L3,
    TENNIS_ACCESSORIES_L3_REFINEMENT_L2,
    TENNIS_RACKET_ACCESSORIES_L2,
)
from src.services.catalog.text import text_or_none

_TITLE_PATH_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")

# Title → leaf L2 только для Padel clothing без L3 (см. refine_*_apparel_l2).
_PADEL_CLOTHING_TITLE_L2_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bshorts\b", re.I), "Shorts"),
    (re.compile(r"\bskirts?\b", re.I), "Skirts"),
    (re.compile(r"\bdress(?:es)?\b", re.I), "Dresses"),
    (re.compile(r"\bpolo\b", re.I), "Shirts"),
    (re.compile(r"\b(hoody|hoodie|sweatshirt)\b", re.I), "Hoodies & Sweaters"),
    (re.compile(r"\b(training\s+)?jackets?\b", re.I), "Jackets"),
    (re.compile(r"\b(tights?|leggings?|malla)\b", re.I), "Pants"),
    (re.compile(r"\b(training\s+)?pants\b", re.I), "Pants"),
    (re.compile(r"\bt-?shirts?\b", re.I), "Shirts"),
    (re.compile(r"\blong\s+sleeve\b", re.I), "Shirts"),
    (re.compile(r"\btank\s+tops?\b", re.I), "Tops"),
    (re.compile(r"\btops?\b", re.I), "Tops"),
    (re.compile(r"\bvests?\b", re.I), "Jackets"),
    (re.compile(r"\btracksuits?\b", re.I), "Tracksuits"),
    (re.compile(r"\bscapri\b", re.I), "Pants"),
    (re.compile(r"\bcapri\b", re.I), "Pants"),
)

_MAKEUP_BAG_TITLE_RE = re.compile(r"make\s*-?\s*up\s*bag", re.I)

# Title → leaf L3 для Tennis accessories без L3.
# См. pick_l3_from_tennis_accessories_handles.
_TENNIS_ACCESSORIES_TITLE_L3_RULES: tuple[
    tuple[re.Pattern[str], str, frozenset[str]], ...
] = (
    (re.compile(r"\bball marker\b", re.I), "Ball clips", TENNIS_RACKET_ACCESSORIES_L2),
    (re.compile(r"\bbutt cap\b", re.I), "Grips", TENNIS_RACKET_ACCESSORIES_L2),
    (re.compile(r"\bgrip hose\b", re.I), "Grips", TENNIS_RACKET_ACCESSORIES_L2),
    (re.compile(r"\bstencil\b", re.I), "Stencil", TENNIS_RACKET_ACCESSORIES_L2),
)

_ITEM_CATEGORY_ROLE_SPORT_NAMESPACE = "sport_namespace"
_ITEM_CATEGORY_ROLE_MERCHANDISE_L1 = "merchandise_l1"


@dataclass(frozen=True)
class ProjectedMerchandiseTaxonomy:
    category_l1: str | None
    category_l2: str | None
    category_l3: str | None
    l2_is_parent_bucket: bool


# Нормализует токен категории.
def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


# Роль item_category: sport namespace или merchandise L1.
def classify_item_category_role(item_category: str | None) -> str:
    raw = _norm(item_category)
    if not raw:
        return _ITEM_CATEGORY_ROLE_MERCHANDISE_L1
    if raw in STOREFRONT_SPORTS:
        return _ITEM_CATEGORY_ROLE_SPORT_NAMESPACE
    if raw in MERCHANDISE_L1_LABELS:
        return _ITEM_CATEGORY_ROLE_MERCHANDISE_L1
    return _ITEM_CATEGORY_ROLE_MERCHANDISE_L1


# Parent apparel bucket для витринного спорта.
def apparel_parent_for_sport(storefront_sport: str | None) -> str | None:
    sport = _norm(storefront_sport)
    if not sport:
        return None
    return APPAREL_PARENT_BY_SPORT.get(sport)


# Линия с префиксом витринного спорта (Padel shoes, Tennis rackets, …).
def _is_sport_prefixed_line(value: str, storefront_sport: str | None) -> bool:
    line = _norm(value)
    sport = _norm(storefront_sport)
    if not line or not sport:
        return False
    prefix = f"{sport.lower()} "
    return line.lower().startswith(prefix)


# Проекция raw supplier_taxonomy → storefront merchandise L1/L2/L3.
def project_supplier_merchandise_taxonomy(
    supplier_taxonomy: dict[str, Any] | None,
    storefront_sport: str | None = None,
    product_type: str | None = None,
) -> ProjectedMerchandiseTaxonomy:
    taxonomy = supplier_taxonomy if isinstance(supplier_taxonomy, dict) else {}
    item_category = _norm(text_or_none(taxonomy.get("item_category"))) or None
    item_category2 = _norm(text_or_none(taxonomy.get("item_category2"))) or None
    item_category3 = _norm(text_or_none(taxonomy.get("item_category3"))) or None
    pt = _norm(product_type) or None
    role = classify_item_category_role(item_category)

    if role == _ITEM_CATEGORY_ROLE_MERCHANDISE_L1:
        category_l1 = item_category
        category_l2 = item_category2 or pt
        category_l3 = item_category3
        l2_parent = bool(category_l2 and category_l2 in PARENT_APPAREL_BUCKETS)
        return ProjectedMerchandiseTaxonomy(
            category_l1=category_l1,
            category_l2=category_l2,
            category_l3=category_l3,
            l2_is_parent_bucket=l2_parent,
        )

    line = item_category2 or pt
    if line in PARENT_APPAREL_BUCKETS:
        category_l1 = line
        category_l2 = line
        category_l3 = item_category3
        return ProjectedMerchandiseTaxonomy(
            category_l1=category_l1,
            category_l2=category_l2,
            category_l3=category_l3,
            l2_is_parent_bucket=True,
        )

    if line in APPAREL_CORE_L2:
        parent = apparel_parent_for_sport(storefront_sport)
        return ProjectedMerchandiseTaxonomy(
            category_l1=parent or item_category,
            category_l2=line,
            category_l3=item_category3,
            l2_is_parent_bucket=False,
        )

    if line and (
        _is_sport_prefixed_line(line, storefront_sport)
        or _is_sport_prefixed_line(line, item_category)
    ):
        return ProjectedMerchandiseTaxonomy(
            category_l1=line,
            category_l2=line,
            category_l3=item_category3,
            l2_is_parent_bucket=False,
        )

    if line:
        return ProjectedMerchandiseTaxonomy(
            category_l1=line,
            category_l2=line,
            category_l3=item_category3,
            l2_is_parent_bucket=line in PARENT_APPAREL_BUCKETS,
        )

    return ProjectedMerchandiseTaxonomy(
        category_l1=item_category,
        category_l2=pt,
        category_l3=item_category3,
        l2_is_parent_bucket=False,
    )


# Можно ли уточнять L2 из collections при parent bucket.
def supplier_l2_allows_collection_override(
    supplier_taxonomy: dict[str, Any] | None,
    projected_l2_is_parent: bool,
) -> bool:
    if projected_l2_is_parent:
        return True
    if not isinstance(supplier_taxonomy, dict):
        return True
    return not bool(text_or_none(supplier_taxonomy.get("item_category2")))


# Нужно ли пытаться уточнить видимый container L2 (sport-scoped).
def _refinement_allowed_for_l2(
    category_l2: str | None,
    storefront_sport: str | None,
) -> bool:
    l2 = _norm(category_l2)
    sport = _norm(storefront_sport)
    if not l2 or not sport:
        return False
    if l2 in {"Running clothes", "Running apparel"}:
        return sport == "Running"
    if l2 == "Outerwear":
        return sport in {"Running", "Padel", "Tennis"}
    if l2 == "Padel clothing":
        return sport == "Padel"
    return False


# Leaf L2 из title для apparel parent/outerwear bucket без L3.
def _pick_padel_clothing_l2_from_title(title: str | None) -> str | None:
    text = (title or "").strip()
    if not text:
        return None
    for pattern, l2 in _PADEL_CLOTHING_TITLE_L2_RULES:
        if pattern.search(text):
            return l2
    return None


# Уточняет Padel clothing по title, если collections/supplier не дали leaf L2.
def _apply_padel_clothing_title_refinement(
    category_l2: str | None,
    storefront_sport: str | None,
    title: str | None,
) -> str | None:
    if _norm(storefront_sport) != "Padel" or _norm(category_l2) != "Padel clothing":
        return category_l2
    return _pick_padel_clothing_l2_from_title(title) or category_l2


# Уточняет supplier Outerwear bucket по title (часто = misc apparel, не куртки).
def _apply_outerwear_title_refinement(
    category_l2: str | None,
    storefront_sport: str | None,
    title: str | None,
) -> str | None:
    if _norm(category_l2) != "Outerwear":
        return category_l2
    if _norm(storefront_sport) not in {"Padel", "Tennis", "Running"}:
        return category_l2
    return _pick_padel_clothing_l2_from_title(title) or category_l2


_HEADGEAR_TITLE_RE = re.compile(r"\b(cap|visor|gorra|kappe)\b", re.I)
_WRISTBAND_TITLE_RE = re.compile(r"\bwrist\s*band\b", re.I)
_WATER_BOTTLE_TITLE_RE = re.compile(
    r"\b(water\s*bottle|shaker|hydration|strohhalm)\b", re.I
)
_PRESSURIZER_TITLE_RE = re.compile(r"\bpressurizer\b", re.I)
_KEYRING_TITLE_RE = re.compile(r"\bkey\s*ring\b", re.I)
_BALL_CLIP_TITLE_RE = re.compile(r"\bball\s*clip\b", re.I)
_COSMETICS_TITLE_RE = re.compile(
    r"\b(sunscreen|cosmetic|lip\s*balm|sun\s*spray)\b", re.I
)
_MINI_RACKET_TITLE_RE = re.compile(r"\bmini\s*racket\b", re.I)


# Уточняет supplier taxonomy перед storefront rule matching (backfill/reconcile).
def refine_storefront_mapping_taxonomy(
    category_l1: str | None,
    category_l2: str | None,
    category_l3: str | None,
    storefront_sport: str | None,
    title: str | None,
) -> tuple[str | None, str | None, str | None]:
    l1 = _norm(category_l1) or None
    l2 = _norm(category_l2) or None
    l3 = _norm(category_l3) or None
    text = title or ""

    if l2 == "Padel clothing" and _WRISTBAND_TITLE_RE.search(text):
        return "Padel accessories", "Padel accessories", None

    if l2 == "Padel accessories" and _HEADGEAR_TITLE_RE.search(text):
        return "Padel clothing", "Headgear", None

    if l2 == "Headgear" and _norm(storefront_sport) == "Tennis":
        if re.search(r"\bheadband\b", text, re.I):
            return "Tennis clothing", "Accessories", "Headbands"
        if re.search(r"\bbandana\b", text, re.I):
            return "Tennis clothing", "Accessories", "Bandanas"
        if re.search(r"\bbeanie\b", text, re.I):
            return "Tennis clothing", "Accessories", "Beanie"
        if _HEADGEAR_TITLE_RE.search(text):
            return "Tennis clothing", "Accessories", "Caps & Visors"

    if _norm(storefront_sport) == "Running" and l2 in {
        "Pants",
        "Running pants & tights",
    }:
        if re.search(r"\bshorts?\b", text, re.I):
            return "Running", "Shorts", None

    if (
        _norm(storefront_sport) == "Running"
        and l1 == "Running clothes"
        and l2 == "Running clothes"
        and not l3
    ):
        leaf = _pick_padel_clothing_l2_from_title(text)
        if leaf == "Shorts":
            return "Running", "Shorts", None
        if leaf == "Hoodies & Sweaters":
            return "Running clothes", "Hoodies & Sweaters", None
        if leaf == "Pants":
            return "Running clothes", "Pants", None

    if (
        _norm(storefront_sport) == "Tennis"
        and l1 == "Tennis clothing"
        and l2 == "Compression"
        and not l3
    ):
        if re.search(r"\btights?\b", text, re.I):
            return l1, l2, "Tights"
        if re.search(r"\bshorts?\b", text, re.I):
            return l1, l2, "Shorts"
        if re.search(r"\bpants\b", text, re.I):
            return l1, l2, "Pants"

    if l1 == "Accessories" and l2 == "Racket accessories" and not l3:
        if re.search(r"dampener|vibration", text, re.I):
            return l1, l2, "Dampeners"
        if re.search(r"grommet", text, re.I):
            return l1, l2, "Grommets"
        if re.search(r"edge\s*guard|frame\s*protection", text, re.I):
            if re.search(r"pickleball|padel", text, re.I):
                return "Accessories", "Pickleball", None
            return l1, l2, "Frame protection"
        if re.search(r"grip.improver|tac\s*rag|reinigungsblock", text, re.I):
            return "Accessories", "Training accessories", "Useful items & care"
        if re.search(r"string\s*meter|stringmeter", text, re.I):
            return "Accessories", "Coaching equipment", None
        if re.search(r"\bpen\b", text, re.I):
            return "Accessories", "Gifts", "Fun items"

    if l1 == "Accessories" and l2 == "Accessories" and not l3:
        if _WATER_BOTTLE_TITLE_RE.search(text):
            return "Accessories", "Training accessories", None
        if _PRESSURIZER_TITLE_RE.search(text):
            if _norm(storefront_sport) == "Padel":
                return "Padel accessories", "Padel accessories", None
            return "Accessories", "Training accessories", None
        if re.search(r"\barmband\b", text, re.I):
            return "Accessories", "Fitness accessories", None
        if _KEYRING_TITLE_RE.search(text):
            return "Accessories", "Gifts", "Keychains"
        if _BALL_CLIP_TITLE_RE.search(text):
            return "Accessories", "Racket accessories", "Ball clips"
        if _COSMETICS_TITLE_RE.search(text):
            return "Accessories", "Training accessories", "Useful items & care"
        if (
            _MINI_RACKET_TITLE_RE.search(text)
            or re.search(r"\bschul-set\b", text, re.I)
            or re.search(r"^set\s+\d", text, re.I)
        ):
            return "Accessories", "Gifts", "Fun items"
        if re.search(r"\brosin\b", text, re.I):
            return "Accessories", "Training accessories", "Useful items & care"

    if _norm(storefront_sport) == "Padel":
        ml1, ml2, ml3 = refine_padel_makeup_bag_taxonomy(
            category_l1, category_l2, category_l3, storefront_sport, title
        )
        if (ml1, ml2, ml3) != (category_l1, category_l2, category_l3):
            return ml1, ml2, ml3

    refined_l2 = _apply_outerwear_title_refinement(l2, storefront_sport, text)
    if refined_l2 and refined_l2 != l2:
        return l1, refined_l2, None

    return category_l1, category_l2, category_l3


# Косметичка по title → Padel bags / Cosmetic bags.
def refine_padel_makeup_bag_taxonomy(
    category_l1: str | None,
    category_l2: str | None,
    category_l3: str | None,
    storefront_sport: str | None,
    title: str | None,
) -> tuple[str | None, str | None, str | None]:
    if _norm(storefront_sport) != "Padel":
        return category_l1, category_l2, category_l3
    if not _MAKEUP_BAG_TITLE_RE.search(title or ""):
        return category_l1, category_l2, category_l3
    return "Padel", "Bags", "Cosmetic bags"


# Фильтрует collections по витринному спорту для bounded refinement.
def _collections_for_sport(
    collections: list[tuple[str, str]] | None,
    storefront_sport: str | None,
) -> list[tuple[str, str]]:
    if not collections:
        return []
    sport = _norm(storefront_sport)
    markers: tuple[str, ...]
    if sport == "Running":
        markers = ("running-",)
    elif sport == "Padel":
        markers = ("padel-", "tennis-clothing", "tennisbekleidung")
    elif sport == "Tennis":
        markers = ("tennis-clothing", "tennisbekleidung", "tennis-")
    else:
        return list(collections)
    filtered = [
        (handle, title)
        for handle, title in collections
        if any(marker in handle.lower() for marker in markers)
    ]
    return filtered


# Нужно ли пытаться уточнить видимый container L2.
def _needs_visible_container_refinement(
    category_l2: str | None,
    storefront_sport: str | None,
) -> bool:
    return _refinement_allowed_for_l2(category_l2, storefront_sport)


# Leaf L2 из supplier item_category3.
def _pick_l2_from_item_category3(
    supplier_taxonomy: dict[str, Any] | None,
) -> str | None:
    if not isinstance(supplier_taxonomy, dict):
        return None
    item_category3 = _norm(text_or_none(supplier_taxonomy.get("item_category3")))
    if not item_category3:
        return None
    return ITEM_CATEGORY3_TO_L2.get(item_category3)


# Текст title/product_type/collections для compression/sleeve guard.
def _compression_sleeve_signal_text(
    title: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
) -> str:
    parts: list[str] = []
    if title:
        parts.append(title.lower())
    if product_type:
        parts.append(product_type.lower())
    if collections:
        for handle, coll_title in collections:
            if handle:
                parts.append(handle.lower())
            if coll_title:
                parts.append(coll_title.lower())
    return " ".join(parts)


# Compression/sleeve/tube сигнал в title, product_type или collections.
def _has_compression_sleeve_signal(
    title: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
) -> bool:
    text = _compression_sleeve_signal_text(title, product_type, collections)
    if not text:
        return False
    return any(signal in text for signal in COMPRESSION_SLEEVE_SIGNALS)


# Аксессуарный сигнал в product_type или collection handles.
def _has_accessory_collection_signal(
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
) -> bool:
    pt = _norm(product_type)
    if pt and pt in ACCESSORIES_PRODUCT_TYPES:
        return True
    if not collections:
        return False
    for handle, _title in collections:
        low = handle.lower().strip()
        if not low:
            continue
        if low.startswith("accessories-") or any(
            marker in low for marker in ACCESSORY_COLLECTION_MARKERS
        ):
            return True
    return False


# Альтернатива Shirts для compression/sleeve:
# Compression (title/type) → accessories → review.
def _resolve_compression_sleeve_l2(
    storefront_sport: str | None,
    title: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
) -> str | None:
    sport = _norm(storefront_sport)
    if not sport:
        return None
    allowed = NAV_L2_BY_SPORT.get(sport, frozenset())
    primary_parts: list[str] = []
    if title:
        primary_parts.append(title.lower())
    if product_type:
        primary_parts.append(product_type.lower())
    primary_text = " ".join(primary_parts)
    if primary_text and "compression" in primary_text and "Compression" in allowed:
        return "Compression"
    if (
        _has_accessory_collection_signal(product_type, collections)
        and "Running accessories" in allowed
    ):
        return "Running accessories"
    if primary_text and any(
        signal in primary_text for signal in COMPRESSION_SLEEVE_SIGNALS
    ):
        if "Compression" in allowed:
            return "Compression"
    if "Compression" in allowed:
        return "Compression"
    if "Running accessories" in allowed:
        return "Running accessories"
    return None


# Блокирует running-tops → Shirts для compression/sleeve/tube.
def _guard_running_tops_shirts_mapping(
    l2: str | None,
    winning_fragment: str | None,
    title: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
    storefront_sport: str | None,
) -> str | None:
    if l2 != "Shirts" or winning_fragment != RUNNING_TOPS_TO_SHIRTS_FRAGMENT:
        return l2
    if not _has_compression_sleeve_signal(title, product_type, collections):
        return l2
    return _resolve_compression_sleeve_l2(
        storefront_sport,
        title,
        product_type,
        collections,
    )


# Leaf L2 из collection handle fragments (длинные совпадения первыми).
def _pick_l2_from_collection_fragments(
    collections: list[tuple[str, str]],
    title: str | None = None,
    product_type: str | None = None,
    storefront_sport: str | None = None,
    collections_for_signal: list[tuple[str, str]] | None = None,
) -> str | None:
    signal_collections = (
        collections_for_signal if collections_for_signal is not None else collections
    )
    best: tuple[int, str, str] | None = None
    for handle, _title in collections:
        low = handle.lower().strip()
        if not low:
            continue
        for fragment, l2 in COLLECTION_HANDLE_FRAGMENT_TO_L2:
            if fragment not in low:
                continue
            depth = len(fragment)
            if best is None or depth > best[0]:
                best = (depth, l2, fragment)
    if not best:
        return None
    return _guard_running_tops_shirts_mapping(
        best[1],
        best[2],
        title,
        product_type,
        signal_collections,
        storefront_sport,
    )


# Leaf L3 из running accessories handles + product_type (без title-regex).
def pick_l3_from_running_accessories_handles(
    category_l2: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
) -> str | None:
    l2 = ORPHAN_L2_NORMALIZATION.get(_norm(category_l2), _norm(category_l2))
    pt = _norm(product_type)
    if not l2 or l2 not in RUNNING_ACCESSORIES_NAV_L2:
        return None
    best: tuple[int, str] | None = None
    for handle, _title in collections or []:
        low = handle.lower().strip()
        if not low:
            continue
        for fragment, l3, allowed_pts in RUNNING_ACCESSORIES_HANDLE_FRAGMENT_TO_L3:
            if fragment not in low:
                continue
            if allowed_pts and pt not in allowed_pts:
                continue
            depth = len(fragment)
            if best is None or depth > best[0]:
                best = (depth, l3)
    if best:
        return best[1]
    if l2 == "Accessories" and pt == "Accessories":
        return None
    return RUNNING_ACCESSORIES_PRODUCT_TYPE_TO_L3.get(pt)


# Leaf L3 из title для Tennis accessories (bounded, без широких cap/sock правил).
def _pick_tennis_accessories_l3_from_title(
    title: str | None,
    category_l2: str | None,
) -> str | None:
    l2 = ORPHAN_L2_NORMALIZATION.get(_norm(category_l2), _norm(category_l2))
    text = (title or "").strip()
    if not l2 or not text or l2 not in TENNIS_ACCESSORIES_L3_REFINEMENT_L2:
        return None
    for pattern, l3, allowed_l2 in _TENNIS_ACCESSORIES_TITLE_L3_RULES:
        if l2 not in allowed_l2:
            continue
        if pattern.search(text):
            return l3
    return None


# Leaf L3 из Tennis accessories handles + bounded title fallback.
def pick_l3_from_tennis_accessories_handles(
    category_l2: str | None,
    product_type: str | None,
    collections: list[tuple[str, str]] | None,
    title: str | None = None,
    storefront_sport: str | None = None,
) -> str | None:
    if _norm(storefront_sport) != "Tennis":
        return None
    l2 = ORPHAN_L2_NORMALIZATION.get(_norm(category_l2), _norm(category_l2))
    if not l2 or l2 not in TENNIS_ACCESSORIES_NAV_L2:
        return None
    best: tuple[int, str] | None = None
    for handle, _title in collections or []:
        low = handle.lower().strip()
        if not low:
            continue
        for fragment, l3, allowed_l2 in TENNIS_ACCESSORIES_HANDLE_FRAGMENT_TO_L3:
            if l2 not in allowed_l2 or fragment not in low:
                continue
            depth = len(fragment)
            if best is None or depth > best[0]:
                best = (depth, l3)
    if best:
        return best[1]
    return _pick_tennis_accessories_l3_from_title(title, l2)


# Leaf L3 из collection handle fragments (без title-regex).
def pick_l3_from_collection_handles(
    collections: list[tuple[str, str]] | None,
    title: str | None = None,
    product_type: str | None = None,
    collections_for_signal: list[tuple[str, str]] | None = None,
) -> str | None:
    if not collections:
        return None
    signal_collections = (
        collections_for_signal if collections_for_signal is not None else collections
    )
    best: tuple[int, str, str] | None = None
    for handle, _title in collections:
        low = handle.lower().strip()
        if not low:
            continue
        for fragment, l3 in COLLECTION_HANDLE_FRAGMENT_TO_L3:
            if fragment not in low:
                continue
            depth = len(fragment)
            if best is None or depth > best[0]:
                best = (depth, l3, fragment)
    if not best:
        return None
    if best[2] == RUNNING_TOPS_TO_SHIRTS_FRAGMENT and _has_compression_sleeve_signal(
        title,
        product_type,
        signal_collections,
    ):
        return None
    return best[1]


# Leaf L2 из product_type внутри parent apparel bucket.
def _pick_l2_from_product_type_in_parent(
    category_l2: str | None,
    product_type: str | None,
) -> str | None:
    l2 = _norm(category_l2)
    pt = _norm(product_type)
    if not l2 or l2 not in PARENT_APPAREL_BUCKETS or not pt:
        return None
    return PRODUCT_TYPE_IN_PARENT_TO_L2.get(pt)


# Уточняет apparel L2 из collection title path.
def _pick_apparel_l2_from_titles(
    collections: list[tuple[str, str]],
) -> str | None:
    best: tuple[int, str] | None = None
    for _handle, title in collections:
        match = _TITLE_PATH_RE.match(title.strip())
        if not match:
            continue
        label = _norm(match.group(1))
        parts = [_norm(part) for part in match.group(2).split("/") if part.strip()]
        if not label or len(parts) < 2:
            continue
        if label not in APPAREL_CORE_L2:
            continue
        depth = len(parts)
        if best is None or depth > best[0]:
            best = (depth, label)
    return best[1] if best else None


# Уточняет apparel L2 из collection handles.
def _pick_apparel_l2_from_handles(
    collections: list[tuple[str, str]],
    title: str | None = None,
    product_type: str | None = None,
    storefront_sport: str | None = None,
    collections_for_signal: list[tuple[str, str]] | None = None,
) -> str | None:
    from_fragments = _pick_l2_from_collection_fragments(
        collections,
        title=title,
        product_type=product_type,
        storefront_sport=storefront_sport,
        collections_for_signal=collections_for_signal,
    )
    if from_fragments:
        return from_fragments
    for handle, _title in collections:
        low = handle.lower().strip()
        if not any(marker in low for marker in APPAREL_COLLECTION_HANDLE_MARKERS):
            continue
        for suffix, l2 in APPAREL_L2_BY_COLLECTION_HANDLE_SUFFIX:
            if suffix in low:
                return l2
    return None


# Bounded refinement: parent apparel bucket → leaf L2 из collections.
def refine_parent_apparel_l2(
    category_l2: str | None,
    collections: list[tuple[str, str]] | None,
    supplier_taxonomy: dict[str, Any] | None = None,
    product_type: str | None = None,
    storefront_sport: str | None = None,
    title: str | None = None,
) -> str | None:
    if not category_l2 or category_l2 not in PARENT_APPAREL_BUCKETS:
        return category_l2
    if not _refinement_allowed_for_l2(category_l2, storefront_sport):
        return category_l2
    scoped_collections = _collections_for_sport(collections, storefront_sport)
    from_l3 = _pick_l2_from_item_category3(supplier_taxonomy)
    if from_l3:
        return from_l3
    if not scoped_collections:
        from_pt = _pick_l2_from_product_type_in_parent(category_l2, product_type)
        if from_pt:
            return from_pt
        return _apply_padel_clothing_title_refinement(
            category_l2, storefront_sport, title
        )
    from_handles = _pick_apparel_l2_from_handles(
        scoped_collections,
        title=title,
        product_type=product_type,
        storefront_sport=storefront_sport,
        collections_for_signal=collections,
    )
    if from_handles:
        return from_handles
    from_titles = _pick_apparel_l2_from_titles(scoped_collections)
    if from_titles:
        return from_titles
    from_pt = _pick_l2_from_product_type_in_parent(category_l2, product_type)
    if from_pt:
        return from_pt
    return _apply_padel_clothing_title_refinement(category_l2, storefront_sport, title)


# Refinement видимых container L2 (Running clothes, Outerwear, Padel clothing).
def refine_visible_container_l2(
    category_l2: str | None,
    supplier_taxonomy: dict[str, Any] | None,
    collections: list[tuple[str, str]] | None,
    product_type: str | None = None,
    storefront_sport: str | None = None,
    title: str | None = None,
) -> str | None:
    if not _needs_visible_container_refinement(category_l2, storefront_sport):
        return category_l2
    scoped_collections = _collections_for_sport(collections, storefront_sport)
    from_l3 = _pick_l2_from_item_category3(supplier_taxonomy)
    if from_l3:
        return from_l3
    if scoped_collections:
        from_fragments = _pick_l2_from_collection_fragments(
            scoped_collections,
            title=title,
            product_type=product_type,
            storefront_sport=storefront_sport,
            collections_for_signal=collections,
        )
        if from_fragments:
            return from_fragments
        from_handles = _pick_apparel_l2_from_handles(
            scoped_collections,
            title=title,
            product_type=product_type,
            storefront_sport=storefront_sport,
            collections_for_signal=collections,
        )
        if from_handles:
            return from_handles
        from_titles = _pick_apparel_l2_from_titles(scoped_collections)
        if from_titles:
            return from_titles
    from_pt = _pick_l2_from_product_type_in_parent(category_l2, product_type)
    if from_pt:
        return from_pt
    refined = _apply_outerwear_title_refinement(category_l2, storefront_sport, title)
    if refined != category_l2:
        return refined
    return _apply_padel_clothing_title_refinement(category_l2, storefront_sport, title)


# Нормализует orphan L2 в nav-compatible ключ.
def normalize_orphan_l2(category_l2: str | None) -> str | None:
    l2 = _norm(category_l2) or None
    if not l2:
        return None
    return ORPHAN_L2_NORMALIZATION.get(l2, l2)


# Проверяет, входит ли L2 в nav contract для sport_type.
def is_nav_compatible_l2(
    category_l2: str | None,
    sport_type: str | None,
) -> bool:
    l2 = normalize_orphan_l2(category_l2)
    sport = _norm(sport_type)
    if not l2 or not sport:
        return False
    allowed = NAV_L2_BY_SPORT.get(sport)
    if not allowed:
        return False
    return l2 in allowed
