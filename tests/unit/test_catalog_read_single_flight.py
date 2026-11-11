import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.catalog.read.service import CatalogService


@pytest.mark.asyncio
async def test_get_catalog_product_count_single_flight_coalesces_db_calls() -> None:
    session = MagicMock()
    service = CatalogService(session)
    crud_calls = 0

    async def count_products(**_kwargs) -> int:
        nonlocal crud_calls
        crud_calls += 1
        await asyncio.sleep(0.05)
        return 42

    service.product_crud = MagicMock()
    service.product_crud.count_catalog_products = AsyncMock(side_effect=count_products)
    service._hidden_brands_for_read = AsyncMock(return_value=frozenset())

    with (
        patch(
            "src.services.catalog.read.service.build_count_cache_key",
            new=AsyncMock(return_value="catalog:count:v1:test"),
        ),
        patch(
            "src.services.catalog.read.service.get_cached_count",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.services.catalog.read.service.set_cached_count",
            new=AsyncMock(),
        ),
        patch("src.core.config.settings.CATALOG_COUNT_CACHE_TTL_SECONDS", 120),
    ):
        results = await asyncio.gather(
            service.get_catalog_product_count(top_category="Padel"),
            service.get_catalog_product_count(top_category="Padel"),
            service.get_catalog_product_count(top_category="Padel"),
            service.get_catalog_product_count(top_category="Padel"),
            service.get_catalog_product_count(top_category="Padel"),
        )

    assert results == [42, 42, 42, 42, 42]
    assert crud_calls == 1
