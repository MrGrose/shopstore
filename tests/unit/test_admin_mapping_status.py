from types import SimpleNamespace

from src.constants.storefront_mapping import (
    STOREFRONT_NAV_STATUS_EXCLUDED,
    STOREFRONT_NAV_STATUS_NOT_SELLABLE,
    STOREFRONT_NAV_STATUS_ORPHAN,
    STOREFRONT_NAV_STATUS_VISIBLE,
)
from src.services.catalog.display.admin_status import (
    admin_mapping_orphan_reason,
    admin_nav_status_from_resolution,
)
from src.services.catalog.display.constants import (
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_UNMAPPED,
)


def _product(*, active: bool = True, in_stock: bool = True) -> SimpleNamespace:
    return SimpleNamespace(is_active=active, catalog_in_stock=in_stock)


def _resolution(status: str, reason: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, reason=reason)


def test_mapped_active_in_stock_is_visible() -> None:
    status = admin_nav_status_from_resolution(
        _product(),
        _resolution(RESOLUTION_MAPPED),
    )
    assert status == STOREFRONT_NAV_STATUS_VISIBLE


def test_excluded_maps_to_excluded_pill() -> None:
    status = admin_nav_status_from_resolution(
        _product(),
        _resolution(RESOLUTION_EXCLUDED),
    )
    assert status == STOREFRONT_NAV_STATUS_EXCLUDED


def test_unmapped_is_orphan_with_reason() -> None:
    resolution = _resolution(RESOLUTION_UNMAPPED, reason="no matching rule")
    status = admin_nav_status_from_resolution(_product(), resolution)
    assert status == STOREFRONT_NAV_STATUS_ORPHAN
    assert admin_mapping_orphan_reason(resolution) == "no matching rule"


def test_inactive_product_is_not_sellable() -> None:
    status = admin_nav_status_from_resolution(
        _product(active=False),
        _resolution(RESOLUTION_MAPPED),
    )
    assert status == STOREFRONT_NAV_STATUS_NOT_SELLABLE
