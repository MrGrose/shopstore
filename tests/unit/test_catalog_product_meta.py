import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.schemas.catalog import (
    CatalogFacetOptionSchema,
    CatalogFacetsSchema,
    CatalogProductMetaSchema,
)
from src.services.catalog.read.service import CatalogService


def _sample_facets() -> CatalogFacetsSchema:
    return CatalogFacetsSchema(
        brands=[
            CatalogFacetOptionSchema(value="Babolat", label_ru="Babolat", count=5),
        ],
        genders=[
            CatalogFacetOptionSchema(value="men", label_ru="Мужской", count=3),
        ],
        colors=[],
        sizes=[],
        price_min=Decimal("1000"),
        price_max=Decimal("50000"),
    )


@pytest.mark.asyncio
async def test_get_catalog_product_meta_returns_count_and_facets() -> None:
    session = MagicMock()
    service = CatalogService(session)
    facets = _sample_facets()
    service.get_catalog_product_count = AsyncMock(return_value=42)
    service.get_catalog_facets = AsyncMock(return_value=facets)

    result = await service.get_catalog_product_meta(top_category="Padel")

    assert result == CatalogProductMetaSchema(total=42, facets=facets)
    service.get_catalog_product_count.assert_awaited_once()
    service.get_catalog_facets.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_catalog_product_meta_passes_shared_filters() -> None:
    session = MagicMock()
    service = CatalogService(session)
    service.get_catalog_product_count = AsyncMock(return_value=1)
    service.get_catalog_facets = AsyncMock(return_value=_sample_facets())

    await service.get_catalog_product_meta(
        top_category="Padel",
        brands=["Babolat"],
        genders=["men"],
        colors=["Black"],
        sizes=["M"],
        price_min=Decimal("1000"),
        price_max=Decimal("5000"),
        q="racket",
        include="core",
        mapping_release_id=7,
        chip_node_ids=(11, 12),
    )

    service.get_catalog_product_count.assert_awaited_once_with(
        top_category="Padel",
        category=None,
        categories=None,
        category_l3=None,
        brands=["Babolat"],
        genders=["men"],
        colors=["Black"],
        sizes=["M"],
        price_min=Decimal("1000"),
        price_max=Decimal("5000"),
        q="racket",
        include_out_of_stock=False,
        zero_stock_only=False,
        inactive_only=False,
        exclude_over_supplier_unit_cap=False,
        require_complete=False,
        exclude_hidden_brands=False,
        mapping_release_id=7,
        chip_node_ids=(11, 12),
    )
    service.get_catalog_facets.assert_awaited_once_with(
        top_category="Padel",
        category=None,
        categories=None,
        category_l3=None,
        brands=["Babolat"],
        genders=["men"],
        colors=["Black"],
        sizes=["M"],
        price_min=Decimal("1000"),
        price_max=Decimal("5000"),
        q="racket",
        include_out_of_stock=False,
        zero_stock_only=False,
        inactive_only=False,
        include="core",
        exclude_hidden_brands=False,
        exclude_over_supplier_unit_cap=False,
        require_complete=False,
        mapping_release_id=7,
        chip_node_ids=(11, 12),
    )


@pytest.mark.asyncio
async def test_get_catalog_product_meta_gathers_count_and_facets_in_parallel() -> None:
    session = MagicMock()
    service = CatalogService(session)
    started: list[str] = []
    release = asyncio.Event()

    async def count_products(**_kwargs: object) -> int:
        started.append("count")
        await release.wait()
        return 7

    async def load_facets(**_kwargs: object) -> CatalogFacetsSchema:
        started.append("facets")
        await release.wait()
        return _sample_facets()

    service.get_catalog_product_count = AsyncMock(side_effect=count_products)
    service.get_catalog_facets = AsyncMock(side_effect=load_facets)

    with patch(
        "src.services.catalog.read.service.asyncio.gather",
        new=asyncio.gather,
    ):
        task = asyncio.create_task(
            service.get_catalog_product_meta(top_category="Padel")
        )
        await asyncio.sleep(0.01)
        assert started == ["count", "facets"]
        release.set()
        result = await task

    assert result.total == 7
    assert result.facets.genders[0].value == "men"


@pytest.mark.asyncio
async def test_get_catalog_product_meta_matches_separate_calls() -> None:
    session = MagicMock()
    service = CatalogService(session)
    facets = _sample_facets()
    service.get_catalog_product_count = AsyncMock(return_value=99)
    service.get_catalog_facets = AsyncMock(return_value=facets)

    meta = await service.get_catalog_product_meta(
        top_category="Tennis",
        brands=["Wilson"],
        include="all",
    )
    count = await service.get_catalog_product_count(
        top_category="Tennis",
        brands=["Wilson"],
    )
    separate_facets = await service.get_catalog_facets(
        top_category="Tennis",
        brands=["Wilson"],
        include="all",
    )

    assert meta.total == count
    assert meta.facets == separate_facets
