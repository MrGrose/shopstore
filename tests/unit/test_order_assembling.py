from types import SimpleNamespace

import pytest

from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.schemas.order import AdminStartAssemblingUpdate, AdminStartDeliveryUpdate
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive


def test_can_start_assembling_requires_created_paid_availability() -> None:
    now = utc_now_naive()
    ok = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
    )
    assert OrderService.can_start_assembling(ok) is True
    unpaid = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=None,
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
    )
    assert OrderService.can_start_assembling(unpaid) is False
    pending = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
    )
    assert OrderService.can_start_assembling(pending) is False


def test_can_start_assembling_false_when_supplier_orders_or_packing() -> None:
    now = utc_now_naive()
    ok = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        supplier_order_id=None,
    )
    assert OrderService.can_start_assembling(ok) is True
    assert (
        OrderService.can_start_assembling(ok, supplier_orders=[SimpleNamespace(id=1)])
        is False
    )
    assert OrderService.can_start_assembling(ok, packing={"can_create": True}) is False
    assert (
        OrderService.can_start_assembling(ok, packing={"placeable_count": 1}) is False
    )


def test_allowed_next_statuses_created_no_delivery_or_assembling() -> None:
    order = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        failed_from_status=None,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert allowed == [OrderStatus.CANCELLED, OrderStatus.FAILED]
    assert OrderStatus.DELIVERY not in allowed
    assert OrderStatus.ASSEMBLING not in allowed


def test_allowed_next_statuses_assembling_uses_action_for_delivery() -> None:
    order = SimpleNamespace(
        status=OrderStatus.ASSEMBLING,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        failed_from_status=None,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert OrderStatus.DELIVERY not in allowed
    assert OrderStatus.FAILED in allowed
    assert OrderStatus.CANCELLED not in allowed


def test_allowed_next_statuses_failed_recovery_from_assembling() -> None:
    order = SimpleNamespace(
        status=OrderStatus.FAILED,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        failed_from_status=OrderStatus.ASSEMBLING,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert OrderStatus.ASSEMBLING in allowed
    assert OrderStatus.CREATED not in allowed
    assert OrderStatus.PROCESSING not in allowed


def test_allowed_next_statuses_failed_recovery_from_delivery() -> None:
    order = SimpleNamespace(
        status=OrderStatus.FAILED,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        failed_from_status=OrderStatus.DELIVERY,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert OrderStatus.DELIVERY in allowed
    assert OrderStatus.ASSEMBLING not in allowed


@pytest.mark.asyncio
async def test_start_order_assembling_commits_customer_notification_outbox() -> None:
    from unittest.mock import AsyncMock, patch

    service = OrderService.__new__(OrderService)
    service.session = AsyncMock()
    service.session.get = AsyncMock(return_value=None)
    service.order_crud = AsyncMock()
    service._commit_enqueued_notifications = AsyncMock()
    now = utc_now_naive()
    order = SimpleNamespace(
        id=7,
        user_id=1,
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        delivery_data_json={"city": "Moscow"},
        supplier_order_id=None,
        supplier_tracking_id=None,
        supplier_delivery_json=None,
    )
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.list_supplier_orders_for_order = AsyncMock(return_value=[])
    service.order_crud.create_order_event = AsyncMock()
    service.order_crud.commit_order = AsyncMock()
    service._build_admin_created_by = AsyncMock(return_value="admin@test")
    service._build_order_items = AsyncMock(return_value=[])
    service._build_order_schema_with_user = AsyncMock(
        return_value=SimpleNamespace(status=OrderStatus.ASSEMBLING)
    )
    notify = AsyncMock(return_value=True)

    payload = AdminStartAssemblingUpdate(
        supplier_order_id="SUP-42",
        notify_customer=True,
    )
    with patch(
        "src.services.orders.order_service.CustomerNotificationService"
    ) as notify_cls:
        notify_cls.return_value.notify_order_status = notify
        await service.start_order_assembling(7, payload, actor=None)

    notify.assert_awaited_once()
    service._commit_enqueued_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_order_assembling_sets_fields_and_event() -> None:
    from unittest.mock import AsyncMock

    service = OrderService.__new__(OrderService)
    service.session = AsyncMock()
    service.session.get = AsyncMock(return_value=None)
    service.order_crud = AsyncMock()
    now = utc_now_naive()
    order = SimpleNamespace(
        id=7,
        user_id=1,
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        delivery_data_json={"city": "Moscow"},
        supplier_order_id=None,
        supplier_tracking_id=None,
        supplier_delivery_json=None,
    )
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.list_supplier_orders_for_order = AsyncMock(return_value=[])
    service.order_crud.create_order_event = AsyncMock()
    service.order_crud.commit_order = AsyncMock()
    service._build_admin_created_by = AsyncMock(return_value="admin@test")
    service._build_order_items = AsyncMock(return_value=[])
    assembling_schema = SimpleNamespace(status=OrderStatus.ASSEMBLING)
    service._build_order_schema_with_user = AsyncMock(return_value=assembling_schema)

    payload = AdminStartAssemblingUpdate(
        supplier_order_id="SUP-42",
    )
    await service.start_order_assembling(7, payload, actor=None)

    assert order.status == OrderStatus.ASSEMBLING
    assert order.supplier_order_id == "SUP-42"
    assert order.supplier_delivery_json == {"city": "Moscow"}
    service.order_crud.create_order_event.assert_awaited_once()
    call_kwargs = service.order_crud.create_order_event.await_args.kwargs
    assert call_kwargs["event_type"] == "assembly_started"


@pytest.mark.asyncio
async def test_start_order_delivery_requires_tracking_and_sets_status() -> None:
    from unittest.mock import AsyncMock

    service = OrderService.__new__(OrderService)
    service.session = AsyncMock()
    service.session.get = AsyncMock(return_value=None)
    service.order_crud = AsyncMock()
    order = SimpleNamespace(
        id=8,
        user_id=1,
        status=OrderStatus.ASSEMBLING,
        supplier_tracking_id=None,
    )
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service._build_admin_created_by = AsyncMock(return_value="admin@test")
    service._build_order_items = AsyncMock(return_value=[])
    service._build_order_schema_with_user = AsyncMock(
        return_value=SimpleNamespace(status=OrderStatus.DELIVERY)
    )

    await service.start_order_delivery(
        8,
        AdminStartDeliveryUpdate(supplier_tracking_id="TRK-8"),
    )

    assert order.status == OrderStatus.DELIVERY
    assert order.supplier_tracking_id == "TRK-8"
    event = service.order_crud.create_order_event.await_args.kwargs
    assert event["event_type"] == "delivery_started"


@pytest.mark.asyncio
async def test_start_order_delivery_rejects_blank_tracking_without_writes() -> None:
    from unittest.mock import AsyncMock

    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    service.order_crud.get_by_id_for_update = AsyncMock(
        return_value=SimpleNamespace(
            id=9,
            status=OrderStatus.ASSEMBLING,
            supplier_tracking_id=None,
        )
    )

    with pytest.raises(ValueError, match="трек-номер"):
        await service.start_order_delivery(
            9,
            AdminStartDeliveryUpdate(supplier_tracking_id="   "),
        )

    service.order_crud.create_order_event.assert_not_awaited()
    service.order_crud.commit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_order_delivery_rejects_wrong_status() -> None:
    from unittest.mock import AsyncMock

    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    service.order_crud.get_by_id_for_update = AsyncMock(
        return_value=SimpleNamespace(id=10, status=OrderStatus.CREATED)
    )

    with pytest.raises(ValueError, match="только заказ в сборке"):
        await service.start_order_delivery(
            10,
            AdminStartDeliveryUpdate(supplier_tracking_id="TRK-10"),
        )

    service.order_crud.create_order_event.assert_not_awaited()
    service.order_crud.commit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_order_assembling_rejects_when_supplier_orders_exist() -> None:
    from unittest.mock import AsyncMock

    service = OrderService.__new__(OrderService)
    service.session = AsyncMock()
    service.order_crud = AsyncMock()
    now = utc_now_naive()
    order = SimpleNamespace(
        id=7,
        status=OrderStatus.CREATED,
        payment_paid_at=now,
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        supplier_order_id=None,
    )
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.list_supplier_orders_for_order = AsyncMock(
        return_value=[SimpleNamespace(id=99)]
    )
    payload = AdminStartAssemblingUpdate(supplier_order_id="SUP-42")
    with pytest.raises(ValueError, match="нельзя передать в сборку"):
        await service.start_order_assembling(7, payload, actor=None)
