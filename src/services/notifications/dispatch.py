from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class NotificationChannel(StrEnum):
    ADMIN_ORDERS = "admin_orders"
    CUSTOMER = "customer"
    SUPPORT_GROUP = "support_group"
    SUPPORT_CUSTOMER = "support_customer"
    EMAIL = "email"


CUSTOMER_PAYMENT_AWAITING_EVENT = "customer_payment_awaiting_notified"
CUSTOMER_PAYMENT_FAILED_EVENT = "customer_payment_failed_notified"


@dataclass(frozen=True)
class NotificationOrderEvent:
    event_type: str
    event_message: str
    payload_json: dict[str, object] | None = None


@dataclass(frozen=True)
class NotificationDispatch:
    channel: NotificationChannel
    template: str
    payload: dict[str, object] = field(default_factory=dict)
    created_by: str = "system"
    idempotency_key: str | None = None
    skip_if_order_event: str | None = None
    record_order_event: NotificationOrderEvent | None = None


# Сериализует dispatch для очереди (RQ/RabbitMQ позже).
def notification_dispatch_to_dict(dispatch: NotificationDispatch) -> dict[str, Any]:
    data = asdict(dispatch)
    data["channel"] = dispatch.channel.value
    return data


# Восстанавливает dispatch из JSON очереди.
def notification_dispatch_from_dict(data: dict[str, Any]) -> NotificationDispatch:
    record_raw = data.get("record_order_event")
    record: NotificationOrderEvent | None = None
    if isinstance(record_raw, dict):
        record = NotificationOrderEvent(
            event_type=str(record_raw.get("event_type") or ""),
            event_message=str(record_raw.get("event_message") or ""),
            payload_json=(
                record_raw.get("payload_json")
                if isinstance(record_raw.get("payload_json"), dict)
                else None
            ),
        )
    payload_raw = data.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    channel_raw = str(data.get("channel") or NotificationChannel.CUSTOMER.value)
    return NotificationDispatch(
        channel=NotificationChannel(channel_raw),
        template=str(data.get("template") or ""),
        payload=payload,
        created_by=str(data.get("created_by") or "system"),
        idempotency_key=(
            str(data["idempotency_key"]) if data.get("idempotency_key") else None
        ),
        skip_if_order_event=(
            str(data["skip_if_order_event"])
            if data.get("skip_if_order_event")
            else None
        ),
        record_order_event=record,
    )
