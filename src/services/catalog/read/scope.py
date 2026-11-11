import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict
from urllib.parse import urlencode

from starlette.requests import Request

CATALOG_ADMIN_VIEW_COOKIE = "catalog_admin_view"
CATALOG_TOP_ORDER: tuple[str, ...] = ("Tennis", "Running", "Padel")
CATALOG_ALL_TOP_CATEGORY = "All"
_PLACEMENT_SCOPE_GLOBAL_CACHE = "__global__"
_PLACEMENT_SCOPE_EMPTY_CACHE = "__empty__"


class UnknownCatalogTopCategoryError(ValueError):
    pass


CATALOG_ADMIN_VIEW_MODES: tuple[str, ...] = (
    "in_catalog",
    "in_stock",
    "zero_stock",
    "removed",
)
FacetExcludeKey = Literal["brand", "gender", "color", "size"]

_FACET_DECIMAL_SIZE = re.compile(r"^\d+,\d+$")


ADMIN_TREE_INCLUSION_MODES: tuple[str, ...] = ("all", "included", "excluded")
ADMIN_TREE_SITE_MODES: tuple[str, ...] = ("all", "visible", "not_visible")
ADMIN_TREE_REASON_MODES: tuple[str, ...] = (
    "all",
    "supplier_limit",
    "zero_stock",
    "orphan",
    "mapping_excluded",
)
ADMIN_TREE_INCLUSION_LABELS_RU: dict[str, str] = {
    "all": "Всего",
    "included": "В каталоге",
    "excluded": "Исключены",
}
ADMIN_TREE_SITE_LABELS_RU: dict[str, str] = {
    "visible": "На сайте",
    "not_visible": "Не на сайте",
}
ADMIN_TREE_REASON_LABELS_RU: dict[str, str] = {
    "supplier_limit": "Лимит TP",
    "zero_stock": "Нет остатка",
    "orphan": "Не в навигации",
    "mapping_excluded": "Правило навигации",
    "hidden_brand": "Скрытый бренд",
    "inactive": "Снят",
}


class CatalogStockFilters(TypedDict):
    include_out_of_stock: bool
    zero_stock_only: bool
    inactive_only: bool
    exclude_over_supplier_unit_cap: bool
    # Storefront publication gate: exclude enrichment HOLD, not COMPLETE.
    require_complete: bool


class CatalogReadFilters(CatalogStockFilters):
    exclude_hidden_brands: bool


# Нормализует top-категорию для storefront.
def normalize_storefront_top_category(top: str | None) -> str | None:
    if top is None:
        return None
    cleaned = top.strip()
    if not cleaned:
        return None
    if cleaned.lower() == "all":
        return CATALOG_ALL_TOP_CATEGORY
    return cleaned


# Резолвит top_category для public catalog: All/global, sport или ошибка.
def resolve_public_catalog_top_category(top: str | None) -> str:
    normalized = normalize_storefront_top_category(top)
    if normalized is None:
        return CATALOG_ALL_TOP_CATEGORY
    if normalized == CATALOG_ALL_TOP_CATEGORY:
        return CATALOG_ALL_TOP_CATEGORY
    if normalized in CATALOG_TOP_ORDER:
        return normalized
    raise UnknownCatalogTopCategoryError(f"Неизвестная top_category: {top!r}")


# Кодирует chip_node_ids для Redis-ключа: None=global, ()=empty scope.
def encode_placement_chip_ids_for_cache(
    chip_node_ids: tuple[int, ...] | None,
) -> str | list[int]:
    if chip_node_ids is None:
        return _PLACEMENT_SCOPE_GLOBAL_CACHE
    if not chip_node_ids:
        return _PLACEMENT_SCOPE_EMPTY_CACHE
    return list(chip_node_ids)


_CATALOG_ADMIN_VIEWS = frozenset(CATALOG_ADMIN_VIEW_MODES)


@dataclass(frozen=True)
class CatalogScope:
    include_out_of_stock: bool = False
    zero_stock_only: bool = False
    inactive_only: bool = False
    exclude_hidden_brands: bool = False
    exclude_over_supplier_unit_cap: bool = False
    require_complete: bool = False

    @classmethod
    def storefront_public(cls) -> "CatalogScope":
        return cls(
            exclude_hidden_brands=True,
            exclude_over_supplier_unit_cap=True,
            require_complete=True,
        )

    @classmethod
    def from_admin_mode(cls, mode: str) -> "CatalogScope":
        show_in_catalog, _, show_zero_stock, show_removed = admin_catalog_view_flags(
            mode
        )
        return cls(
            include_out_of_stock=show_in_catalog,
            zero_stock_only=show_zero_stock,
            inactive_only=show_removed,
        )

    def list_filter_kwargs(self) -> CatalogStockFilters:
        return {
            "include_out_of_stock": self.include_out_of_stock,
            "zero_stock_only": self.zero_stock_only,
            "inactive_only": self.inactive_only,
            "exclude_over_supplier_unit_cap": self.exclude_over_supplier_unit_cap,
            "require_complete": self.require_complete,
        }

    # Kwargs для read repo: stock-фильтры + флаг скрытых брендов на витрине.
    def catalog_read_kwargs(self) -> CatalogReadFilters:
        stock = self.list_filter_kwargs()
        return {
            "include_out_of_stock": stock["include_out_of_stock"],
            "zero_stock_only": stock["zero_stock_only"],
            "inactive_only": stock["inactive_only"],
            "exclude_over_supplier_unit_cap": stock["exclude_over_supplier_unit_cap"],
            "require_complete": stock["require_complete"],
            "exclude_hidden_brands": self.exclude_hidden_brands,
        }


# Явный require_complete: ключ из filters, иначе значение scope (не скрытый False).
def require_complete_from_stock_filters(
    stock_filters: Mapping[str, object],
    scope: CatalogScope,
) -> bool:
    if "require_complete" in stock_filters:
        return bool(stock_filters["require_complete"])
    return bool(scope.require_complete)


@dataclass(frozen=True)
class AdminCatalogTree:
    inclusion: str = "included"
    site: str = "visible"
    reason: str = "all"


# Нормализует query-фильтр inclusion админ-дерева.
def normalize_admin_tree_inclusion(raw: str | None) -> str:
    value = (raw or "included").strip().lower()
    if value in ADMIN_TREE_INCLUSION_MODES:
        return value
    return "included"


# Нормализует query-фильтр site админ-дерева.
def normalize_admin_tree_site(raw: str | None) -> str:
    value = (raw or "visible").strip().lower()
    if value in ADMIN_TREE_SITE_MODES:
        return value
    return "visible"


# Нормализует diagnostic reason админ-дерева.
def normalize_admin_tree_reason(raw: str | None) -> str:
    value = (raw or "all").strip().lower()
    if value in ADMIN_TREE_REASON_MODES:
        return value
    return "all"


# Сводит inclusion/site/reason к взаимоисключающим родителям + diagnostic.
def normalize_admin_catalog_tree(
    inclusion: str | None = None,
    site: str | None = None,
    reason: str | None = None,
) -> AdminCatalogTree:
    inclusion_key = normalize_admin_tree_inclusion(inclusion)
    site_key = normalize_admin_tree_site(site)
    reason_key = normalize_admin_tree_reason(reason)
    if inclusion_key == "excluded":
        return AdminCatalogTree(inclusion="excluded", site="all", reason="all")
    if reason_key != "all":
        return AdminCatalogTree(
            inclusion="included",
            site="not_visible",
            reason=reason_key,
        )
    if site_key == "visible":
        return AdminCatalogTree(inclusion="included", site="visible", reason="all")
    if site_key == "not_visible":
        return AdminCatalogTree(inclusion="included", site="not_visible", reason="all")
    if inclusion_key == "all":
        return AdminCatalogTree(inclusion="all", site="all", reason="all")
    return AdminCatalogTree(inclusion="included", site="all", reason="all")


# Проверяет, есть ли фильтры в запросе.
def admin_catalog_view_in_query(request: Request) -> bool:
    q = request.query_params
    return any(
        key in q for key in ("show_removed", "show_zero_stock", "show_out_of_stock")
    )


# Решает режим администратора по параметрам запроса.
def resolve_admin_catalog_view_from_params(
    show_out_of_stock: bool | None,
    show_zero_stock: bool | None,
    show_removed: bool | None,
    cookie_mode: str | None = None,
    fallback: str = "in_catalog",
) -> str:
    if show_removed is True:
        return "removed"
    if show_zero_stock is True:
        return "zero_stock"
    if show_out_of_stock is not None:
        return "in_catalog" if show_out_of_stock else "in_stock"
    if cookie_mode and cookie_mode in _CATALOG_ADMIN_VIEWS:
        return cookie_mode
    if fallback in _CATALOG_ADMIN_VIEWS:
        return fallback
    return "in_catalog"


# Решает режим администратора по запросу.
def resolve_admin_catalog_view(
    request: Request,
    show_out_of_stock: bool | None,
    show_zero_stock: bool | None,
    show_removed: bool | None,
) -> str:
    return resolve_admin_catalog_view_from_params(
        show_out_of_stock=show_out_of_stock,
        show_zero_stock=show_zero_stock,
        show_removed=show_removed,
        cookie_mode=request.cookies.get(CATALOG_ADMIN_VIEW_COOKIE, ""),
    )


# Решает параметры запроса по режиму администратора.
def admin_catalog_view_query(mode: str) -> dict[str, str]:
    if mode == "removed":
        return {"show_removed": "1"}
    if mode == "zero_stock":
        return {"show_zero_stock": "1"}
    if mode == "in_stock":
        return {"show_out_of_stock": "0"}
    return {"show_out_of_stock": "1"}


# Формирует строку запроса для администратора.
def catalog_admin_qs(mode: str) -> str:
    return "&" + urlencode(admin_catalog_view_query(mode))


# Формирует URL с режимом администратора.
def catalog_url_with_admin_view(
    request: Request,
    mode: str,
    page: str | None = None,
) -> str:
    q = request.query_params
    params: list[tuple[str, str]] = [
        ("page", page or q.get("page") or "1"),
        ("page_size", q.get("page_size") or "20"),
        ("top", q.get("top") or "Padel"),
    ]
    category = q.get("category")
    if category:
        params.append(("category", category))
    brand = q.get("brand")
    if brand:
        params.append(("brand", brand))
    params.extend(admin_catalog_view_query(mode).items())
    return f"/catalog?{urlencode(params)}"


# Проверяет, есть ли параметр в запросе.
def optional_query_bool(request: Request, key: str) -> bool | None:
    if key not in request.query_params:
        return None
    return request.query_params.get(key) in ("1", "true", "True")


# Определяет флаги режима администратора.
def admin_catalog_view_flags(mode: str) -> tuple[bool, bool, bool, bool]:
    return (
        mode == "in_catalog",
        mode == "in_stock",
        mode == "zero_stock",
        mode == "removed",
    )


# Решает scope для каталога.
def resolve_catalog_scope(
    is_admin: bool,
    admin_mode: str,
) -> CatalogScope:
    if not is_admin:
        return CatalogScope.storefront_public()
    return CatalogScope.from_admin_mode(admin_mode)


# Разбирает одну query-строку фасета: | — multi;
# comma — legacy brand only; size keeps decimal comma; color/gender opaque.
def _split_facet_token_list(
    text: str,
    facet_key: FacetExcludeKey | None = None,
) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    if "|" in raw:
        return [part.strip() for part in raw.split("|") if part.strip()]
    if facet_key in (None, "size") and _FACET_DECIMAL_SIZE.match(raw):
        return [raw]
    if facet_key in (None, "brand") and "," in raw:
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) > 1:
            return parts
        if len(parts) == 1:
            return parts
        return []
    return [raw]


# Добавляет raw-значения фасета в merged без дублей.
def _append_facet_tokens(
    merged: list[str],
    seen: set[str],
    raw: str | None,
    facet_key: FacetExcludeKey | None = None,
) -> None:
    if raw is None:
        return
    for token in _split_facet_token_list(str(raw), facet_key):
        if not token or token in seen:
            continue
        seen.add(token)
        merged.append(token)


# Разбирает repeated query values фасета каталога.
def parse_facet_query_param(
    values: list[str] | None,
    facet_key: FacetExcludeKey | None = None,
) -> list[str] | None:
    if not values:
        return None
    return merge_facet_list_param(None, values, facet_key=facet_key)


# Разбирает одно query value фасета каталога.
def parse_facet_list_param(
    value: str | None,
    facet_key: FacetExcludeKey | None = None,
) -> list[str] | None:
    if value is None:
        return None
    merged: list[str] = []
    seen: set[str] = set()
    _append_facet_tokens(merged, seen, value, facet_key)
    return merged or None


# Сливает repeated query params и serialized facet values.
def merge_facet_list_param(
    primary: str | None,
    extra: Iterable[str] | None = None,
    facet_key: FacetExcludeKey | None = None,
) -> list[str] | None:
    merged: list[str] = []
    seen: set[str] = set()
    _append_facet_tokens(merged, seen, primary, facet_key)
    if extra:
        for item in extra:
            _append_facet_tokens(merged, seen, item, facet_key)
    return merged or None


# Нормализует список значений фасета для ключа Redis-кэша.
def normalize_facet_list_for_cache(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        trimmed = str(value).strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        normalized.append(trimmed)
    return sorted(normalized)


# Сериализует значения фасета в query string (| между значениями).
def join_facet_list_param(values: Iterable[str] | None) -> str:
    if not values:
        return ""
    seen: set[str] = set()
    parts: list[str] = []
    for value in values:
        trimmed = str(value).strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        parts.append(trimmed)
    return "|".join(parts)


# Для facet options: все фильтры кроме self-filter (counts внутри активного среза).
def build_facet_filters_excluding(
    brands: list[str] | None,
    genders: list[str] | None,
    colors: list[str] | None,
    sizes: list[str] | None,
    exclude: FacetExcludeKey,
) -> tuple[list[str] | None, list[str] | None, list[str] | None, list[str] | None]:
    return (
        None if exclude == "brand" else brands,
        None if exclude == "gender" else genders,
        None if exclude == "color" else colors,
        None if exclude == "size" else sizes,
    )
