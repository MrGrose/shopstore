from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.notifications.customer_notification_keys import (
    all_customer_outbox_keys,
    customer_outbox_keys_for_journey,
    shipment_delivered_notify_key,
)
from src.services.orders.order_service import OrderService
from src.services.orders.shipments import (
    SHIPMENT_CUSTOMER_NOTIFY_ORDER_STATUS,
    customer_notify_outbox_keys_for_cards,
)

OS = "src.services.orders.order_service"


def _row(
    shipment_id: int,
    order_id: int = 188,
    status: str = "delivered",
    completed_at: datetime | None = None,
    so_id: int = 1,
    cj: str = "CJ-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=shipment_id,
        order_id=order_id,
        status=status,
        completed_at=completed_at,
        supplier_order_id=so_id,
        supplier_tracking_number=cj,
    )


@pytest.fixture
def order_service() -> OrderService:
    session = AsyncMock()
    service = OrderService(session)
    service.order_crud = AsyncMock()
    service._build_admin_created_by = AsyncMock(return_value="admin@test")
    service._commit_enqueued_notifications = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_notify_one_shipment_uses_shipment_key(
    order_service: OrderService,
) -> None:
    order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[_row(11, so_id=2, cj="CJ-2")]
    )
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(
        return_value=[SimpleNamespace(id=2, seq=2)]
    )
    notify = AsyncMock(return_value=True)
    with patch(f"{OS}.CustomerNotificationService") as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        queued = await order_service.notify_shipments_delivered(
            188, [11], None, actor=MagicMock()
        )
    assert queued == 1
    notify.assert_awaited_once()
    kwargs = notify.await_args.kwargs
    assert kwargs["idempotency_key"] == shipment_delivered_notify_key(188, 11)
    assert kwargs["order_status"] == SHIPMENT_CUSTOMER_NOTIFY_ORDER_STATUS
    assert kwargs["custom_message"] == "По заказу 📦 #188 · Посылка №2 доставлена."
    order_service._commit_enqueued_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_two_shipments_independent_keys(
    order_service: OrderService,
) -> None:
    order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[
            _row(10, so_id=1, cj="CJ-1"),
            _row(11, so_id=2, cj="CJ-2"),
        ]
    )
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(
        return_value=[
            SimpleNamespace(id=1, seq=1),
            SimpleNamespace(id=2, seq=2),
        ]
    )
    notify = AsyncMock(return_value=True)
    with patch(f"{OS}.CustomerNotificationService") as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        queued = await order_service.notify_shipments_delivered(
            188, [10, 11], "Заказ #{order_id} · Посылка №{seq} · {cj}"
        )
    assert queued == 2
    keys = [call.kwargs["idempotency_key"] for call in notify.await_args_list]
    assert keys == [
        shipment_delivered_notify_key(188, 10),
        shipment_delivered_notify_key(188, 11),
    ]
    texts = [call.kwargs["custom_message"] for call in notify.await_args_list]
    assert "CJ-1" in texts[0] and "CJ-2" not in texts[0]
    assert "CJ-2" in texts[1] and "CJ-1" not in texts[1]


@pytest.mark.asyncio
async def test_notify_repeat_does_not_queue_duplicate(
    order_service: OrderService,
) -> None:
    order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[_row(11)]
    )
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(
        return_value=[SimpleNamespace(id=1, seq=1)]
    )
    notify = AsyncMock(return_value=False)
    with patch(f"{OS}.CustomerNotificationService") as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        queued = await order_service.notify_shipments_delivered(188, [11], None)
    assert queued == 0
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_skips_in_transit(order_service: OrderService) -> None:
    order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[_row(10, status="in_transit", cj="CJ-1")]
    )
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(return_value=[])
    notify = AsyncMock()
    with patch(f"{OS}.CustomerNotificationService") as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        with pytest.raises(ValueError, match="доставленную"):
            await order_service.notify_shipments_delivered(188, [10], None)
    notify.assert_not_called()


@pytest.mark.asyncio
async def test_notify_does_not_complete_or_finalize(
    order_service: OrderService,
) -> None:
    row = _row(11)
    order_service.order_crud.list_shipments_for_order = AsyncMock(return_value=[row])
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(
        return_value=[SimpleNamespace(id=1, seq=1)]
    )
    notify = AsyncMock(return_value=True)
    finalize = AsyncMock()
    completed_alert = AsyncMock()
    with (
        patch(f"{OS}.CustomerNotificationService") as notify_cls,
        patch(f"{OS}.OrderService.finalize_order_delivery", finalize),
        patch(f"{OS}.sync_order_completed_admin_alert", completed_alert),
    ):
        notify_cls.return_value.notify_order_status = notify
        await order_service.notify_shipments_delivered(188, [11], None)
    assert row.completed_at is None
    finalize.assert_not_called()
    completed_alert.assert_not_called()


@pytest.mark.asyncio
async def test_notify_wrong_order_does_not_send(
    order_service: OrderService,
) -> None:
    order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[_row(11, order_id=186)]
    )
    order_service.order_crud.list_placed_supplier_orders = AsyncMock(return_value=[])
    notify = AsyncMock()
    with patch(f"{OS}.CustomerNotificationService") as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        with pytest.raises(ValueError, match="не найдена"):
            await order_service.notify_shipments_delivered(188, [11], None)
    notify.assert_not_called()


def test_all_customer_outbox_keys_are_order_scoped() -> None:
    keys = all_customer_outbox_keys(188)
    assert all(":shipment:" not in key for key in keys)
    assert shipment_delivered_notify_key(188, 11) not in keys
    cards = [MagicMock(id=11)]
    extra = customer_notify_outbox_keys_for_cards(188, cards)
    assert shipment_delivered_notify_key(188, 11) in extra


def test_customer_outbox_keys_for_journey_include_shipment_b() -> None:
    order_keys = all_customer_outbox_keys(188)
    keys = customer_outbox_keys_for_journey(188, [11, 12])
    assert keys[: len(order_keys)] == order_keys
    assert shipment_delivered_notify_key(188, 11) in keys
    assert shipment_delivered_notify_key(188, 12) in keys
    assert len(keys) == len(set(keys))


def test_customer_outbox_keys_for_journey_without_shipments_match_order_level() -> None:
    assert customer_outbox_keys_for_journey(188) == all_customer_outbox_keys(188)
    assert customer_outbox_keys_for_journey(188, []) == all_customer_outbox_keys(188)


def test_customer_outbox_keys_for_journey_dedupes_shipment_ids() -> None:
    key = shipment_delivered_notify_key(188, 11)
    keys = customer_outbox_keys_for_journey(188, [11, 11])
    assert keys.count(key) == 1
