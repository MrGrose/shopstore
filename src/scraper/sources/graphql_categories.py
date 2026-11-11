import re
from typing import Any

from src.services.catalog.categories.l2_sets import PARENT_L2_FOR_RACKET_SUBTYPES
from src.services.catalog.categories.l3_registry import (
    PADEL_RACKET_L3_BY_HANDLE,
    RACKET_L2_BY_HANDLE_SUFFIX,
    TENNIS_SHOE_L3_BY_HANDLE_SUFFIX,
)
from src.services.catalog.categories.sport_policy import resolve_storefront_sport
from src.services.catalog.categories.taxonomy import (
    infer_category_l3,
    resolve_merchandise_l1,
)
from src.services.catalog.categories.taxonomy_policy import (
    normalize_orphan_l2,
    pick_l3_from_collection_handles,
    pick_l3_from_running_accessories_handles,
    pick_l3_from_tennis_accessories_handles,
    project_supplier_merchandise_taxonomy,
    refine_padel_makeup_bag_taxonomy,
    refine_parent_apparel_l2,
    refine_visible_container_l2,
    supplier_l2_allows_collection_override,
)
from src.services.catalog.text import text_or_none
from src.utils.labels import TENNIS_SHOES_BASE_L2, normalize_category_levels

# Регулярное выражение для извлечения label и path из title.
_TITLE_PATH_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")

# Родительские категории для подтипов теннисной обуви.
_PARENT_L2_FOR_SHOE_SUBTYPES = frozenset(TENNIS_SHOES_BASE_L2)

# Noise handles для фильтрации коллекций.
_NOISE_HANDLES = frozenset(
    {
        "supplier-demo",
        "brands",
        "productsup",
        "padel",
        "tennis",
        "running",
        "topseller",
    }
)

# Noise prefixes для фильтрации коллекций.
_NOISE_PREFIXES = (
    "brands-",
    "aktion-",
    "productsup",
    "padel-padel-racket-en",
    "tennis-rackets-en",
)


# Нормализует токен (строка без пробелов).
def _normalize_token(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


# Нормализует handle токен (строка без пробелов и символов подчеркивания).
def _normalize_handle_token(value: str) -> str:
    return value.lower().replace("-", " ").replace("_", " ").strip()


# Проверяет, является ли коллекция noise (noise handle или noise prefix).
def _is_noise_collection(handle: str) -> bool:
    low = handle.lower().strip()
    if not low or low in _NOISE_HANDLES:
        return True
    return any(low.startswith(prefix) for prefix in _NOISE_PREFIXES)


# Извлекает label и path из title коллекции.
def _parse_collection_title(title: str) -> tuple[str | None, list[str]]:
    match = _TITLE_PATH_RE.match(title.strip())
    if not match:
        return None, []
    label = _normalize_token(match.group(1))
    parts = [
        _normalize_token(part) for part in match.group(2).split("/") if part.strip()
    ]
    return label or None, parts


# Итерирует коллекции продукта.
def _iter_product_collections(node: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for edge in (node.get("collections") or {}).get("edges") or []:
        coll = edge.get("node") or {}
        handle = _normalize_token(coll.get("handle"))
        if not handle or _is_noise_collection(handle):
            continue
        title = _normalize_token(coll.get("title")) or handle
        out.append((handle, title))
    return out


# Выбирает L3 теннисной обуви из collection handles.
def _pick_l3_from_tennis_shoe_handles(
    collections: list[tuple[str, str]],
    product_type: str,
) -> str | None:
    if product_type not in _PARENT_L2_FOR_SHOE_SUBTYPES:
        return None
    for handle, _title in collections:
        low = handle.lower().strip()
        if "tennis-shoes" not in low:
            continue
        for suffix, l3 in TENNIS_SHOE_L3_BY_HANDLE_SUFFIX.items():
            if low.endswith(suffix):
                return l3
    return None


# Выбирает L3 падел-ракеток из collection handles.
def _pick_l3_from_padel_racket_handles(
    collections: list[tuple[str, str]],
) -> str | None:
    for handle, _title in collections:
        mapped = PADEL_RACKET_L3_BY_HANDLE.get(handle)
        if mapped:
            return mapped
    return None


# Выбирает подтип теннис-ракеток (supplier-demo collection handles).
def _pick_racket_l2_override(
    collections: list[tuple[str, str]],
    product_type: str,
) -> str | None:
    if product_type not in PARENT_L2_FOR_RACKET_SUBTYPES:
        return None
    for handle, title in collections:
        for suffix, l2 in RACKET_L2_BY_HANDLE_SUFFIX.items():
            if handle.endswith(suffix):
                return l2
        label, parts = _parse_collection_title(title)
        if not label or not parts:
            continue
        last = parts[-1]
        if _normalize_handle_token(last) in {
            "junior rackets",
            "tour rackets",
            "allround rackets",
            "power rackets",
            "control rackets",
        }:
            return label
    return None


# Выбирает подтип теннис-ракеток (supplier-demo collection handles).
def _pick_l3_from_titles(
    collections: list[tuple[str, str]],
    sport_type: str,
    category_l2: str,
) -> str | None:
    sport_norm = _normalize_handle_token(sport_type)
    l2_norm = _normalize_handle_token(category_l2)
    best: tuple[int, str] | None = None

    for _handle, title in collections:
        label, parts = _parse_collection_title(title)
        if not label or len(parts) < 2:
            continue
        if _normalize_handle_token(parts[0]) != sport_norm:
            continue
        parent_norm = _normalize_handle_token(parts[-1])
        if parent_norm != l2_norm and parent_norm not in {
            l2_norm.rstrip("s"),
            f"{l2_norm} racket",
            "padel racket",
            "shoes",
            "tennis shoes",
            "tennis shoe",
        }:
            continue
        depth = len(parts)
        if best is None or depth > best[0]:
            best = (depth, label)

    return best[1] if best else None


# True если supplier_taxonomy уже задал поле.
def _taxonomy_has(
    supplier_taxonomy: dict[str, Any] | None,
    key: str,
) -> bool:
    if not isinstance(supplier_taxonomy, dict):
        return False
    return bool(text_or_none(supplier_taxonomy.get(key)))


# Решает категории GraphQL из node.
def resolve_graphql_categories(
    sport_type: str,
    product_type: str,
    collections: list[tuple[str, str]],
    title: str = "",
    supplier_taxonomy: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    taxonomy = supplier_taxonomy if isinstance(supplier_taxonomy, dict) else {}
    import_sport = _normalize_token(sport_type) or None
    product_type_norm = _normalize_token(product_type) or None

    raw_l1 = _normalize_token(text_or_none(taxonomy.get("item_category"))) or None
    raw_l2 = _normalize_token(text_or_none(taxonomy.get("item_category2"))) or None
    raw_l3 = _normalize_token(text_or_none(taxonomy.get("item_category3"))) or None

    if not raw_l1:
        raw_l1 = resolve_merchandise_l1(
            product_type_norm,
            import_collection_sport=import_sport,
        )
    if not raw_l2:
        raw_l2 = product_type_norm

    # Витринный sport: StorefrontSportPolicy (Phase A).
    storefront_sport = resolve_storefront_sport(
        import_collection_sport=import_sport,
        merchandise_l1=raw_l1,
        merchandise_l2=raw_l2,
        product_type=product_type_norm,
        title=title,
        product_collections=collections,
        supplier_taxonomy_sport=text_or_none(taxonomy.get("sport_type")),
    )

    projected = project_supplier_merchandise_taxonomy(
        taxonomy,
        storefront_sport=storefront_sport,
        product_type=product_type_norm,
    )
    category_l1 = projected.category_l1 or raw_l1
    category_l2 = projected.category_l2 or raw_l2
    category_l3 = projected.category_l3 or raw_l3
    l2_is_parent = projected.l2_is_parent_bucket

    if l2_is_parent:
        category_l2 = (
            refine_parent_apparel_l2(
                category_l2,
                collections,
                supplier_taxonomy=taxonomy,
                product_type=product_type_norm,
                storefront_sport=storefront_sport,
                title=title or None,
            )
            or category_l2
        )

    category_l2 = (
        refine_visible_container_l2(
            category_l2=category_l2,
            supplier_taxonomy=taxonomy,
            collections=collections,
            product_type=product_type_norm,
            storefront_sport=storefront_sport,
            title=title or None,
        )
        or category_l2
    )

    category_l1, category_l2, category_l3 = refine_padel_makeup_bag_taxonomy(
        category_l1,
        category_l2,
        category_l3,
        storefront_sport,
        title or None,
    )

    allow_l2_override = supplier_l2_allows_collection_override(taxonomy, l2_is_parent)

    l2_override = _pick_racket_l2_override(collections, product_type_norm or "")
    if l2_override and allow_l2_override:
        category_l2 = l2_override

    # Generic Shoes в running-коллекции → Running shoes.
    if (
        allow_l2_override
        and category_l1 == "Running shoes"
        and (product_type_norm or "").lower() in {"shoes", "shoe"}
    ):
        category_l2 = "Running shoes"

    if (product_type_norm or "") in {
        "Padel rackets",
        "Padel racket",
    } and not category_l3:
        category_l3 = _pick_l3_from_padel_racket_handles(collections)

    if not category_l3 and storefront_sport == "Tennis":
        category_l3 = _pick_l3_from_tennis_shoe_handles(
            collections, product_type_norm or category_l2 or ""
        )

    if not category_l3 and storefront_sport == "Running":
        category_l3 = pick_l3_from_running_accessories_handles(
            category_l2=category_l2,
            product_type=product_type_norm,
            collections=collections,
        )

    if not category_l3 and storefront_sport == "Tennis":
        category_l3 = pick_l3_from_tennis_accessories_handles(
            category_l2=category_l2,
            product_type=product_type_norm,
            collections=collections,
            title=title or None,
            storefront_sport=storefront_sport,
        )

    if not category_l3:
        category_l3 = pick_l3_from_collection_handles(
            collections,
            title=title or None,
            product_type=product_type_norm,
            collections_for_signal=collections,
        )

    if not category_l3 and category_l2 == "Running shoes" and title:
        category_l3 = infer_category_l3(category_l2=category_l2, title=title)

    if not category_l3 and category_l2 and storefront_sport:
        category_l3 = _pick_l3_from_titles(
            collections,
            sport_type=storefront_sport,
            category_l2=category_l2,
        )

    category_l2, category_l3 = normalize_category_levels(
        category_l2, category_l3, sport_type=storefront_sport
    )
    category_l2 = normalize_orphan_l2(category_l2)
    trade_group = product_type_norm or category_l2

    return {
        "category_l1": category_l1,
        "category_l2": category_l2,
        "category_l3": category_l3,
        "sport_type": storefront_sport,
        "trade_group": trade_group,
        "item_category": category_l1,
        "item_category2": category_l2,
        "item_category3": category_l3,
    }


# Решает категории GraphQL из node.
def resolve_graphql_categories_from_node(
    node: dict[str, Any],
    sport_type: str,
) -> dict[str, str | None]:
    product_type = _normalize_token(node.get("productType"))
    collections = _iter_product_collections(node)
    title = _normalize_token(node.get("title"))
    return resolve_graphql_categories(
        sport_type=sport_type,
        product_type=product_type or "",
        collections=collections,
        title=title,
    )


# Коллекции Shopify node для supplier_snapshot_json (без noise handles).
def supplier_collections_from_node(node: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"handle": handle, "title": title}
        for handle, title in _iter_product_collections(node)
    ]
