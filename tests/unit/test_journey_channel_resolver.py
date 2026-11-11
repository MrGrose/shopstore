from types import SimpleNamespace

from src.models.notification_outbox import NotificationOutboxStatus
from src.services.notifications.customer_notification_keys import (
    assembly_notify_key,
    availability_notify_key,
    finalize_notify_key,
    payment_late_received_key,
    payment_received_key,
)
from src.services.orders.journey_channel_resolver import (
    CustomerNotificationRecord,
    extract_customer_notifications,
    resolve_composition_tg_state,
    resolve_lk_state,
    resolve_stage_channels,
    resolve_tg_state,
)


def _order(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 1,
        "status": "created",
        "availability_confirmation_status": "confirmed",
        "payment_state": "not_started",
        "payment_paid_at": None,
        "supplier_order_id": None,
        "supplier_tracking_id": None,
        "notification_channels": ["telegram"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_lk_created_and_availability_pending() -> None:
    assert resolve_lk_state("created", _order()) == "sent"
    assert (
        resolve_lk_state(
            "availability",
            _order(availability_confirmation_status="pending", status="processing"),
        )
        == "sent"
    )


def test_lk_payment_and_delivery_with_tracking() -> None:
    assert (
        resolve_lk_state(
            "payment",
            _order(payment_paid_at="2026-07-01", payment_state="paid"),
        )
        == "sent"
    )
    assert (
        resolve_lk_state(
            "delivery",
            _order(status="delivery", supplier_tracking_id="CJ123"),
        )
        == "sent"
    )


def test_tg_payment_sent_by_template() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=payment_received_key(1),
            channel="telegram",
        )
    ]
    assert resolve_tg_state("payment", 1, notifications, {}) == "sent"


def test_tg_payment_sent_by_late_received_template() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="payment.late.received",
            idempotency_key=payment_late_received_key(1, 7),
            channel="telegram",
        )
    ]
    assert resolve_tg_state("payment", 1, notifications, {}) == "sent"


def test_tg_payment_not_sent_when_only_email_notified() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=f"{payment_received_key(1)}:email",
            channel="email",
        )
    ]
    assert resolve_tg_state("payment", 1, notifications, {}) == "waiting"


def test_tg_payment_sent_with_legacy_customer_channel() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=payment_received_key(1),
            channel="customer",
        )
    ]
    assert resolve_tg_state("payment", 1, notifications, {}) == "sent"


def test_resolve_stage_channels_dual_channel_payment_both_sent() -> None:
    order = _order(
        notification_channels=["telegram", "email"],
        payment_state="paid",
    )
    notifications = [
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=f"{payment_received_key(1)}:telegram",
            channel="customer",
        ),
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=f"{payment_received_key(1)}:email",
            channel="email",
        ),
    ]
    snapshot = resolve_stage_channels("payment", order, notifications, {})
    assert snapshot.tg == "sent"
    assert snapshot.email == "sent"
    assert snapshot.telegram_enabled is True
    assert snapshot.email_enabled is True


def test_email_payment_sent_with_channel_suffix_key() -> None:
    order = _order(notification_channels=["email"], payment_state="paid")
    notifications = [
        CustomerNotificationRecord(
            template="payment.received",
            idempotency_key=f"{payment_received_key(1)}:email",
            channel="email",
        )
    ]
    snapshot = resolve_stage_channels("payment", order, notifications, {})
    assert snapshot.email == "sent"
    assert snapshot.tg == "na"


def test_email_assembly_sent_with_channel_suffix_key() -> None:
    order = _order(
        notification_channels=["email"],
        status="assembling",
        supplier_order_id="TP-1",
    )
    notifications = [
        CustomerNotificationRecord(
            template="order_status",
            idempotency_key=f"{assembly_notify_key(1)}:email",
            channel="email",
        )
    ]
    snapshot = resolve_stage_channels("assembly", order, notifications, {})
    assert snapshot.email == "sent"


def test_email_created_stage_is_na_not_waiting() -> None:
    order = _order(notification_channels=["email"])
    snapshot = resolve_stage_channels("created", order, [], {})
    assert snapshot.email == "na"


def test_email_delivery_optional_without_notify_is_na() -> None:
    order = _order(
        notification_channels=["email"],
        status="delivery",
        supplier_tracking_id="CJ123",
    )
    snapshot = resolve_stage_channels("delivery", order, [], {})
    assert snapshot.email == "na"


def test_tg_payment_waiting_from_outbox() -> None:
    outbox = {
        payment_received_key(1): NotificationOutboxStatus.PENDING,
    }
    assert resolve_tg_state("payment", 1, [], outbox) == "waiting"


def test_tg_payment_waiting_from_outbox_telegram_suffix() -> None:
    outbox = {
        f"{payment_received_key(1)}:telegram": NotificationOutboxStatus.PENDING,
    }
    assert resolve_tg_state("payment", 1, [], outbox) == "waiting"


def test_tg_payment_error_from_outbox() -> None:
    outbox = {
        payment_received_key(1): NotificationOutboxStatus.FAILED,
    }
    assert resolve_tg_state("payment", 1, [], outbox) == "error"


def test_tg_availability_optional_na_without_notify() -> None:
    assert resolve_tg_state("availability", 1, [], {}) == "na"


def test_tg_availability_sent_with_key() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="order_status",
            idempotency_key=availability_notify_key(1),
        )
    ]
    assert resolve_tg_state("availability", 1, notifications, {}) == "sent"


def test_tg_assembly_sent_with_key() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="order_status",
            idempotency_key=assembly_notify_key(1),
        )
    ]
    assert resolve_tg_state("assembly", 1, notifications, {}) == "sent"


def test_tg_delivery_finalize_only_matching_key() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="order_status",
            idempotency_key=assembly_notify_key(1),
        )
    ]
    assert resolve_tg_state("delivery", 1, notifications, {}) == "na"
    finalize_notifications = [
        CustomerNotificationRecord(
            template="order_status",
            idempotency_key=finalize_notify_key(1),
        )
    ]
    assert resolve_tg_state("delivery", 1, finalize_notifications, {}) == "sent"


def test_extract_customer_notifications_reads_payload_template() -> None:
    rows = [
        {
            "event_type": "customer_notified",
            "payload_json": {
                "message": "Оплата получена",
                "template": "payment.received",
                "idempotency_key": payment_received_key(42),
            },
        }
    ]
    records = extract_customer_notifications(rows)
    assert len(records) == 1
    assert records[0].template == "payment.received"
    assert records[0].idempotency_key == payment_received_key(42)


def test_composition_tg_on_payment_stage() -> None:
    notifications = [
        CustomerNotificationRecord(
            template="composition.changed",
            idempotency_key=None,
        )
    ]
    assert resolve_composition_tg_state(notifications) == "sent"


def test_resolve_stage_channels_delivery_lk_without_completed() -> None:
    order = _order(status="delivery", supplier_tracking_id="CJ123")
    snapshot = resolve_stage_channels("delivery", order, [], {})
    assert snapshot.lk == "sent"
    assert snapshot.tg == "na"
