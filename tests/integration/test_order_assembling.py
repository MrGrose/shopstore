import httpx
import pytest
from sqlalchemy import select

from src.main import app
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderStatus,
)
from src.repositories.session import async_session_maker
from src.schemas.order import (
    AdminOrderStatusUpdate,
    AdminStartAssemblingUpdate,
    AdminStartDeliveryUpdate,
)
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)
from tests.integration.test_order_availability_sync import _create_processing_order


@pytest.mark.asyncio
async def test_start_assembling_happy_path(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = now
        await session.commit()
        order_id = order.id
        service = OrderService(session)
        result = await service.start_order_assembling(
            order_id,
            AdminStartAssemblingUpdate(
                supplier_order_id="SUP-100",
            ),
            actor=buyer,
        )
        assert result.status == OrderStatus.ASSEMBLING

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == OrderStatus.ASSEMBLING
        assert order.supplier_order_id == "SUP-100"
        assert order.supplier_tracking_id is None
        event = await session.scalar(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == "assembly_started",
            )
            .order_by(OrderEvent.id.desc())
        )
        assert event is not None


@pytest.mark.asyncio
async def test_start_assembling_rejects_unpaid(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 1)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        service = OrderService(session)
        with pytest.raises(ValueError, match="сборку"):
            await service.start_order_assembling(
                order.id,
                AdminStartAssemblingUpdate(
                    supplier_order_id="SUP-1",
                ),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_assembling_to_delivery(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 2)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = now
        order.status = OrderStatus.ASSEMBLING
        order.supplier_order_id = "SUP-2"
        await session.commit()
        service = OrderService(session)
        result = await service.start_order_delivery(
            order.id,
            AdminStartDeliveryUpdate(supplier_tracking_id="TRK-2"),
            actor=buyer,
        )
        assert result.status == OrderStatus.DELIVERY
        assert result.supplier_tracking_id == "TRK-2"


@pytest.mark.asyncio
async def test_start_delivery_post_saves_tracking_and_redirects(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 20)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.status = OrderStatus.ASSEMBLING
        order.supplier_order_id = "SUP-POST"
        await session.commit()
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 21)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/internal/admin/orders/{order_id}/start-delivery",
            data={"supplier_tracking_id": "TRK-POST"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 303
    assert "success=" in response.headers.get("location", "")
    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == OrderStatus.DELIVERY
        assert order.supplier_tracking_id == "TRK-POST"


@pytest.mark.asyncio
async def test_assembling_cannot_cancel(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 3)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = now
        order.status = OrderStatus.ASSEMBLING
        await session.commit()
        service = OrderService(session)
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.CANCELLED),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_failed_from_assembling_recovery(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 4)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = now
        order.status = OrderStatus.FAILED
        order.failed_from_status = OrderStatus.ASSEMBLING
        await session.commit()
        order_id = order.id
        service = OrderService(session)
        result = await service.update_order_status(
            order_id,
            AdminOrderStatusUpdate(status=OrderStatus.ASSEMBLING),
            actor=buyer,
        )
        assert result.status == OrderStatus.ASSEMBLING

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.failed_from_status is None
