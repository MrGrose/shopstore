from unittest.mock import AsyncMock, patch

import pytest

from src.services.catalog.read.facets_cache import build_facets_cache_key


@pytest.mark.asyncio
async def test_facets_cache_key_differs_for_price_range() -> None:
    with patch(
        "src.services.catalog.read.facets_cache.get_catalog_version",
        new=AsyncMock(return_value=3),
    ):
        low = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min="100",
            price_max="200",
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )
        high = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min="500",
            price_max="900",
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )

    assert low != high
    assert low.startswith("catalog:facets:v3:")
    assert high.startswith("catalog:facets:v3:")


@pytest.mark.asyncio
async def test_facets_cache_key_same_for_identical_price_range() -> None:
    with patch(
        "src.services.catalog.read.facets_cache.get_catalog_version",
        new=AsyncMock(return_value=1),
    ):
        first = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min="100",
            price_max=None,
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )
        second = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min="100",
            price_max=None,
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )

    assert first == second


@pytest.mark.asyncio
async def test_facets_cache_key_differs_for_search_query() -> None:
    with patch(
        "src.services.catalog.read.facets_cache.get_catalog_version",
        new=AsyncMock(return_value=2),
    ):
        without_q = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min=None,
            price_max=None,
            q=None,
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )
        with_q = await build_facets_cache_key(
            top_category="Padel",
            category=None,
            categories=None,
            category_l3=None,
            brands=None,
            genders=None,
            colors=None,
            sizes=None,
            price_min=None,
            price_max=None,
            q="mizuno",
            include_out_of_stock=False,
            zero_stock_only=False,
            inactive_only=False,
        )

    assert without_q != with_q
