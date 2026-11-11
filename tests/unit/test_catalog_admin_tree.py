from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.core.order_limits import is_supplier_unit_storefront_allowed
from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.services.catalog.display.admin_status import admin_product_tree_status
from src.services.catalog.display.constants import (
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_UNMAPPED,
)
from src.services.catalog.read.scope import normalize_admin_catalog_tree


def test_normalize_default_is_on_site() -> None:
    tree = normalize_admin_catalog_tree("included", "visible", "all")
    assert tree.inclusion == "included"
    assert tree.site == "visible"
    assert tree.reason == "all"


def test_normalize_excluded_clears_site_and_reason() -> None:
    tree = normalize_admin_catalog_tree("excluded", "visible", "supplier_limit")
    assert tree.inclusion == "excluded"
    assert tree.site == "all"
    assert tree.reason == "all"


def test_normalize_reason_implies_not_visible() -> None:
    tree = normalize_admin_catalog_tree("all", "all", "supplier_limit")
    assert tree.inclusion == "included"
    assert tree.site == "not_visible"
    assert tree.reason == "supplier_limit"


def test_normalize_total_keeps_all() -> None:
    tree = normalize_admin_catalog_tree("all", "all", "all")
    assert tree.inclusion == "all"
    assert tree.site == "all"
    assert tree.reason == "all"


def test_included_mapped_under_cap_with_placement_is_visible() -> None:
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Babolat",
        supplier_price_eur=Decimal("250"),
        hidden_brands=frozenset(),
        has_placement=True,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "included"
    assert status.site == "visible"
    assert status.reasons == ()


def test_over_cap_mapped_in_stock_is_not_visible_supplier_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    assert is_supplier_unit_storefront_allowed(Decimal("270.02")) is False
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Babolat",
        supplier_price_eur=Decimal("270.02"),
        hidden_brands=frozenset(),
        has_placement=True,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "included"
    assert status.site == "not_visible"
    assert status.reasons == ("supplier_limit",)


def test_hidden_brand_is_excluded_not_not_visible() -> None:
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Supplier-Demo",
        supplier_price_eur=Decimal("40"),
        hidden_brands=frozenset({"Supplier-Demo"}),
        has_placement=True,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "excluded"
    assert status.site == "none"
    assert status.reasons == ("hidden_brand",)
    assert "supplier_limit" not in status.reasons


def test_inactive_is_excluded() -> None:
    status = admin_product_tree_status(
        is_active=False,
        catalog_in_stock=True,
        brand="Head",
        supplier_price_eur=Decimal("100"),
        hidden_brands=frozenset(),
        has_placement=True,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "excluded"
    assert status.site == "none"
    assert status.reasons == ("inactive",)
    assert "supplier_limit" not in status.reasons


def test_zero_stock_and_over_cap_reasons_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=False,
        brand="Head",
        supplier_price_eur=Decimal("315"),
        hidden_brands=frozenset(),
        has_placement=True,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "included"
    assert status.site == "not_visible"
    assert status.reasons == ("supplier_limit", "zero_stock")


def test_mapping_excluded_is_not_catalog_excluded() -> None:
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Asics",
        supplier_price_eur=Decimal("80"),
        hidden_brands=frozenset(),
        has_placement=False,
        resolution=SimpleNamespace(status=RESOLUTION_EXCLUDED),
    )
    assert status.inclusion == "included"
    assert status.site == "not_visible"
    assert status.reasons == ("mapping_excluded",)
    assert "supplier_limit" not in status.reasons
    assert "orphan" not in status.reasons


def test_unmapped_without_placement_is_orphan() -> None:
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Asics",
        supplier_price_eur=Decimal("80"),
        hidden_brands=frozenset(),
        has_placement=False,
        resolution=SimpleNamespace(status=RESOLUTION_UNMAPPED),
    )
    assert status.inclusion == "included"
    assert status.site == "not_visible"
    assert status.reasons == ("orphan",)


def test_mapped_in_stock_under_cap_without_placement_is_orphan() -> None:
    status = admin_product_tree_status(
        is_active=True,
        catalog_in_stock=True,
        brand="Asics",
        supplier_price_eur=Decimal("80"),
        hidden_brands=frozenset(),
        has_placement=False,
        resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
    )
    assert status.inclusion == "included"
    assert status.site == "not_visible"
    assert status.reasons == ("orphan",)


def test_orphan_sql_includes_missing_chip_and_skips_mapping_excluded() -> None:
    repo = CrudProduct(session=None, model=Product)
    compiled = str(
        repo._admin_orphan_clause(7).compile(compile_kwargs={"literal_binds": True})
    )
    assert "product_storefront_placements" in compiled
    assert "chip" in compiled
    assert "'excluded'" in compiled
    assert "'unmapped'" in compiled
    assert "NOT (EXISTS" in compiled


def test_admin_js_cache_token_is_bumped() -> None:
    html = Path("src/templates/site/admin/base.html").read_text(encoding="utf-8")
    assert "admin.js?v=admin-design-40" in html
    assert "admin.js?v=admin-design-39" not in html


def test_products_page_detail_hx_preserves_tree_query() -> None:
    html = Path("src/templates/site/admin/products.html").read_text(encoding="utf-8")
    detail = html.split('id="admin-product-detail"', 1)[1]
    hx_get = detail.split("hx-get=", 1)[1].split("\n", 1)[0]
    assert "inclusion={{ inclusion | default('included') }}" in hx_get
    assert "site={{ site | default('visible') }}" in hx_get
    assert "reason={{ reason | default('all') }}" in hx_get
