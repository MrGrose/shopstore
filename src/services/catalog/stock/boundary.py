from dataclasses import dataclass, field


@dataclass
class RefreshStockResult:
    refreshed: int = 0
    boundary_flipped_ids: list[int] = field(default_factory=list)


# Витрина: is_active и catalog_in_stock (denorm).
def storefront_visible(is_active: bool, catalog_in_stock: bool) -> bool:
    return bool(is_active) and bool(catalog_in_stock)
