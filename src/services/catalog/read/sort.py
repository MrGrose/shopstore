from typing import Literal

CatalogSortPrice = Literal["asc", "desc"]

CATALOG_SORT_PRICE_OPTIONS: tuple[tuple[CatalogSortPrice, str], ...] = (
    ("asc", "Недорогие"),
    ("desc", "Дорогие"),
)

# Тип сортировки в админ-панели.
CatalogAdminSort = Literal[
    "price_asc",
    "price_desc",
    "stock_asc",
    "stock_desc",
    "synced_asc",
    "synced_desc",
    "id_asc",
    "id_desc",
]


# Опции сортировки в админ-панели.
CATALOG_ADMIN_SORT_OPTIONS: tuple[tuple[CatalogAdminSort, str], ...] = (
    ("price_asc", "Цена ↑"),
    ("price_desc", "Цена ↓"),
    ("stock_asc", "Остаток ↑"),
    ("stock_desc", "Остаток ↓"),
    ("synced_asc", "Дата ↑"),
    ("synced_desc", "Дата ↓"),
    ("id_asc", "ID ↑"),
    ("id_desc", "ID ↓"),
)


# Нормализует sort_price (legacy sort_price=asc|desc → price_*).
def normalize_sort_price(value: str | None) -> CatalogSortPrice | None:
    if value in {"asc", "desc"}:
        return value  # type: ignore[return-value]
    return None


# Нормализует admin sort (legacy sort_price=asc|desc → price_*).
def normalize_admin_sort(
    sort: str | None,
    legacy_sort_price: str | None = None,
) -> CatalogAdminSort | None:
    raw = (sort or "").strip()
    if raw in {
        "price_asc",
        "price_desc",
        "stock_asc",
        "stock_desc",
        "synced_asc",
        "synced_desc",
        "id_asc",
        "id_desc",
    }:
        return raw  # type: ignore[return-value]
    legacy = normalize_sort_price(legacy_sort_price)
    if legacy == "asc":
        return "price_asc"
    if legacy == "desc":
        return "price_desc"
    return None
