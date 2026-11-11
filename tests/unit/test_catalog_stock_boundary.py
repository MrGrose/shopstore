from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.product import Product
from src.services.catalog.read.caches import invalidate_if_catalog_boundary_changed
from src.services.catalog.stock.boundary import storefront_visible
from src.services.catalog.stock.service import CatalogStockService


def test_storefront_visible_requires_active_and_in_stock() -> None:
    assert storefront_visible(True, True) is True
    assert storefront_visible(True, False) is False
    assert storefront_visible(False, True) is False


@pytest.mark.asyncio
async def test_refresh_batch_detects_visible_to_hidden_flip(monkeypatch) -> None:
    product = Product(
        id=1,
        is_active=True,
        catalog_in_stock=True,
        stock=1,
        title="t",
        brand="b",
        sale_price=100,
        supplier_price_eur=10,
    )
    product.variants = []

    session = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = [product]
    session.scalars = AsyncMock(return_value=scalars_result)
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    order_crud = MagicMock()
    order_crud.get_reserved_quantities = AsyncMock(return_value={1: 1})
    order_crud.get_reserved_quantities_by_variant = AsyncMock(return_value={})

    service = CatalogStockService(session=session)
    service.order_crud = order_crud

    result = await service._refresh_products_batch([1])

    assert result.refreshed == 1
    assert result.boundary_flipped_ids == [1]


@pytest.mark.asyncio
async def test_refresh_batch_no_flip_when_stays_visible(monkeypatch) -> None:
    product = Product(
        id=2,
        is_active=True,
        catalog_in_stock=True,
        stock=5,
        title="t",
        brand="b",
        sale_price=100,
        supplier_price_eur=10,
    )
    product.variants = []

    session = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = [product]
    session.scalars = AsyncMock(return_value=scalars_result)
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    order_crud = MagicMock()
    order_crud.get_reserved_quantities = AsyncMock(return_value={2: 0})
    order_crud.get_reserved_quantities_by_variant = AsyncMock(return_value={})

    service = CatalogStockService(session=session)
    service.order_crud = order_crud

    result = await service._refresh_products_batch([2])

    assert result.refreshed == 1
    assert result.boundary_flipped_ids == []


@pytest.mark.parametrize(
    ("product_id", "catalog_in_stock", "stock", "reserved", "available", "flips"),
    [
        pytest.param(3, True, 5, 2, 3, [], id="stock_5_to_3"),
        pytest.param(4, False, 5, 0, 5, [4], id="manual_stock_0_to_5"),
    ],
)
@pytest.mark.asyncio
async def test_stock_refresh_does_not_change_pricing(
    product_id: int,
    catalog_in_stock: bool,
    stock: int,
    reserved: int,
    available: int,
    flips: list[int],
) -> None:
    product = Product(
        id=product_id,
        is_active=True,
        catalog_in_stock=catalog_in_stock,
        stock=stock,
        title="t",
        brand="b",
        sale_price=1300,
        regular_price=1300,
        supplier_price_eur=10,
        pricing_category_key="Padel:balls",
    )
    product.variants = []
    session = MagicMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = [product]
    session.scalars = AsyncMock(return_value=scalars_result)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    service = CatalogStockService(session=session)
    service.order_crud = MagicMock(
        get_reserved_quantities=AsyncMock(return_value={product_id: reserved}),
        get_reserved_quantities_by_variant=AsyncMock(return_value={}),
    )

    result = await service._refresh_products_batch([product_id])

    update_statement = session.execute.await_args.args[0]
    assert update_statement.compile().params["available_qty"] == available
    assert result.boundary_flipped_ids == flips
    assert product.sale_price == 1300
    assert product.regular_price == 1300
    assert product.pricing_category_key == "Padel:balls"


@patch("src.services.catalog.read.caches.invalidate_catalog_read_caches")
def test_invalidate_if_catalog_boundary_changed_skips_empty(mock_invalidate) -> None:
    assert invalidate_if_catalog_boundary_changed([], "order_stock_boundary") is False
    mock_invalidate.assert_not_called()


@patch("src.services.catalog.read.caches.invalidate_catalog_read_caches")
def test_invalidate_if_catalog_boundary_changed_on_flip(mock_invalidate) -> None:
    assert invalidate_if_catalog_boundary_changed([1], "dom_stock_boundary") is True
    mock_invalidate.assert_called_once_with(reason="dom_stock_boundary")
