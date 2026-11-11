import pytest
from sqlalchemy import select

from src.models.order import Order
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.product_service import (
    PRODUCT_ADMIN_ORDER_HISTORY_PAGE_SIZE,
    ProductService,
)


@pytest.mark.asyncio
async def test_list_orders_for_product_returns_rows() -> None:
    async with async_session_maker() as session:
        product_id = await session.scalar(select(Product.id).limit(1))
        if product_id is None:
            pytest.skip("нет товаров")
        repo = CrudOrder(session=session, model=Order)
        rows = await repo.list_orders_for_product(int(product_id), page=1, page_size=5)
        assert isinstance(rows, list)
        for row in rows:
            assert "order_id" in row
            assert "quantity" in row
            assert int(row["quantity"]) >= 1


@pytest.mark.asyncio
async def test_count_orders_for_product_matches_list() -> None:
    async with async_session_maker() as session:
        product_id = await session.scalar(select(Product.id).limit(1))
        if product_id is None:
            pytest.skip("нет товаров")
        pid = int(product_id)
        repo = CrudOrder(session=session, model=Order)
        total = await repo.count_orders_for_product(pid)
        rows = await repo.list_orders_for_product(
            pid,
            page=1,
            page_size=max(total, 1),
        )
        assert len(rows) == total


@pytest.mark.asyncio
async def test_product_order_history_page_size_and_clamp() -> None:
    async with async_session_maker() as session:
        product_id = await session.scalar(select(Product.id).limit(1))
        if product_id is None:
            pytest.skip("нет товаров")
        svc = ProductService(session)
        rows, total, total_pages, page = await svc.get_product_order_history_page(
            int(product_id), page=1
        )
        assert page == 1
        assert len(rows) <= PRODUCT_ADMIN_ORDER_HISTORY_PAGE_SIZE
        if total > PRODUCT_ADMIN_ORDER_HISTORY_PAGE_SIZE:
            assert total_pages > 1
            (
                _,
                _,
                total_pages_high,
                page_high,
            ) = await svc.get_product_order_history_page(int(product_id), page=9999)
            assert page_high == total_pages_high
