from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.models.product import Product
from src.repositories.product_repo import CrudProduct


@pytest.mark.asyncio
async def test_get_catalog_facets_price_bounds_ignore_own_price_filter() -> None:
    repo = CrudProduct(session=AsyncMock(), model=Product)
    contexts: dict[str, object] = {}

    async def capture_run(ctx, fetcher):
        contexts[fetcher.__name__] = ctx
        if fetcher.__name__ == "_fetch_facet_prices":
            return Decimal("1000"), Decimal("50000")
        if fetcher.__name__ == "_fetch_facet_colors":
            return {}
        return []

    with patch(
        "src.repositories.product_repo._run_catalog_facet_query",
        side_effect=capture_run,
    ):
        await repo.get_catalog_facets(
            brands=["Babolat"],
            price_min=Decimal("10000"),
            price_max=Decimal("30000"),
            include="all",
        )

    brand_ctx = contexts["_fetch_facet_brands"]
    price_ctx = contexts["_fetch_facet_prices"]
    assert brand_ctx.filters != price_ctx.filters
    assert len(brand_ctx.filters) > len(price_ctx.filters)


@pytest.mark.asyncio
async def test_get_catalog_facets_price_bounds_reuse_ctx_without_price_filter() -> None:
    repo = CrudProduct(session=AsyncMock(), model=Product)
    build_calls: list[tuple[Decimal | None, Decimal | None]] = []
    original_build = repo._build_catalog_facet_context

    def tracked_build(*args, **kwargs):
        build_calls.append((kwargs.get("price_min"), kwargs.get("price_max")))
        return original_build(*args, **kwargs)

    repo._build_catalog_facet_context = tracked_build  # type: ignore[method-assign]

    async def capture_run(_ctx, fetcher):
        if fetcher.__name__ == "_fetch_facet_prices":
            return Decimal("1000"), Decimal("50000")
        return []

    with patch(
        "src.repositories.product_repo._run_catalog_facet_query",
        side_effect=capture_run,
    ):
        await repo.get_catalog_facets(brands=["Babolat"], include="prices")

    assert build_calls == [(None, None)]


@pytest.mark.asyncio
async def test_price_bounds_stable_across_price_filter_values() -> None:
    repo = CrudProduct(session=AsyncMock(), model=Product)

    async def capture_run(_ctx, fetcher):
        if fetcher.__name__ == "_fetch_facet_prices":
            return Decimal("1000"), Decimal("5000")
        return []

    with patch(
        "src.repositories.product_repo._run_catalog_facet_query",
        side_effect=capture_run,
    ):
        without_price = await repo.get_catalog_facets(include="prices")
        with_price = await repo.get_catalog_facets(
            include="prices",
            price_min=Decimal("2000"),
            price_max=Decimal("4000"),
        )

    assert without_price["price_min"] == with_price["price_min"] == Decimal("1000")
    assert without_price["price_max"] == with_price["price_max"] == Decimal("5000")


@pytest.mark.asyncio
async def test_price_bounds_context_includes_search_query() -> None:
    repo = CrudProduct(session=AsyncMock(), model=Product)
    captured: list[dict[str, object]] = []
    original = repo._build_catalog_facet_context

    def spy(*args, **kwargs):
        captured.append(kwargs)
        return original(*args, **kwargs)

    repo._build_catalog_facet_context = spy  # type: ignore[method-assign]

    async def capture_run(_ctx, fetcher):
        if fetcher.__name__ == "_fetch_facet_prices":
            return Decimal("1000"), Decimal("5000")
        return []

    with patch(
        "src.repositories.product_repo._run_catalog_facet_query",
        side_effect=capture_run,
    ):
        await repo.get_catalog_facets(include="prices", q="mizuno")

    assert captured
    assert captured[0]["q"] == "mizuno"


@pytest.mark.asyncio
async def test_brand_facet_counts_keep_price_filter_in_context() -> None:
    repo = CrudProduct(session=AsyncMock(), model=Product)
    contexts: dict[str, object] = {}

    async def capture_run(ctx, fetcher):
        contexts[fetcher.__name__] = ctx
        if fetcher.__name__ == "_fetch_facet_prices":
            return Decimal("1000"), Decimal("50000")
        if fetcher.__name__ == "_fetch_facet_brands":
            return [{"value": "Babolat", "count": 2}]
        return []

    with patch(
        "src.repositories.product_repo._run_catalog_facet_query",
        side_effect=capture_run,
    ):
        await repo.get_catalog_facets(
            brands=["Babolat"],
            price_min=Decimal("10000"),
            price_max=Decimal("30000"),
            include="brands,prices",
        )

    brand_filters = tuple(contexts["_fetch_facet_brands"].filters)
    price_filters = tuple(contexts["_fetch_facet_prices"].filters)
    assert brand_filters != price_filters
    assert len(brand_filters) > len(price_filters)
