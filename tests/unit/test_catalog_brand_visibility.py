import pytest
from sqlalchemy import select

from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.schemas.catalog import ADMIN_BRANDS_PAGE_SIZE
from src.services.catalog import CatalogService
from src.services.catalog.read.scope import CatalogScope


@pytest.mark.asyncio
async def test_hidden_brand_excluded_from_storefront_paginate() -> None:
    async with async_session_maker() as session:
        brand_row = await session.scalar(
            select(Product.brand)
            .where(Product.brand.is_not(None), Product.brand != "")
            .limit(1)
        )
        if not brand_row:
            pytest.skip("нет товаров с брендом")
        brand = str(brand_row)
        svc = CatalogService(session)
        await svc.set_brand_storefront_visible(brand, visible=False)

        items, total, _ = await svc.get_products_list(
            page=1,
            page_size=500,
            exclude_hidden_brands=True,
        )
        assert brand not in {row.brand for row in items}
        assert all(row.brand != brand for row in items)

        admin_items, admin_total, _ = await svc.get_products_list(
            page=1,
            page_size=500,
            q=brand,
            exclude_hidden_brands=False,
        )
        assert any(row.brand == brand for row in admin_items)

        await svc.set_brand_storefront_visible(brand, visible=True)


@pytest.mark.asyncio
async def test_storefront_search_by_hidden_brand_empty() -> None:
    async with async_session_maker() as session:
        brand_row = await session.scalar(
            select(Product.brand)
            .where(Product.brand.is_not(None), Product.brand != "")
            .limit(1)
        )
        if not brand_row:
            pytest.skip("нет товаров с брендом")
        brand = str(brand_row)
        svc = CatalogService(session)
        await svc.set_brand_storefront_visible(brand, visible=False)

        items, total, _ = await svc.get_products_list(
            page=1,
            page_size=50,
            q=brand,
            exclude_hidden_brands=True,
        )
        assert all(row.brand != brand for row in items)
        if total is not None:
            hidden_only, hidden_total, _ = await svc.get_products_list(
                page=1,
                page_size=1,
                q=brand,
                exclude_hidden_brands=False,
            )
            assert hidden_total and hidden_total > 0
            assert any(row.brand == brand for row in hidden_only)

        await svc.set_brand_storefront_visible(brand, visible=True)


@pytest.mark.asyncio
async def test_list_admin_brand_rows_filters_by_query() -> None:
    async with async_session_maker() as session:
        rows, total, _, _, _ = await CatalogService(session).list_admin_brand_rows(
            page_size=5000
        )
        if not rows:
            pytest.skip("нет брендов")
        sample = str(rows[0]["brand"])
        term = sample[: max(2, len(sample) // 2)].lower()
        filtered, filtered_total, _, _, _ = await CatalogService(
            session
        ).list_admin_brand_rows(q=term, page_size=5000)
        assert filtered
        assert all(term in str(row["brand"]).lower() for row in filtered)
        assert filtered_total <= total


@pytest.mark.asyncio
async def test_list_admin_brand_rows_paginates() -> None:
    async with async_session_maker() as session:
        svc = CatalogService(session)
        page_rows, brand_total, _, total_pages, page = await svc.list_admin_brand_rows(
            page=1
        )
        assert page == 1
        assert len(page_rows) <= ADMIN_BRANDS_PAGE_SIZE
        if brand_total > ADMIN_BRANDS_PAGE_SIZE:
            assert total_pages > 1
            assert len(page_rows) == ADMIN_BRANDS_PAGE_SIZE
            (
                last_page_rows,
                _,
                _,
                total_pages_high,
                page_high,
            ) = await svc.list_admin_brand_rows(page=9999)
            assert page_high == total_pages_high
            assert len(last_page_rows) <= ADMIN_BRANDS_PAGE_SIZE


@pytest.mark.asyncio
async def test_list_admin_brand_rows_filters_by_visibility() -> None:
    async with async_session_maker() as session:
        svc = CatalogService(session)
        summary = await svc.get_admin_brands_summary()
        if summary["total_brands"] == 0:
            pytest.skip("нет брендов")
        visible_rows, visible_total, _, _, _ = await svc.list_admin_brand_rows(
            visibility="visible",
            page_size=5000,
        )
        hidden_rows, hidden_total, _, _, _ = await svc.list_admin_brand_rows(
            visibility="hidden",
            page_size=5000,
        )
        assert visible_total == summary["visible_brands"]
        assert hidden_total == summary["hidden_brands"]
        assert all(row["storefront_visible"] for row in visible_rows)
        assert all(not row["storefront_visible"] for row in hidden_rows)


def test_storefront_public_read_kwargs_exclude_hidden_brands() -> None:
    read_kwargs = CatalogScope.storefront_public().catalog_read_kwargs()
    assert read_kwargs["exclude_hidden_brands"] is True
    assert read_kwargs["exclude_over_supplier_unit_cap"] is True
    assert read_kwargs["require_complete"] is True
    stock_kwargs = CatalogScope.storefront_public().list_filter_kwargs()
    assert "exclude_hidden_brands" not in stock_kwargs
    assert stock_kwargs["exclude_over_supplier_unit_cap"] is True
    assert stock_kwargs["require_complete"] is True


@pytest.mark.asyncio
async def test_set_brand_storefront_visible_refreshes_hidden_brands_cache() -> None:
    from src.core.cache import set_reference_ttl_cache

    async with async_session_maker() as session:
        brand_row = await session.scalar(
            select(Product.brand)
            .where(Product.brand.is_not(None), Product.brand != "")
            .limit(1)
        )
        if not brand_row:
            pytest.skip("нет товаров с брендом")
        brand = str(brand_row)
        svc = CatalogService(session)
        set_reference_ttl_cache("catalog:hidden_brands", frozenset())

        await svc.set_brand_storefront_visible(brand, visible=False)
        hidden = await svc.get_hidden_brands_set()
        assert brand in hidden

        await svc.set_brand_storefront_visible(brand, visible=True)
        hidden_after = await svc.get_hidden_brands_set()
        assert brand not in hidden_after


def test_append_hidden_brands_filter_skips_empty_set() -> None:
    repo = CrudProduct(session=None, model=Product)
    filters: list = []
    repo._append_hidden_brands_filter(filters, Product, None)
    repo._append_hidden_brands_filter(filters, Product, frozenset())
    assert filters == []
