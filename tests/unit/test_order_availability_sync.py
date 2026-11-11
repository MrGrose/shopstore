from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive


def test_reserve_positions_changed_add_remove() -> None:
    assert (
        OrderService._reserve_positions_changed(
            [{"order_item_id": 1}],
            [],
            [],
        )
        is True
    )
    assert (
        OrderService._reserve_positions_changed(
            [],
            [{"order_item_id": 1}],
            [],
        )
        is True
    )


def test_reserve_positions_changed_quantity_only() -> None:
    changed = [
        {
            "before": {
                "product_id": 1,
                "variant_id": None,
                "quantity": 1,
                "unit_price": "100",
            },
            "after": {
                "product_id": 1,
                "variant_id": None,
                "quantity": 2,
                "unit_price": "100",
            },
        }
    ]
    assert OrderService._reserve_positions_changed([], [], changed) is True


def test_reserve_positions_changed_price_only() -> None:
    changed = [
        {
            "before": {
                "product_id": 1,
                "variant_id": None,
                "quantity": 1,
                "unit_price": "100",
            },
            "after": {
                "product_id": 1,
                "variant_id": None,
                "quantity": 1,
                "unit_price": "120",
            },
        }
    ]
    assert OrderService._reserve_positions_changed([], [], changed) is False


def test_low_stock_signature_preserves_duplicate_lines() -> None:
    items = [
        {"product_id": 1, "variant_id": None, "quantity": 1},
        {"product_id": 1, "variant_id": None, "quantity": 1},
    ]
    assert OrderService._low_stock_signature(items) == [(1, None, 1), (1, None, 1)]


def test_composition_edit_state_paid_and_final() -> None:
    paid = SimpleNamespace(
        payment_paid_at=utc_now_naive(),
        status=OrderStatus.PROCESSING,
    )
    cancelled = SimpleNamespace(
        payment_paid_at=None,
        status=OrderStatus.CANCELLED,
    )
    allowed, reason, qr = OrderService.composition_edit_state(paid, None)
    assert allowed is False
    assert reason == "Нельзя изменить оплаченный заказ"
    assert qr is None
    allowed, reason, _qr = OrderService.composition_edit_state(cancelled, None)
    assert allowed is False
    assert "завершённого" in (reason or "")


def test_composition_edit_state_active_qr() -> None:
    now = utc_now_naive()
    attempt = SimpleNamespace(
        qr_expires_at=now + timedelta(minutes=10),
        provider_status="QRCDATA_CREATED",
        provider_order_id="ext-1",
        init_state="ready",
    )
    order = SimpleNamespace(payment_paid_at=None, status=OrderStatus.PROCESSING)
    allowed, reason, qr_expires = OrderService.composition_edit_state(
        order, attempt, now=now
    )
    assert allowed is False
    assert "QR" in (reason or "")
    assert qr_expires == attempt.qr_expires_at


def test_composition_edit_state_expired_qr() -> None:
    now = utc_now_naive()
    attempt = SimpleNamespace(
        qr_expires_at=now - timedelta(minutes=1),
        provider_status="QRCDATA_CREATED",
        provider_order_id="ext-1",
        init_state="ready",
    )
    order = SimpleNamespace(payment_paid_at=None, status=OrderStatus.PROCESSING)
    allowed, reason, qr = OrderService.composition_edit_state(order, attempt, now=now)
    assert allowed is True
    assert reason is None
    assert qr is None


@pytest.mark.asyncio
async def test_last_availability_signature_uses_newest_event() -> None:
    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    service.order_crud.get_order_events = AsyncMock(
        return_value=[
            SimpleNamespace(
                event_type="availability_confirmation_requested",
                payload_json={
                    "items": [
                        {"product_id": 2, "variant_id": None, "quantity": 1},
                    ]
                },
            ),
            SimpleNamespace(
                event_type="availability_confirmation_requested",
                payload_json={
                    "items": [
                        {"product_id": 1, "variant_id": None, "quantity": 1},
                    ]
                },
            ),
        ]
    )
    result = await service._last_availability_requested_signature(1)
    assert result == [(2, None, 1)]


@pytest.mark.asyncio
async def test_recompute_partial_low_stock_stays_pending() -> None:
    service = OrderService.__new__(OrderService)
    order = SimpleNamespace(
        id=1,
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
        payment_due_at=None,
    )
    low_stock_row = {
        "product_id": 2,
        "variant_id": None,
        "quantity": 1,
        "product_title": "Low",
        "variant_label": None,
        "available": 1,
        "stock_badge": "последний",
    }
    service._collect_low_stock_items_for_order = AsyncMock(return_value=[low_stock_row])
    service._available_by_reserve_key_excluding_order = AsyncMock(
        return_value=({}, {}, {})
    )
    service._last_availability_requested_signature = AsyncMock(return_value=None)
    service.order_crud = AsyncMock()
    service.order_crud.create_order_event = AsyncMock()
    service._sync_order_status_from_availability = AsyncMock(return_value=False)

    before, after = await service._recompute_order_availability(order, [])

    assert before == AvailabilityConfirmationStatus.PENDING
    assert after == AvailabilityConfirmationStatus.PENDING
    assert order.payment_due_at is None
    service.order_crud.create_order_event.assert_awaited_once()


def test_status_target_from_availability() -> None:
    assert (
        OrderService._status_target_from_availability(
            AvailabilityConfirmationStatus.PENDING
        )
        == OrderStatus.PROCESSING
    )
    assert (
        OrderService._status_target_from_availability(
            AvailabilityConfirmationStatus.CONFIRMED
        )
        == OrderStatus.CREATED
    )


def test_allowed_next_statuses_for_order_created_paid_no_delivery() -> None:
    order = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        failed_from_status=None,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert OrderStatus.DELIVERY not in allowed
    assert OrderStatus.ASSEMBLING not in allowed
    assert OrderStatus.PROCESSING not in allowed


def test_allowed_next_statuses_processing_no_manual_transitions() -> None:
    order = SimpleNamespace(
        status=OrderStatus.PROCESSING,
        payment_paid_at=utc_now_naive(),
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
    )
    service = OrderService.__new__(OrderService)
    allowed = service.allowed_next_statuses_for_order(order)
    assert OrderStatus.DELIVERY not in allowed
    assert OrderStatus.CREATED not in allowed


def test_allowed_next_statuses_failed_recovery_pending_and_unavailable() -> None:
    service = OrderService.__new__(OrderService)
    for availability in (
        AvailabilityConfirmationStatus.PENDING,
        AvailabilityConfirmationStatus.UNAVAILABLE,
    ):
        order = SimpleNamespace(
            status=OrderStatus.FAILED,
            payment_paid_at=None,
            availability_confirmation_status=availability,
            failed_from_status=None,
        )
        allowed = service.allowed_next_statuses_for_order(order)
        assert OrderStatus.PROCESSING in allowed
        assert OrderStatus.CREATED not in allowed


@pytest.mark.asyncio
async def test_sync_order_status_idempotent_no_event() -> None:
    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    order = SimpleNamespace(
        id=1,
        status=OrderStatus.CREATED,
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
    )
    changed = await service._sync_order_status_from_availability(
        order, created_by="system"
    )
    assert changed is False
    service.order_crud.create_order_event.assert_not_called()


@pytest.mark.asyncio
async def test_sync_order_status_writes_created_by() -> None:
    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    order = SimpleNamespace(
        id=1,
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
    )
    changed = await service._sync_order_status_from_availability(
        order, created_by="admin@test"
    )
    assert changed is True
    call_kwargs = service.order_crud.create_order_event.await_args.kwargs
    assert call_kwargs["created_by"] == "admin@test"
    assert call_kwargs["payload_json"]["reason"] == "availability_resolved"
