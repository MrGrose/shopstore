# Сценарий prod-заказа #40: dual-channel,
# legacy TG channel="customer" в customer_notified.
from src.services.notifications.customer_notification_keys import (
    assembly_notify_key,
    payment_received_key,
)

ORDER_40_ID = 40

ORDER_40_ORDER = {
    "id": ORDER_40_ID,
    "status": "assembling",
    "availability_confirmation_status": "confirmed",
    "payment_state": "paid",
    "supplier_order_id": "TP-40",
    "supplier_tracking_id": None,
    "notification_channels": ["telegram", "email"],
}

ORDER_40_CUSTOMER_NOTIFIED_EVENTS: list[dict[str, object]] = [
    {
        "event_type": "customer_notified",
        "payload_json": {
            "message": "Оплата получена",
            "template": "payment.received",
            "idempotency_key": f"{payment_received_key(ORDER_40_ID)}:email",
            "channel": "email",
        },
    },
    {
        "event_type": "customer_notified",
        "payload_json": {
            "message": "Оплата получена",
            "template": "payment.received",
            "idempotency_key": f"{payment_received_key(ORDER_40_ID)}:telegram",
            "channel": "customer",
        },
    },
    {
        "event_type": "customer_notified",
        "payload_json": {
            "message": "Заказ передан в сборку",
            "template": "order_status",
            "idempotency_key": f"{assembly_notify_key(ORDER_40_ID)}:email",
            "channel": "email",
        },
    },
    {
        "event_type": "customer_notified",
        "payload_json": {
            "message": "Заказ передан в сборку",
            "template": "order_status",
            "idempotency_key": f"{assembly_notify_key(ORDER_40_ID)}:telegram",
            "channel": "customer",
        },
    },
    {"event_type": "assembly_started"},
    {"event_type": "payment_accepted"},
    {"event_type": "order_created"},
]
