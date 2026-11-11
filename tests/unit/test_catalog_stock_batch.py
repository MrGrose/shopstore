from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.order import Order
from src.repositories.order_repo import _SQL_IN_CHUNK, CrudOrder
from src.services.catalog.stock.boundary import RefreshStockResult
from src.services.catalog.stock.service import (
    _REFRESH_PRODUCTS_BATCH,
    CatalogStockService,
)

_ASYNC_PG_MAX_BINDS = 32767


def test_refresh_products_batch_under_asyncpg_limit() -> None:
    assert _REFRESH_PRODUCTS_BATCH < _ASYNC_PG_MAX_BINDS


def test_sql_in_chunk_under_asyncpg_limit() -> None:
    assert _SQL_IN_CHUNK < _ASYNC_PG_MAX_BINDS


def test_prod_finalize_scale_exceeds_asyncpg_without_batching() -> None:
    # Регрессия: ~4000+ деактиваций за finalize (локальная БД: 37627 variant binds).
    estimated_variant_binds = 37627
    assert estimated_variant_binds > _ASYNC_PG_MAX_BINDS


@pytest.mark.asyncio
async def test_refresh_products_splits_large_id_list(monkeypatch) -> None:
    batches: list[list[int]] = []

    async def fake_batch(self, ids: list[int]) -> RefreshStockResult:
        batches.append(list(ids))
        return RefreshStockResult(refreshed=len(ids))

    monkeypatch.setattr(CatalogStockService, "_refresh_products_batch", fake_batch)

    service = CatalogStockService(session=MagicMock())
    product_ids = list(range(1, 1251))

    result = await service.refresh_products(product_ids)

    assert result.refreshed == 1250
    assert len(batches) == 3
    assert len(batches[0]) == _REFRESH_PRODUCTS_BATCH
    assert len(batches[1]) == _REFRESH_PRODUCTS_BATCH
    assert len(batches[2]) == 250


@pytest.mark.asyncio
async def test_get_reserved_quantities_by_variant_batches_in_clause() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)

    crud = CrudOrder(session=session, model=Order)
    variant_ids = list(range(1, _SQL_IN_CHUNK + 2501))

    await crud.get_reserved_quantities_by_variant(variant_ids)

    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_get_reserved_quantities_batches_in_clause() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.all.return_value = []
    session.execute = AsyncMock(return_value=result_mock)

    crud = CrudOrder(session=session, model=Order)
    product_ids = list(range(1, _SQL_IN_CHUNK + 1501))

    await crud.get_reserved_quantities(product_ids)

    assert session.execute.await_count == 2
