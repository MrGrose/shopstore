import re
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from src.main import app
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderItem,
    OrderStatus,
)
from src.repositories.session import async_session_maker
from src.schemas.order import (
    AdminAvailabilityItemDecision,
    AdminAvailabilityStockCheckUpdate,
)
from src.services.orders.order_service import OrderService
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_pending_availability_order,
    create_telegram_user,
    pick_active_product_id,
    pick_two_product_line_specs,
    resolve_product_line_spec,
)


@pytest.mark.asyncio
async def test_availability_save_check_post_submits_all_decisions(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    item_ids: list[int] = []
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        try:
            product_specs = await pick_two_product_line_specs(session)
        except RuntimeError:
            pytest.skip("нужно минимум 2 активных товара в каталоге")

        order, items = await create_pending_availability_order(
            session,
            user_id=buyer.id,
            product_specs=product_specs,
        )
        order_id = order.id
        item_ids = [item.id for item in items]
        _, admin_token = await create_admin_access_token(session, suffix + 1)

    form_data = {
        "action": "save_check",
        f"availability_item_{item_ids[0]}_decision": "confirmed",
        f"availability_item_{item_ids[1]}_decision": "confirmed",
        "event_message": "Проверено на складе",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/internal/admin/orders/{order_id}/availability",
            data=form_data,
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 303
    assert "success=" in response.headers.get("location", "")

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert (
            order.availability_confirmation_status
            == AvailabilityConfirmationStatus.CONFIRMED
        )
        remaining = list(
            (
                await session.scalars(
                    select(OrderItem).where(OrderItem.order_id == order_id)
                )
            ).all()
        )
        assert len(remaining) == 2


@pytest.mark.asyncio
async def test_availability_order_detail_radios_inside_form(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    item_id = 0
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, items = await create_pending_availability_order(
            session,
            user_id=buyer.id,
            product_specs=[line_spec],
        )
        order_id = order.id
        item_id = items[0].id
        _, admin_token = await create_admin_access_token(session, suffix + 2)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            f"/internal/admin/orders?id={order_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    html = response.text
    form_pattern = re.compile(
        rf'<form[^>]*id="order-availability-form-{order_id}"[^>]*>(.*?)</form>',
        re.S,
    )
    match = form_pattern.search(html)
    assert match is not None
    form_body = match.group(1)
    assert f'name="availability_item_{item_id}_decision"' in form_body
    assert f'form="order-availability-form-{order_id}"' in form_body


@pytest.mark.asyncio
async def test_save_availability_stock_check_confirms_all_positions(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        try:
            product_specs = await pick_two_product_line_specs(session)
        except RuntimeError:
            pytest.skip("нужно минимум 2 активных товара в каталоге")

        order, items = await create_pending_availability_order(
            session,
            user_id=buyer.id,
            product_specs=product_specs,
        )
        item_ids = [item.id for item in items]
        service = OrderService(session)
        order_schema, _warning = await service.save_availability_stock_check(
            order_id=order.id,
            payload=AdminAvailabilityStockCheckUpdate(
                items=[
                    AdminAvailabilityItemDecision(
                        order_item_id=item_ids[0], confirmed=True
                    ),
                    AdminAvailabilityItemDecision(
                        order_item_id=item_ids[1], confirmed=True
                    ),
                ],
            ),
            actor=buyer,
        )
        status = order_schema.availability_confirmation_status
        items_count = len(order_schema.items or [])

    assert status == "confirmed"
    assert items_count == 2


@pytest.mark.asyncio
async def test_save_availability_stock_check_removes_one_position(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        try:
            product_specs = await pick_two_product_line_specs(session)
        except RuntimeError:
            pytest.skip("нужно минимум 2 активных товара в каталоге")

        order, items = await create_pending_availability_order(
            session,
            user_id=buyer.id,
            product_specs=product_specs,
        )
        reject_id, keep_id = items[0].id, items[1].id
        service = OrderService(session)
        order_schema, _warning = await service.save_availability_stock_check(
            order_id=order.id,
            payload=AdminAvailabilityStockCheckUpdate(
                items=[
                    AdminAvailabilityItemDecision(
                        order_item_id=reject_id, confirmed=False
                    ),
                    AdminAvailabilityItemDecision(
                        order_item_id=keep_id, confirmed=True
                    ),
                ],
            ),
            actor=buyer,
        )
        status = order_schema.availability_confirmation_status
        remaining_id = order_schema.items[0].id if order_schema.items else None
        remaining_count = len(order_schema.items or [])

    assert status == "confirmed"
    assert remaining_count == 1
    assert remaining_id == keep_id


@pytest.mark.asyncio
async def test_save_availability_stock_check_cancels_order_when_all_removed(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, items = await create_pending_availability_order(
            session,
            user_id=buyer.id,
            product_specs=[line_spec],
        )
        service = OrderService(session)
        order_schema, _warning = await service.save_availability_stock_check(
            order_id=order.id,
            payload=AdminAvailabilityStockCheckUpdate(
                items=[
                    AdminAvailabilityItemDecision(
                        order_item_id=items[0].id, confirmed=False
                    ),
                ],
            ),
            actor=buyer,
        )
        status = order_schema.status
        availability = order_schema.availability_confirmation_status
        items_count = len(order_schema.items or [])

    assert status == OrderStatus.CANCELLED
    assert availability == "unavailable"
    assert items_count == 0
