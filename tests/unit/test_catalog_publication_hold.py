import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.product import Product, ProductFeature, ProductImage
from src.repositories.product_repo import CrudProduct
from src.services.catalog.importing.product_complete import (
    HOLD_DOM_LAST_ERRORS,
    enrichment_hold_sql_criterion,
    is_enrichment_hold,
    is_product_complete,
)
from src.services.catalog.read.facets_cache import build_facets_cache_key
from src.services.catalog.read.scope import (
    CatalogScope,
    require_complete_from_stock_filters,
)
from src.services.catalog.read.service import CatalogService
from src.services.product_service import ProductService
from src.utils.datetime_fmt import utc_now_naive
from src.web.admin_dashboard import _failed_dom_filters


def _compile(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def _product(
    *,
    description_raw: str = "Valid padel racket description for listing.",
    attempts: int = 0,
    last_error: str | None = None,
    is_active: bool = True,
    with_enrichment: bool = True,
    dom_full_at=None,
) -> Product:
    product = Product(
        title="Racket",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=1,
        is_active=is_active,
        external_id="p1",
        product_url="https://example.com/p1",
        description_raw=description_raw,
        dom_attempts=attempts,
        dom_last_error=last_error,
        dom_full_at=dom_full_at,
    )
    if with_enrichment:
        product.images = [ProductImage(url="https://example.com/i.jpg", position=0)]
        product.features = [ProductFeature(name="Color", value="Red", position=0)]
        if product.dom_full_at is None:
            product.dom_full_at = utc_now_naive()
    else:
        product.images = []
        product.features = []
    return product


def test_storefront_public_requires_complete() -> None:
    public = CatalogScope.storefront_public()
    assert public.require_complete is True
    assert public.list_filter_kwargs()["require_complete"] is True
    admin = CatalogScope.from_admin_mode("in_catalog")
    assert admin.require_complete is False
    assert admin.list_filter_kwargs()["require_complete"] is False


def test_admin_inactive_scope_does_not_require_complete() -> None:
    removed = CatalogScope.from_admin_mode("removed")
    assert removed.inactive_only is True
    assert removed.require_complete is False


def test_catalog_base_filters_exclude_hold_not_complete() -> None:
    repo = CrudProduct(session=None, model=Product)
    base = repo._catalog_base_filters()
    gated = repo._catalog_base_filters(require_complete=True)
    assert len(gated) == len(base) + 1
    compiled = _compile(gated[-1])
    assert "invalid_description" in compiled
    assert "invalid_gallery" in compiled
    assert "invalid_pdp" in compiled
    assert "not_found" not in compiled


def test_never_full_incomplete_is_not_hold() -> None:
    product = _product(with_enrichment=False, attempts=0, last_error=None)
    assert is_product_complete(product) is False
    assert is_enrichment_hold(product, 5) is False


def test_retry_pending_invalid_description_is_not_hold() -> None:
    product = _product(
        with_enrichment=False,
        attempts=4,
        last_error="invalid_description",
    )
    assert is_enrichment_hold(product, 5) is False


@pytest.mark.parametrize("error", list(HOLD_DOM_LAST_ERRORS))
def test_exhausted_invalid_errors_are_hold(error: str) -> None:
    product = _product(with_enrichment=False, attempts=5, last_error=error)
    assert is_product_complete(product) is False
    assert is_enrichment_hold(product, 5) is True


@pytest.mark.parametrize("error", ["not_found", "timeout", "captcha", "parser_error"])
def test_exhausted_other_errors_are_not_hold(error: str) -> None:
    product = _product(with_enrichment=False, attempts=5, last_error=error)
    assert is_enrichment_hold(product, 5) is False


def test_complete_product_is_not_hold() -> None:
    product = _product(attempts=0)
    assert is_product_complete(product) is True
    assert is_enrichment_hold(product, 5) is False


def test_hold_sql_matches_invalid_errors_only() -> None:
    compiled = _compile(enrichment_hold_sql_criterion(5))
    for error in HOLD_DOM_LAST_ERRORS:
        assert error in compiled
    assert "not_found" not in compiled
    assert "timeout" not in compiled
    assert "captcha" not in compiled


def test_failed_dom_hold_filter_uses_hold_predicate() -> None:
    hold = _failed_dom_filters(None, False, 5, hold_only=True)
    retry = _failed_dom_filters(None, True, 5, hold_only=False)
    assert len(hold) == 2
    compiled = " ".join(_compile(part) for part in hold)
    assert "invalid_description" in compiled
    assert "invalid_gallery" in compiled
    assert "invalid_pdp" in compiled
    assert "not_found" not in compiled
    assert len(retry) == 3


def test_require_complete_from_stock_filters_uses_scope_when_absent() -> None:
    public = CatalogScope.storefront_public()
    admin = CatalogScope.from_admin_mode("in_catalog")
    assert require_complete_from_stock_filters({}, public) is True
    assert require_complete_from_stock_filters({}, admin) is False
    assert (
        require_complete_from_stock_filters({"require_complete": False}, public)
        is False
    )
    assert (
        require_complete_from_stock_filters({"require_complete": True}, admin) is True
    )


@pytest.mark.asyncio
async def test_resolve_catalog_filters_no_keyerror_when_require_complete_absent() -> (
    None
):
    service = CatalogService(session=MagicMock())
    service.get_catalog_top_categories = AsyncMock(return_value=["Padel"])
    service.get_catalog_categories = AsyncMock(return_value=["Shoes"])
    service.get_catalog_brands = AsyncMock(return_value=["Babolat"])
    result = await service._resolve_catalog_filters(
        top="Padel",
        category="Shoes",
        brand=None,
        scope=CatalogScope.storefront_public(),
        preferred_order=("Padel",),
    )
    assert result.selected_category == "Shoes"
    kwargs = service.get_catalog_brands.await_args.kwargs
    assert kwargs["require_complete"] is True


def test_storefront_require_complete_propagates_through_brands_tree() -> None:
    kwargs = CatalogScope.storefront_public().catalog_read_kwargs()
    assert kwargs["require_complete"] is True
    admin = CatalogScope.from_admin_mode("in_catalog").catalog_read_kwargs()
    assert admin["require_complete"] is False
    brand_params = inspect.signature(CatalogService.get_catalog_brands).parameters
    tree_params = inspect.signature(
        CatalogService.get_top_category_product_counts_mapping
    ).parameters
    nav_params = inspect.signature(CatalogService.get_catalog_navigation).parameters
    assert "require_complete" in brand_params
    assert "require_complete" in tree_params
    assert "require_complete" in nav_params


@pytest.mark.asyncio
async def test_facets_cache_key_differs_for_require_complete() -> None:
    with patch(
        "src.services.catalog.read.facets_cache.get_catalog_version",
        new=AsyncMock(return_value=3),
    ):
        off = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
            require_complete=False,
        )
        on = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
            require_complete=True,
        )
    assert off != on


@pytest.mark.asyncio
async def test_pdp_hides_hold_and_keeps_never_full() -> None:
    service = ProductService(session=MagicMock())
    service.catalog.is_brand_storefront_visible = AsyncMock(return_value=True)

    hold = _product(with_enrichment=False, attempts=5, last_error="invalid_description")
    hold.supplier_price_eur = 10
    never_full = _product(with_enrichment=False, attempts=0, last_error=None)
    never_full.supplier_price_eur = 10

    with patch("src.services.product_service.default_dom_max_attempts", return_value=5):
        service.get_product = AsyncMock(return_value=hold)
        assert await service.get_product_for_storefront(1) is None
        service.get_product = AsyncMock(return_value=never_full)
        assert await service.get_product_for_storefront(1) is never_full
