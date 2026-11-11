from dataclasses import dataclass

from src.services.catalog.display.pricing_nav_registry import CATALOG_SUBCATEGORIES
from src.services.catalog.display.search_display_groups import (
    RUNNING_APPAREL_DISPLAY_GROUPS,
    TENNIS_APPAREL_DISPLAY_GROUPS,
    CatalogRawSlice,
)
from src.utils.labels import (
    CATEGORY_L2_LABELS_RU,
    CATEGORY_L3_LABELS_RU,
    catalog_labels_client_dict,
)


@dataclass(frozen=True)
class CatalogSearchHit:
    raw_slices: tuple[CatalogRawSlice, ...] = ()
    category_l3_keys: tuple[str, ...] = ()
    sport_types: tuple[str, ...] = ()


# Нормализует текст поискового запроса (trim, без ведущего #).
def _normalize_search_query(q: str | None) -> str | None:
    if not q:
        return None
    text = q.strip().lstrip("#")
    return text or None


# Приводит подпись/запрос к сравнению без регистра и ё/е.
def _normalize_catalog_search_text(value: str) -> str:
    return value.strip().casefold().replace("ё", "е")


# Схлопывает повторяющиеся буквы (слиппоны → слипоны).
def _compact_repeated_letters(value: str) -> str:
    out: list[str] = []
    prev = ""
    for ch in value:
        if ch != prev:
            out.append(ch)
        prev = ch
    return "".join(out)


# Проверяет, что запрос относится к русской подписи категории.
def _label_matches_query(label_ru: str, query: str) -> bool:
    label = _normalize_catalog_search_text(label_ru)
    queries = {
        _normalize_catalog_search_text(query),
        _compact_repeated_letters(_normalize_catalog_search_text(query)),
    }
    for q in queries:
        if len(q) < 3:
            continue
        if q in label or label in q:
            return True
        prefix = min(5, len(q), len(label))
        if prefix >= 4 and q[:prefix] in label:
            return True
    return False


# Убирает дубли (l2, l3) из списка raw_slices.
def _dedupe_slices(slices: tuple[CatalogRawSlice, ...]) -> tuple[CatalogRawSlice, ...]:
    seen: set[tuple[str, str | None]] = set()
    out: list[CatalogRawSlice] = []
    for slice_ in slices:
        key = (slice_.category_l2, slice_.category_l3)
        if key in seen:
            continue
        seen.add(key)
        out.append(slice_)
    return tuple(out)


# Собирает индекс русских подписей витрины → raw_slices / sport / L3.
def _build_catalog_search_entries() -> tuple[tuple[str, CatalogSearchHit], ...]:
    entries: list[tuple[str, CatalogSearchHit]] = []

    for group in (*TENNIS_APPAREL_DISPLAY_GROUPS, *RUNNING_APPAREL_DISPLAY_GROUPS):
        entries.append(
            (group.label_ru, CatalogSearchHit(raw_slices=group.sources)),
        )

    for subs in CATALOG_SUBCATEGORIES.values():
        for sub in subs:
            slices = tuple(CatalogRawSlice(l2) for l2 in sub.category_l2)
            entries.append((sub.label, CatalogSearchHit(raw_slices=slices)))

    for key, label in CATEGORY_L2_LABELS_RU.items():
        entries.append((label, CatalogSearchHit(raw_slices=(CatalogRawSlice(key),))))

    l3_slices: dict[str, list[CatalogRawSlice]] = {}
    for group in (*TENNIS_APPAREL_DISPLAY_GROUPS, *RUNNING_APPAREL_DISPLAY_GROUPS):
        for slice_ in group.sources:
            if slice_.category_l3:
                l3_slices.setdefault(slice_.category_l3, []).append(slice_)

    for key, label in CATEGORY_L3_LABELS_RU.items():
        if key in l3_slices:
            entries.append(
                (
                    label,
                    CatalogSearchHit(raw_slices=_dedupe_slices(tuple(l3_slices[key]))),
                ),
            )
        else:
            entries.append((label, CatalogSearchHit(category_l3_keys=(key,))))

    sport_types = catalog_labels_client_dict().get("sport_types", {})
    if not isinstance(sport_types, dict):
        sport_types = {}
    for sport, label in sport_types.items():
        if isinstance(sport, str) and isinstance(label, str):
            entries.append((label, CatalogSearchHit(sport_types=(sport,))))

    return tuple(entries)


_CATALOG_SEARCH_ENTRIES = _build_catalog_search_entries()


# Резолвит q в срезы каталога по русским подписям навигации.
def resolve_catalog_search_hit(q: str | None) -> CatalogSearchHit | None:
    text = _normalize_search_query(q)
    if not text:
        return None

    slices: list[CatalogRawSlice] = []
    l3_keys: list[str] = []
    sports: list[str] = []
    matched = False

    for label, hit in _CATALOG_SEARCH_ENTRIES:
        if not _label_matches_query(label, text):
            continue
        matched = True
        slices.extend(hit.raw_slices)
        l3_keys.extend(hit.category_l3_keys)
        sports.extend(hit.sport_types)

    if not matched:
        return None

    return CatalogSearchHit(
        raw_slices=_dedupe_slices(tuple(slices)),
        category_l3_keys=tuple(dict.fromkeys(l3_keys)),
        sport_types=tuple(dict.fromkeys(sports)),
    )
