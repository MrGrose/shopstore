from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.orders.order_service import OrderService


def _order(**kwargs):
    defaults = {
        "status": OrderStatus.CREATED,
        "availability_confirmation_status": AvailabilityConfirmationStatus.NOT_REQUIRED,
        "payment_paid_at": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_resolve_customer_status_label_created_unpaid() -> None:
    order = _order()
    assert OrderService.resolve_customer_status_label(order) == "Ожидает оплаты"


def test_resolve_customer_status_label_created_paid() -> None:
    order = _order(payment_paid_at=datetime(2026, 7, 17, 8, 52, 19))
    assert OrderService.resolve_customer_status_label(order) == "Оформляем у поставщика"


def test_resolve_customer_status_label_processing_pending() -> None:
    order = _order(
        status=OrderStatus.PROCESSING,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
    )
    assert OrderService.resolve_customer_status_label(order) == "Проверяем наличие"


def test_resolve_admin_status_label_created_paid() -> None:
    order = _order(payment_paid_at=datetime(2026, 7, 17, 8, 52, 19))
    assert OrderService.resolve_admin_status_label(order) == "Оплачен · ожидает TP"


def test_admin_status_select_context_hides_created_when_assembling_allowed() -> None:
    order = _order(payment_paid_at=datetime(2026, 7, 17, 8, 52, 19))
    choices, hint = OrderService.admin_status_select_context(
        order,
        [OrderStatus.CANCELLED, OrderStatus.FAILED],
    )
    assert choices == [OrderStatus.CANCELLED, OrderStatus.FAILED]
    assert hint == "Следующий шаг — блок «Сборка» ниже."


def test_admin_status_select_context_keeps_created_when_unpaid() -> None:
    order = _order()
    choices, hint = OrderService.admin_status_select_context(
        order,
        [OrderStatus.CANCELLED, OrderStatus.FAILED],
    )
    assert choices == [OrderStatus.CANCELLED, OrderStatus.CREATED, OrderStatus.FAILED]
    assert hint is None


def test_build_order_schema_uses_customer_status_label_for_paid_created() -> None:
    service = OrderService(MagicMock())
    order = MagicMock()
    order.id = 3606
    order.user_id = 1
    order.status = OrderStatus.CREATED
    order.availability_confirmation_status = AvailabilityConfirmationStatus.NOT_REQUIRED
    order.payment_paid_at = datetime(2026, 7, 17, 8, 52, 19)
    order.payment_due_at = None
    order.total_amount = Decimal("100")
    order.items_subtotal_amount = Decimal("100")
    order.discount_items_amount = Decimal("0")
    order.delivery_fee_amount = Decimal("0")
    order.eur_rate_snapshot = Decimal("100")
    order.notification_channels = []
    order.payment_meta_json = None
    order.payment_status = "IPS_ACCEPTED"
    order.payment_qr_id = None
    order.payment_qr_payload = None
    order.payment_provider = "sbp"
    order.payment_order_id = "test"
    order.cancellation_reason = None
    order.promo_code_applied = None
    order.last_name = None
    order.first_name = None
    order.street = None
    order.house = None
    order.apartment = None
    order.city = None
    order.postal_code = None
    order.phone = None
    order.notification_email = None
    order.supplier_order_id = None
    order.supplier_tracking_id = None
    order.failed_from_status = None
    order.created_at = None
    order.updated_at = None

    schema = service._build_order_schema(order, [])
    assert schema.status == OrderStatus.CREATED
    assert schema.status_label == "Оформляем у поставщика"
