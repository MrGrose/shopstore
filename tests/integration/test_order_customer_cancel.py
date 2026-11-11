from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from src.core.security import create_access_token
from src.main import app
from src.models.order import (
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    ORDER_EVENT_CANCELLED_BY_CUSTOMER,
    Order,
    OrderEvent,
    OrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from src.web.admin_labels import ORDER_EVENT_LABELS
from src.web.admin_order_events import format_order_event_rows
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)
from tests.integration.test_order_availability_sync import (
    _admin_get_order_detail,
    _create_processing_order,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_my_orders_exposes_customer_cancel_allowed_before_cancel(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    buyer_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        buyer_token = create_access_token(buyer.id)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/orders/my?page=1&page_size=10",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    assert response.status_code == 200
    rows = response.json()
    match = next((row for row in rows if row["id"] == order_id), None)
    assert match is not None
    assert match["status"] == OrderStatus.CREATED
    assert match["customer_cancel_allowed"] is True
    assert match["customer_cancel_blocked_reason"] in (None, "")


@pytest.mark.asyncio
async def test_customer_cancel_via_api_updates_order(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    buyer_token = ""
    order_id = 0

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        buyer_token = create_access_token(buyer.id)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == order_id
    assert body["status"] == OrderStatus.CANCELLED
    assert body["cancellation_reason"] == CANCELLATION_REASON_CUSTOMER_REQUEST
    assert body["customer_cancel_allowed"] is False

    async with async_session_maker() as session:
        refreshed = await session.get(Order, order_id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CANCELLED
        assert refreshed.cancellation_reason == CANCELLATION_REASON_CUSTOMER_REQUEST
        event = await session.scalar(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == ORDER_EVENT_CANCELLED_BY_CUSTOMER,
            )
            .order_by(OrderEvent.id.desc())
        )
        assert event is not None
        assert "клиентом" in (event.event_message or "").lower()


@pytest.mark.asyncio
async def test_customer_cancelled_order_hidden_from_my_orders(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 1000
    buyer_token = ""
    order_id = 0

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        buyer_token = create_access_token(buyer.id)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id
        await OrderService(session).cancel_order_by_customer(order_id, buyer.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/orders/my?page=1&page_size=20",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    assert response.status_code == 200
    match = next((row for row in response.json() if row["id"] == order_id), None)
    assert match is None


@pytest.mark.asyncio
async def test_customer_cancel_forbidden_for_other_user(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 2000
    order_id = 0
    other_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        other = await create_telegram_user(session, suffix + 1)
        other_token = create_access_token(other.id)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {other_token}"},
        )

    assert response.status_code == 400
    assert "не найден" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_customer_cancel_blocked_while_qr_alive(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix + 3000
    buyer_token = ""
    order_id = 0

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        buyer_token = create_access_token(buyer.id)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order_id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order_id}/1",
            x_req_id_order=f"shopstore-order-{order_id}-1",
            x_req_id_qr=f"shopstore-qrc-{order_id}-1",
            payment_amount_minor=60000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order_id)
        assert attempt is not None
        attempt.qr_expires_at = utc_now_naive() + timedelta(minutes=10)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        my_orders = await client.get(
            "/orders/my?page=1&page_size=10",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )
        cancel = await client.post(
            f"/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {buyer_token}"},
        )

    assert my_orders.status_code == 200
    match = next((row for row in my_orders.json() if row["id"] == order_id), None)
    assert match is not None
    assert match["customer_cancel_allowed"] is False
    assert match["customer_cancel_blocked_reason"]
    assert cancel.status_code == 400
    assert "QR" in cancel.json()["detail"]


@pytest.mark.asyncio
async def test_admin_order_detail_shows_customer_cancel_reason_and_timeline(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 4000
    order_id = 0
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id
        await OrderService(session).cancel_order_by_customer(order_id, buyer.id)
        _, admin_token = await create_admin_access_token(session, suffix + 1)

    response = await _admin_get_order_detail(order_id, admin_token)
    assert response.status_code == 200
    html = response.text
    assert ORDER_EVENT_LABELS["order_cancelled_by_customer"] in html


@pytest.mark.asyncio
async def test_admin_event_rows_label_customer_cancel(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix + 5000
    order_id = 0

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_due_at = utc_now_naive() + timedelta(hours=5)
        await session.commit()
        order_id = order.id
        service = OrderService(session)
        await service.cancel_order_by_customer(order_id, buyer.id)
        events = await service.get_order_events(order_id)

    rows = format_order_event_rows(
        events,
        event_labels=ORDER_EVENT_LABELS,
        status_labels={"cancelled": "Отменен"},
    )
    cancel_row = next(
        (row for row in rows if row["event_type"] == ORDER_EVENT_CANCELLED_BY_CUSTOMER),
        None,
    )
    assert cancel_row is not None
    assert cancel_row["title"] == "Клиент отменил заказ"
