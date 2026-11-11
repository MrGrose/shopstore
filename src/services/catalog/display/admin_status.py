from dataclasses import dataclass
from decimal import Decimal

from src.core.order_limits import is_supplier_unit_storefront_allowed
from src.models.product import Product
from src.models.storefront_mapping import ProductStorefrontResolution
from src.services.catalog.display.admin_mapping_status import (
    STOREFRONT_NAV_STATUS_EXCLUDED,
    STOREFRONT_NAV_STATUS_NOT_SELLABLE,
    STOREFRONT_NAV_STATUS_ORPHAN,
    STOREFRONT_NAV_STATUS_VISIBLE,
)
from src.services.catalog.display.constants import (
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_MAPPING_ERROR,
    RESOLUTION_UNMAPPED,
)


# Admin nav pill из product + resolution active release.
def admin_nav_status_from_resolution(
    product: Product,
    resolution: ProductStorefrontResolution | None,
) -> str:
    if not product.is_active or not product.catalog_in_stock:
        return STOREFRONT_NAV_STATUS_NOT_SELLABLE
    if resolution is None:
        return STOREFRONT_NAV_STATUS_ORPHAN
    if resolution.status == RESOLUTION_MAPPED:
        return STOREFRONT_NAV_STATUS_VISIBLE
    if resolution.status == RESOLUTION_EXCLUDED:
        return STOREFRONT_NAV_STATUS_EXCLUDED
    if resolution.status in (RESOLUTION_UNMAPPED, RESOLUTION_MAPPING_ERROR):
        return STOREFRONT_NAV_STATUS_ORPHAN
    return STOREFRONT_NAV_STATUS_ORPHAN


# Текст причины orphan/mapping_error для карточки товара.
def admin_mapping_orphan_reason(
    resolution: ProductStorefrontResolution | None,
) -> str | None:
    if resolution is None:
        return "Нет resolution в active release"
    if resolution.status not in (RESOLUTION_UNMAPPED, RESOLUTION_MAPPING_ERROR):
        return None
    if resolution.reason:
        return resolution.reason
    return f"resolution={resolution.status}"


@dataclass(frozen=True)
class AdminProductTreeStatus:
    inclusion: str
    site: str
    reasons: tuple[str, ...]


# Бренд не скрыт catalog_hidden_brands (пустой бренд считается видимым).
def brand_is_storefront_hidden(
    brand: str | None, hidden_brands: frozenset[str]
) -> bool:
    name = (brand or "").strip()
    if not name:
        return False
    return name in hidden_brands


# Catalog inclusion / storefront site / diagnostic reasons для админ-строки.
def admin_product_tree_status(
    *,
    is_active: bool,
    catalog_in_stock: bool,
    brand: str | None,
    supplier_price_eur: Decimal | float | int | None,
    hidden_brands: frozenset[str],
    has_placement: bool,
    resolution: ProductStorefrontResolution | None,
) -> AdminProductTreeStatus:
    hidden_brand = brand_is_storefront_hidden(brand, hidden_brands)
    included = bool(is_active) and not hidden_brand
    over_cap = not is_supplier_unit_storefront_allowed(supplier_price_eur)
    if not included:
        reasons: list[str] = []
        if not is_active:
            reasons.append("inactive")
        if hidden_brand:
            reasons.append("hidden_brand")
        return AdminProductTreeStatus(
            inclusion="excluded",
            site="none",
            reasons=tuple(reasons),
        )
    visible = bool(catalog_in_stock) and not over_cap and has_placement
    if visible:
        return AdminProductTreeStatus(
            inclusion="included",
            site="visible",
            reasons=(),
        )
    reasons = []
    if over_cap:
        reasons.append("supplier_limit")
    if not catalog_in_stock:
        reasons.append("zero_stock")
    if resolution is not None and resolution.status == RESOLUTION_EXCLUDED:
        reasons.append("mapping_excluded")
    orphan = resolution is None or (
        resolution.status in (RESOLUTION_UNMAPPED, RESOLUTION_MAPPING_ERROR)
    )
    if orphan or not has_placement:
        if "mapping_excluded" not in reasons:
            reasons.append("orphan")
    return AdminProductTreeStatus(
        inclusion="included",
        site="not_visible",
        reasons=tuple(reasons),
    )
