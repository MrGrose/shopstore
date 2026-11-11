from datetime import datetime
from types import SimpleNamespace

from src.models.order import (
    AvailabilityConfirmationStatus,
    OrderStatus,
    SupplierOrderStatus,
)
from src.services.orders.admin_action_rail import resolve_admin_action_rail
from src.services.orders.supplier_orders import packing_assembly_complete


def _order(**kwargs):
    defaults = {
        "status": OrderStatus.CREATED,
        "availability_confirmation_status": AvailabilityConfirmationStatus.NOT_REQUIRED,
        "payment_state": "not_started",
        "payment_paid_at": None,
        "supplier_order_id": None,
        "supplier_tracking_id": None,
        "late_payment_after_auto_cancel": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_not_required_unpaid_active_payment() -> None:
    rail = resolve_admin_action_rail(_order())
    assert rail["active_step"] == "payment"
    assert rail["steps"]["payment"]["state"] == "active"
    assert rail["steps"]["payment"]["waiting"] is True
    assert rail["steps"]["payment"]["waiting_message"]
    assert rail["steps"]["composition"]["state"] == "locked"
    assert rail["steps"]["composition"]["body_editable"] is True
    assert rail["flow_steps"] == (
        "availability",
        "composition",
        "payment",
        "assembly",
        "delivery",
    )
    assert rail["steps"]["assembly"]["state"] == "locked"
    assert rail["steps"]["assembly"]["body_editable"] is True


def test_pending_active_availability_payment_locked() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.PROCESSING,
            availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
        )
    )
    assert rail["active_step"] == "availability"
    assert rail["steps"]["availability"]["state"] == "active"
    assert rail["steps"]["composition"]["body_editable"] is False
    assert rail["steps"]["availability"]["notify_visible"] is True
    assert rail["steps"]["availability"]["notify_default"] is True
    assert rail["steps"]["availability"]["notify_hint"] == "Результат проверки наличия"
    assert rail["steps"]["payment"]["state"] == "locked"
    assert "после проверки наличия" in (rail["steps"]["payment"]["hint"] or "")


def test_availability_outbox_pending_flag() -> None:
    order = _order(
        id=42,
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
    )
    rail = resolve_admin_action_rail(
        order,
        outbox_by_key={"customer:availability.notify:order:42": "pending"},
    )
    assert rail["steps"]["availability"]["notify_outbox_pending"] is True


def test_availability_outbox_pending_flag_telegram_suffix() -> None:
    order = _order(
        id=42,
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
    )
    rail = resolve_admin_action_rail(
        order,
        outbox_by_key={"customer:availability.notify:order:42:telegram": "pending"},
    )
    assert rail["steps"]["availability"]["notify_outbox_pending"] is True


def test_delivery_step_hides_notify_checkbox() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.ASSEMBLING,
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
            supplier_order_id="TP-123",
        )
    )
    assert rail["steps"]["delivery"]["notify_visible"] is False


def test_confirmed_unpaid_active_payment() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.PROCESSING,
            availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        )
    )
    assert rail["active_step"] == "payment"
    assert rail["steps"]["availability"]["state"] == "done"


def test_paid_active_assembly() -> None:
    rail = resolve_admin_action_rail(
        _order(
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
        )
    )
    assert rail["active_step"] == "assembly"
    assert rail["steps"]["payment"]["state"] == "done"
    assert rail["steps"]["assembly"]["state"] == "active"
    assert rail["steps"]["assembly"]["notify_default"] is True


def test_processing_confirmed_paid_can_start_assembly() -> None:
    from src.services.orders.order_service import OrderService

    order = _order(
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
        payment_state="paid",
        payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
    )
    assert OrderService.can_start_assembling(order) is True
    rail = resolve_admin_action_rail(order)
    assert rail["active_step"] == "assembly"


def test_paid_state_without_paid_at_can_start_assembly() -> None:
    from src.services.orders.order_service import OrderService

    order = _order(
        status=OrderStatus.PROCESSING,
        payment_state="paid",
        payment_paid_at=None,
    )
    assert OrderService.can_start_assembling(order) is True
    rail = resolve_admin_action_rail(order)
    assert rail["active_step"] == "assembly"


def test_assembling_without_supplier_id_active_assembly() -> None:
    from src.services.orders.order_service import OrderService

    order = _order(
        status=OrderStatus.ASSEMBLING,
        payment_state="paid",
        payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
        supplier_order_id=None,
    )
    assert OrderService.can_start_assembling(order) is True
    rail = resolve_admin_action_rail(order)
    assert rail["active_step"] == "assembly"
    assert rail["steps"]["assembly"]["state"] == "active"


def test_supplier_order_id_active_delivery() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.ASSEMBLING,
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
            supplier_order_id="TP-123",
        )
    )
    assert rail["active_step"] == "delivery"
    assert rail["steps"]["assembly"]["state"] == "done"
    assert rail["steps"]["delivery"]["state"] == "active"


def test_completed_terminal_readonly() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.COMPLETED,
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
            supplier_order_id="TP-123",
        )
    )
    assert rail["active_step"] == "terminal"
    assert rail["steps"]["payment"]["state"] == "done"
    assert rail["steps"]["delivery"]["state"] == "done"
    assert rail["steps"]["assembly"]["open"] is False


def test_cancelled_terminal() -> None:
    rail = resolve_admin_action_rail(_order(status=OrderStatus.CANCELLED))
    assert rail["active_step"] == "terminal"
    assert rail["alert"] is not None
    assert "отменён" in rail["alert"].lower()


def test_unavailable_terminal() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.PROCESSING,
            availability_confirmation_status=AvailabilityConfirmationStatus.UNAVAILABLE,
        )
    )
    assert rail["active_step"] == "terminal"
    assert rail["steps"]["availability"]["state"] == "locked"
    assert "недоступен" in (rail["alert"] or "").lower()


def test_delivery_status_active_finalize() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.DELIVERY,
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
            supplier_order_id="TP-123",
            supplier_tracking_id="CJ-456",
        )
    )
    assert rail["active_step"] == "delivery"
    assert rail["steps"]["delivery"]["state"] == "active"
    assert rail["steps"]["finalize"]["state"] == "hidden"
    assert "finalize" not in rail["flow_steps"]


def test_tracking_keeps_delivery_monitoring_open() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.ASSEMBLING,
            payment_state="paid",
            payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
            supplier_order_id="TP-123",
            supplier_tracking_id="CJ-456",
        )
    )
    assert rail["active_step"] == "delivery"
    assert rail["steps"]["delivery"]["state"] == "active"


def test_late_paid_after_cancel_alert_assembly_locked() -> None:
    rail = resolve_admin_action_rail(
        _order(
            status=OrderStatus.CANCELLED,
            payment_state="late_paid_after_cancel",
            payment_paid_at=datetime(2026, 7, 17, 12, 0, 0),
            late_payment_after_auto_cancel=True,
        )
    )
    assert rail["active_step"] == "terminal"
    assert rail["alert"] is not None
    assert "автоотмены" in rail["alert"].lower()
    assert rail["steps"]["assembly"]["state"] == "locked"
    assert "недоступна" in (rail["steps"]["assembly"]["hint"] or "").lower()


def test_paid_without_tp_stays_assembly_for_packing() -> None:
    order = _order(
        payment_state="paid",
        payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
    )
    rail = resolve_admin_action_rail(order)
    assert rail["active_step"] == "assembly"


def _so(seq: int, status: str, qty: int = 1, external_id: str = "TP-1", so_id: int = 1):
    return SimpleNamespace(
        id=so_id,
        seq=seq,
        status=status,
        external_id=external_id,
        lines=[SimpleNamespace(quantity=qty)] if qty else [],
        line_qty_by_item_id={1: qty} if qty else {},
    )


def _paid_assembling(**kwargs):
    return _order(
        status=OrderStatus.ASSEMBLING,
        payment_state="paid",
        payment_paid_at=datetime(2026, 7, 17, 10, 0, 0),
        **kwargs,
    )


def test_one_placed_fully_allocated_completes_assembly() -> None:
    packing = {"fully_allocated": True, "placed_count": 1, "placeable_count": 1}
    rail = resolve_admin_action_rail(
        _paid_assembling(supplier_order_id="TP-1"),
        packing=packing,
        supplier_orders=[_so(1, SupplierOrderStatus.PLACED, 1, "TP-1", 10)],
    )
    assert rail["active_step"] == "delivery"
    assert rail["steps"]["assembly"]["state"] == "done"


def test_two_so_one_draft_keeps_assembly_despite_first_tp() -> None:
    packing = {"fully_allocated": False, "placed_count": 1, "placeable_count": 2}
    rail = resolve_admin_action_rail(
        _paid_assembling(supplier_order_id="TP-1"),
        packing=packing,
        supplier_orders=[
            _so(1, SupplierOrderStatus.PLACED, 1, "TP-1", 10),
            _so(2, SupplierOrderStatus.DRAFT, 1, None, 11),
        ],
    )
    assert rail["active_step"] == "assembly"
    assert rail["steps"]["assembly"]["state"] == "active"
    assert rail["steps"]["delivery"]["state"] != "active"


def test_two_placed_fully_allocated_opens_delivery() -> None:
    packing = {"fully_allocated": True, "placed_count": 2, "placeable_count": 2}
    rail = resolve_admin_action_rail(
        _paid_assembling(supplier_order_id="TP-1"),
        packing=packing,
        supplier_orders=[
            _so(1, SupplierOrderStatus.PLACED, 1, "TP-1", 10),
            _so(2, SupplierOrderStatus.PLACED, 1, "TP-2", 11),
        ],
    )
    assert rail["active_step"] == "delivery"
    assert rail["steps"]["assembly"]["queue_summary"] == "2 / 2 оформлены"


def test_cancelled_so_does_not_block_assembly_complete() -> None:
    packing = {"fully_allocated": True, "placed_count": 1, "placeable_count": 1}
    rail = resolve_admin_action_rail(
        _paid_assembling(supplier_order_id="TP-1"),
        packing=packing,
        supplier_orders=[
            _so(1, SupplierOrderStatus.PLACED, 1, "TP-1", 10),
            _so(2, SupplierOrderStatus.CANCELLED, 1, "TP-X", 11),
        ],
    )
    assert rail["active_step"] == "delivery"


def test_empty_draft_does_not_block_assembly_complete() -> None:
    assert packing_assembly_complete(
        True,
        [
            (SupplierOrderStatus.PLACED, 2),
            (SupplierOrderStatus.DRAFT, 0),
            (SupplierOrderStatus.CANCELLED, 5),
        ],
    )
    packing = {"fully_allocated": True, "placed_count": 1, "placeable_count": 1}
    rail = resolve_admin_action_rail(
        _paid_assembling(supplier_order_id="TP-1"),
        packing=packing,
        supplier_orders=[
            _so(1, SupplierOrderStatus.PLACED, 2, "TP-1", 10),
            _so(2, SupplierOrderStatus.DRAFT, 0, None, 11),
        ],
    )
    assert rail["active_step"] == "delivery"


def test_legacy_tp_without_so_list_still_opens_delivery() -> None:
    rail = resolve_admin_action_rail(_paid_assembling(supplier_order_id="TP-123"))
    assert rail["active_step"] == "delivery"
