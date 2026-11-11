import pytest
from sqlalchemy import func, select

from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.services.catalog import CatalogService


# zero_stock_only: catalog_in_stock=false, не products.stock.
def test_zero_stock_base_filter_uses_catalog_in_stock() -> None:
    repo = CrudProduct(session=None, model=Product)
    filters = repo._catalog_base_filters(zero_stock_only=True)
    assert len(filters) == 2
    assert filters[0].left.key == "is_active"
    assert filters[1].left.key == "catalog_in_stock"


async def test_zero_stock_admin_summary_matches_active_oos() -> None:
    async with async_session_maker() as session:
        svc = CatalogService(session)
        admin_summary = await svc.get_catalog_admin_summary()
        active_oos = await session.scalar(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.catalog_in_stock.is_(False),
            )
        )
    assert (
        admin_summary["included"]
        == admin_summary["visible"] + admin_summary["not_visible"]
    )
    assert admin_summary["reason_zero_stock"] <= int(active_oos or 0)


async def test_zero_stock_list_excludes_stock_drift_products() -> None:
    async with async_session_maker() as session:
        drift_ids = list(
            await session.scalars(
                select(Product.id).where(
                    Product.is_active.is_(True),
                    Product.stock == 0,
                    Product.catalog_in_stock.is_(True),
                )
            )
        )
        if not drift_ids:
            pytest.skip("нет товаров stock=0 при catalog_in_stock=true")

        svc = CatalogService(session)
        items, total, _ = await svc.product_crud.paginate_products(
            page=1,
            page_size=max(len(drift_ids) + 50, 100),
            zero_stock_only=True,
        )
        listed_ids = {int(item.id) for item in items}
        assert not listed_ids.intersection(drift_ids)
        assert total is not None
        assert total == await session.scalar(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.catalog_in_stock.is_(False),
            )
        )


async def test_zero_stock_list_includes_active_oos_products() -> None:
    async with async_session_maker() as session:
        oos_id = await session.scalar(
            select(Product.id)
            .where(
                Product.is_active.is_(True),
                Product.catalog_in_stock.is_(False),
            )
            .limit(1)
        )
        if oos_id is None:
            pytest.skip("нет активных товаров без остатка")

        svc = CatalogService(session)
        _, total, _ = await svc.product_crud.paginate_products(
            page=1,
            page_size=100,
            zero_stock_only=True,
        )
        found = False
        for page in range(1, ((int(total or 0) + 99) // 100) + 1):
            items, _, _ = await svc.product_crud.paginate_products(
                page=page,
                page_size=100,
                zero_stock_only=True,
            )
            found = found or int(oos_id) in {int(item.id) for item in items}
        assert found
