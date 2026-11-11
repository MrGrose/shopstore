from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.orders.supplier_tracking_shape import has_terminal_delivered_signal

PARCELLAB_CYCLE_STAGES: tuple[str, ...] = (
    "preparing",
    "dispatched",
    "in_transit",
    "destination",
    "last_mile",
    "delivered",
)

_STAGE_RAW: dict[str, tuple[str, str]] = {
    "preparing": ("OrderProcessed", "The order is being prepared by the supplier"),
    "dispatched": ("InboundScan", "The goods have been sent."),
    "in_transit": ("InTransit", "The shipment is on its way"),
    "destination": ("Import", "The shipment arrived in the destination country"),
    "last_mile": ("OutForDelivery", "The shipment is out for delivery"),
    "delivered": ("Delivered", "The shipment has been successfully delivered"),
}

DEFAULT_CYCLE_TRACKING_NUMBER = "CJ-DEMO-CYCLE-DE"
DEFAULT_CYCLE_HEADER_ID = "tracking-cycle-demo"


def build_parcellab_payload_through(
    stage: str,
    *,
    tracking_number: str = DEFAULT_CYCLE_TRACKING_NUMBER,
    header_id: str = DEFAULT_CYCLE_HEADER_ID,
    anchor: datetime | None = None,
) -> dict[str, Any]:
    if stage not in _STAGE_RAW:
        known = ", ".join(PARCELLAB_CYCLE_STAGES)
        raise ValueError(f"Unknown stage {stage!r}; expected one of: {known}")
    end_index = PARCELLAB_CYCLE_STAGES.index(stage)
    base = anchor or datetime(2026, 7, 11, 10, 0, 0, tzinfo=UTC)
    events: list[dict[str, Any]] = []
    for index in range(end_index + 1):
        step = PARCELLAB_CYCLE_STAGES[index]
        status_code, details = _STAGE_RAW[step]
        at = (base + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M:%SZ")
        events.append(
            {
                "shown": True,
                "id": f"event-{step}",
                "timestamp": at,
                "status": status_code,
                "status_details": details,
            }
        )
    header_last = "Delivered" if stage == "delivered" else events[-1]["status"]
    return {
        "header": [
            {
                "id": header_id,
                "tracking_number": tracking_number,
                "courier": {
                    "name": "dhl-germany",
                    "prettyname": "DHL",
                    "trackingurl": f"https://example.test/track/{tracking_number}",
                    "destination_courier": {"prettyname": "Russian Post"},
                },
                "last_delivery_status": {"code": header_last},
            }
        ],
        "body": {header_id: events},
    }


def applied_parcellab_stages(tracking_json: Mapping[str, object] | None) -> list[str]:
    data = dict(tracking_json or {})
    keys = {
        str(event.get("key") or "")
        for event in data.get("supplier_events") or []
        if isinstance(event, Mapping)
    }
    return [stage for stage in PARCELLAB_CYCLE_STAGES if f"pl-event-{stage}" in keys]


def next_parcellab_stage(tracking_json: Mapping[str, object] | None) -> str | None:
    applied = applied_parcellab_stages(tracking_json)
    for stage in PARCELLAB_CYCLE_STAGES:
        if stage not in applied:
            return stage
    return None


def _count_events(events: Sequence[object], event_type: str) -> int:
    return sum(
        1
        for row in events
        if isinstance(row, Mapping) and str(row.get("event_type") or "") == event_type
    )


def verify_order_cycle(
    order: object,
    event_rows: Sequence[Mapping[str, object]],
) -> list[str]:
    errors: list[str] = []
    status = str(getattr(order, "status", "") or "").lower()
    availability = str(
        getattr(order, "availability_confirmation_status", "")
        or AvailabilityConfirmationStatus.NOT_REQUIRED
    ).lower()
    tracking_json = getattr(order, "supplier_tracking_json", None)
    paid_at = getattr(order, "payment_paid_at", None)

    if availability == AvailabilityConfirmationStatus.PENDING:
        errors.append(
            "availability_confirmation_status=pending — подтверди или отклони",
        )

    if status == OrderStatus.COMPLETED:
        if _count_events(event_rows, "delivered_to_customer") != 1:
            errors.append("ожидается ровно одно событие delivered_to_customer")
        return errors

    if paid_at is None and status not in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        errors.append("заказ не оплачен — make order-paid")

    if status in {OrderStatus.ASSEMBLING, OrderStatus.DELIVERY}:
        if not getattr(order, "supplier_order_id", None):
            errors.append("нет supplier_order_id — make order-start-assembling")
        if _count_events(event_rows, "assembly_started") != 1:
            errors.append("ожидается одно событие assembly_started")

    if status == OrderStatus.DELIVERY:
        if _count_events(event_rows, "delivery_started") != 1:
            errors.append("ожидается одно событие delivery_started")
        tracking_map = (
            dict(tracking_json) if isinstance(tracking_json, Mapping) else None
        )
        if has_terminal_delivered_signal(tracking_map):
            return errors
        missing = next_parcellab_stage(tracking_map)
        if missing:
            errors.append(
                f"ParcelLab stage не доведён до delivered (следующий: {missing})"
            )

    if status == OrderStatus.ASSEMBLING:
        missing = next_parcellab_stage(
            dict(tracking_json) if isinstance(tracking_json, Mapping) else None
        )
        if missing:
            errors.append(
                f"заказ в assembling — примени tracking-parcellab-stage STAGE={missing}"
            )

    return errors
