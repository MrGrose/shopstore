from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.catalog.stock.boundary import RefreshStockResult
from src.services.product_service import ProductService


@pytest.mark.asyncio
@patch("src.services.product_service.invalidate_catalog_read_caches")
@patch("src.services.product_service.CatalogStockService")
async def test_bulk_set_active_by_top_category_refreshes_and_invalidates(
    mock_stock_cls,
    mock_invalidate,
) -> None:
    session = MagicMock()
    service = ProductService(session)
    service.product_crud.bulk_set_active_by_top_category = AsyncMock(
        return_value=[10, 11]
    )

    stock_service = MagicMock()
    stock_service.refresh_products = AsyncMock(
        return_value=RefreshStockResult(refreshed=2)
    )
    mock_stock_cls.return_value = stock_service
    session.commit = AsyncMock()

    updated = await service.bulk_set_active_by_top_category("Padel", False)

    assert updated == 2
    service.product_crud.bulk_set_active_by_top_category.assert_awaited_once_with(
        "Padel",
        False,
        category_l2=None,
    )
    stock_service.refresh_products.assert_awaited_once_with([10, 11])
    session.commit.assert_awaited_once()
    mock_invalidate.assert_called_once_with(
        reason="product_bulk_set_active_by_top_category"
    )


@pytest.mark.asyncio
@patch("src.services.product_service.invalidate_catalog_read_caches")
@patch("src.services.product_service.CatalogStockService")
async def test_bulk_set_active_by_top_category_skips_when_no_rows(
    mock_stock_cls,
    mock_invalidate,
) -> None:
    session = MagicMock()
    service = ProductService(session)
    service.product_crud.bulk_set_active_by_top_category = AsyncMock(return_value=[])

    updated = await service.bulk_set_active_by_top_category("Tennis", True)

    assert updated == 0
    mock_stock_cls.assert_not_called()
    mock_invalidate.assert_not_called()
