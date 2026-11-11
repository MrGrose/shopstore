import uuid
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import update

from src.main import app
from src.models.order import Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import (
    msk_date_end_exclusive_utc_naive,
    msk_date_start_utc_naive,
)
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)


async def _create_order_with_created_at(
    session,
    user_id: int,
    created_at: datetime,
    *,
    first_name: str | None = None,
    status: OrderStatus = OrderStatus.CREATED,
) -> Order:
    product_id = await pick_active_product_id(session)
    product_id, variant_id, price, qty = await resolve_product_line_spec(
        session, product_id, Decimal("100"), 1
    )
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.create_order_with_items(
        user_id=user_id,
        total_amount=Decimal("600"),
        items_subtotal_amount=Decimal("100"),
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=Decimal("500"),
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=None,
        items_payload=[
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "quantity": qty,
                "unit_price": price,
                "product_title_captured": f"Product {product_id}",
            }
        ],
        idempotency_key=f"date-filter-{uuid.uuid4()}",
        delivery_payload={
            "last_name": "Test",
            "first_name": first_name or "User",
            "street": "Test St",
            "house": "1",
            "city": "Moscow",
            "postal_code": "101000",
            "phone": "+79990000000",
        },
        availability_confirmation_status="not_required",
        status=status,
    )
    await order_crud.commit_order(order)
    await session.execute(
        update(Order)
        .where(Order.id == order.id)
        .values(created_at=created_at, status=status.value)
    )
    await session.commit()
    await session.refresh(order)
    return order


@pytest.mark.asyncio
async def test_list_admin_orders_single_day_msk(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix)
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 3, 22, 0, 0),
            first_name=f"msk_in_{merge_unique_suffix}",
        )
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 3, 20, 0, 0),
            first_name=f"msk_out_{merge_unique_suffix}",
        )
        service = OrderService(session)
        start = msk_date_start_utc_naive(date(2026, 7, 4))
        end = msk_date_end_exclusive_utc_naive(date(2026, 7, 4))
        listed_inside = await service.list_admin_orders(
            page=1,
            page_size=100,
            q=f"msk_in_{merge_unique_suffix}",
            created_from_utc=start,
            created_to_exclusive_utc=end,
        )
        listed_outside = await service.list_admin_orders(
            page=1,
            page_size=100,
            q=f"msk_out_{merge_unique_suffix}",
            created_from_utc=start,
            created_to_exclusive_utc=end,
        )
        assert int(listed_inside["total"]) == 1
        assert int(listed_outside["total"]) == 0


@pytest.mark.asyncio
async def test_list_admin_orders_count_matches_items(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix)
        marker = f"cnt{merge_unique_suffix}"
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 4, 1, 0, 0),
            first_name=marker,
        )
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 4, 2, 0, 0),
            first_name=marker,
        )
        service = OrderService(session)
        start = msk_date_start_utc_naive(date(2026, 7, 4))
        end = msk_date_end_exclusive_utc_naive(date(2026, 7, 4))
        listed = await service.list_admin_orders(
            page=1,
            page_size=100,
            q=marker,
            created_from_utc=start,
            created_to_exclusive_utc=end,
        )
        total = int(listed["total"])
        items = listed["items"]
        assert isinstance(items, list)
        assert total == len(items)


@pytest.mark.asyncio
async def test_admin_orders_table_partial_invalid_date_returns_200(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/orders/table",
            params={"date_from": "bad-date"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert "Некорректная дата" in response.text


@pytest.mark.asyncio
async def test_admin_orders_page_preserves_applied_dates(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/orders",
            params={"date_from": "2026-07-01", "date_to": "2026-07-04"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert 'data-applied-from="2026-07-01"' in response.text
    assert 'data-applied-to="2026-07-04"' in response.text


@pytest.mark.asyncio
async def test_admin_orders_status_counts_with_date_filter(
    merge_unique_suffix: int,
) -> None:
    marker = f"stcnt{merge_unique_suffix}"
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix)
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 4, 10, 0, 0),
            first_name=marker,
            status=OrderStatus.CREATED,
        )
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 4, 11, 0, 0),
            first_name=marker,
            status=OrderStatus.PROCESSING,
        )
        await _create_order_with_created_at(
            session,
            user.id,
            datetime(2026, 7, 1, 10, 0, 0),
            first_name=marker,
            status=OrderStatus.PROCESSING,
        )
        service = OrderService(session)
        start = msk_date_start_utc_naive(date(2026, 7, 4))
        end = msk_date_end_exclusive_utc_naive(date(2026, 7, 4))
        counts = await service.get_admin_orders_status_counts(
            q=marker,
            created_from_utc=start,
            created_to_exclusive_utc=end,
        )
    assert counts[""] == 2
    assert counts[OrderStatus.CREATED.value] == 1
    assert counts[OrderStatus.PROCESSING.value] == 1
    assert counts[OrderStatus.DELIVERY.value] == 0


@pytest.mark.asyncio
async def test_admin_orders_table_partial_returns_status_count_oob(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/orders/table",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert 'id="admin-orders-status-count-all"' in response.text
    assert "hx-swap-oob" in response.text
