from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog import CatalogService
from src.services.catalog.display.admin_status import admin_product_tree_status
from src.services.catalog.display.constants import (
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
)
from src.services.catalog.read.scope import normalize_admin_catalog_tree


async def _require_active_release(session):
    repo = StorefrontMappingRepository(session)
    active = await repo.get_active_release()
    if active is None:
        pytest.skip("no active storefront release")
    return active


@pytest.mark.asyncio
async def test_admin_tree_summary_partitions() -> None:
    async with async_session_maker() as session:
        await _require_active_release(session)
        summary = await CatalogService(session).get_catalog_admin_summary(
            top_category="All"
        )

    assert summary["total"] == summary["included"] + summary["excluded"]
    assert summary["included"] == summary["visible"] + summary["not_visible"]
    assert summary["reason_supplier_limit"] >= 0
    assert summary["reason_zero_stock"] >= 0
    assert (
        summary["reason_supplier_limit"]
        + summary["reason_zero_stock"]
        + summary["reason_orphan"]
        + summary["reason_mapping_excluded"]
        >= 0
    )


@pytest.mark.asyncio
async def test_admin_tree_summary_category_changes_total() -> None:
    async with async_session_maker() as session:
        await _require_active_release(session)
        svc = CatalogService(session)
        all_summary = await svc.get_catalog_admin_summary(top_category="Tennis")
        state = await svc.build_catalog_page_state(
            page=1,
            page_size=1,
            top="Tennis",
            scope=None,
            include_admin_summary=False,
        )
        if not state.categories:
            pytest.skip("no tennis categories")
        category = state.categories[0]
        sliced = await svc.get_catalog_admin_summary(
            top_category="Tennis",
            category=category,
        )

    assert sliced["total"] <= all_summary["total"]
    assert sliced["total"] == sliced["included"] + sliced["excluded"]
    assert sliced["included"] == sliced["visible"] + sliced["not_visible"]


@pytest.mark.asyncio
async def test_admin_tree_summary_ignores_search() -> None:
    async with async_session_maker() as session:
        await _require_active_release(session)
        svc = CatalogService(session)
        tree = normalize_admin_catalog_tree("all", "all", "all")
        without_q = await svc.build_catalog_page_state(
            page=1,
            page_size=5,
            top="All",
            q=None,
            include_admin_summary=True,
            admin_tree=tree,
        )
        with_q = await svc.build_catalog_page_state(
            page=1,
            page_size=5,
            top="All",
            q="zzzzzz-no-such-product",
            include_admin_summary=True,
            admin_tree=tree,
        )

    assert without_q.catalog_summary == with_q.catalog_summary
    assert without_q.catalog_summary is not None
    assert (with_q.total or 0) <= (without_q.total or 0)


# Ищет SKU по независимым placement/resolution clauses, не через orphan helper.
async def _first_product(session, *clauses):
    return (
        (await session.execute(select(Product).where(*clauses).limit(1)))
        .scalars()
        .first()
    )


# Row / summary / listing filter для reason=orphan должны совпасть.
@pytest.mark.asyncio
async def test_mapped_without_chip_is_orphan_everywhere() -> None:
    async with async_session_maker() as session:
        active = await _require_active_release(session)
        svc = CatalogService(session)
        hidden = await svc.get_hidden_brands_set()
        repo = CrudProduct(session=session, model=Product)
        product = await _first_product(
            session,
            repo._admin_included_clause(hidden),
            Product.catalog_in_stock.is_(True),
            repo._supplier_cap_ok_clause(),
            repo._resolution_status_exists(active.id, (RESOLUTION_MAPPED,)),
            ~repo._resolution_status_exists(active.id, (RESOLUTION_EXCLUDED,)),
            ~repo._active_chip_placement_exists(active.id),
        )
        if product is None:
            pytest.skip("no mapped in-stock under-cap SKU without chip placement")

        status = admin_product_tree_status(
            is_active=bool(product.is_active),
            catalog_in_stock=bool(product.catalog_in_stock),
            brand=product.brand,
            supplier_price_eur=product.supplier_price_eur,
            hidden_brands=hidden,
            has_placement=False,
            resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
        )
        assert status.site == "not_visible"
        assert status.reasons == ("orphan",)

        tree = normalize_admin_catalog_tree("included", "not_visible", "orphan")
        filters: list = []
        repo._append_admin_tree_filters(filters, tree, hidden, active.id)
        found = await session.scalar(
            select(Product.id).where(Product.id == product.id, *filters)
        )
        assert found == product.id

        in_count = await session.scalar(
            select(func.count())
            .select_from(Product)
            .where(
                Product.id == product.id,
                repo._admin_included_clause(hidden),
                repo._admin_orphan_clause(active.id),
            )
        )
        assert int(in_count or 0) == 1
        summary = await svc.get_catalog_admin_summary(top_category="All")
        assert summary["reason_orphan"] >= 1


# mapping_excluded без chip не должен попадать в orphan filter/count.
@pytest.mark.asyncio
async def test_mapping_excluded_without_chip_is_not_orphan() -> None:
    async with async_session_maker() as session:
        active = await _require_active_release(session)
        svc = CatalogService(session)
        hidden = await svc.get_hidden_brands_set()
        repo = CrudProduct(session=session, model=Product)
        product = await _first_product(
            session,
            repo._admin_included_clause(hidden),
            repo._resolution_status_exists(active.id, (RESOLUTION_EXCLUDED,)),
            ~repo._active_chip_placement_exists(active.id),
        )
        if product is None:
            pytest.skip("no mapping_excluded SKU without chip placement")

        status = admin_product_tree_status(
            is_active=bool(product.is_active),
            catalog_in_stock=bool(product.catalog_in_stock),
            brand=product.brand,
            supplier_price_eur=product.supplier_price_eur,
            hidden_brands=hidden,
            has_placement=False,
            resolution=SimpleNamespace(status=RESOLUTION_EXCLUDED),
        )
        assert "mapping_excluded" in status.reasons
        assert "orphan" not in status.reasons

        orphan_tree = normalize_admin_catalog_tree("included", "not_visible", "orphan")
        orphan_filters: list = []
        repo._append_admin_tree_filters(orphan_filters, orphan_tree, hidden, active.id)
        found_orphan = await session.scalar(
            select(Product.id).where(Product.id == product.id, *orphan_filters)
        )
        assert found_orphan is None

        excluded_tree = normalize_admin_catalog_tree(
            "included", "not_visible", "mapping_excluded"
        )
        excluded_filters: list = []
        repo._append_admin_tree_filters(
            excluded_filters, excluded_tree, hidden, active.id
        )
        found_excluded = await session.scalar(
            select(Product.id).where(Product.id == product.id, *excluded_filters)
        )
        assert found_excluded == product.id


# Mapped + chip + stock + under cap — VISIBLE, не orphan.
@pytest.mark.asyncio
async def test_mapped_with_chip_is_visible_not_orphan() -> None:
    async with async_session_maker() as session:
        active = await _require_active_release(session)
        svc = CatalogService(session)
        hidden = await svc.get_hidden_brands_set()
        repo = CrudProduct(session=session, model=Product)
        product = await _first_product(
            session,
            repo._admin_included_clause(hidden),
            Product.catalog_in_stock.is_(True),
            repo._supplier_cap_ok_clause(),
            repo._resolution_status_exists(active.id, (RESOLUTION_MAPPED,)),
            repo._active_chip_placement_exists(active.id),
        )
        if product is None:
            pytest.skip("no mapped in-stock under-cap SKU with chip placement")

        status = admin_product_tree_status(
            is_active=bool(product.is_active),
            catalog_in_stock=bool(product.catalog_in_stock),
            brand=product.brand,
            supplier_price_eur=product.supplier_price_eur,
            hidden_brands=hidden,
            has_placement=True,
            resolution=SimpleNamespace(status=RESOLUTION_MAPPED),
        )
        assert status.site == "visible"
        assert status.reasons == ()

        orphan_tree = normalize_admin_catalog_tree("included", "not_visible", "orphan")
        orphan_filters: list = []
        repo._append_admin_tree_filters(orphan_filters, orphan_tree, hidden, active.id)
        found_orphan = await session.scalar(
            select(Product.id).where(Product.id == product.id, *orphan_filters)
        )
        assert found_orphan is None

        visible_tree = normalize_admin_catalog_tree("included", "visible", "all")
        visible_filters: list = []
        repo._append_admin_tree_filters(
            visible_filters, visible_tree, hidden, active.id
        )
        found_visible = await session.scalar(
            select(Product.id).where(Product.id == product.id, *visible_filters)
        )
        assert found_visible == product.id
