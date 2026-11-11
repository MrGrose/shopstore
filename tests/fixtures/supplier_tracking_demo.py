from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

FULL_DHL_CARRIER_EVENTS: list[dict[str, Any]] = [
    {
        "key": "dhl-preparing",
        "at": "2026-07-05T08:00:00+00:00",
        "stage": "preparing",
        "title": "Поставщик готовит отправление",
        "description": "Instruction data for this shipment has been received",
        "source": "dhl",
    },
    {
        "key": "dhl-dispatched",
        "at": "2026-07-06T11:30:00+00:00",
        "stage": "dispatched",
        "title": "Передан перевозчику",
        "description": "The shipment has left the export parcel center",
        "source": "dhl",
    },
    {
        "key": "dhl-transit-export",
        "at": "2026-07-07T06:15:00+00:00",
        "stage": "in_transit",
        "title": "В пути",
        "description": "Transported to the destination country",
        "source": "dhl",
    },
    {
        "key": "dhl-destination",
        "at": "2026-07-07T18:40:00+00:00",
        "stage": "destination",
        "title": "Прибыл в страну назначения",
        "description": "The shipment arrived in the destination country",
        "source": "dhl",
    },
    {
        "key": "dhl-transit-import",
        "at": "2026-07-08T05:20:00+00:00",
        "stage": "in_transit",
        "title": "В пути",
        "description": "The shipment has left the import parcel center",
        "source": "dhl",
    },
    {
        "key": "dhl-last-mile",
        "at": "2026-07-08T12:00:00+00:00",
        "stage": "last_mile",
        "title": "Передан местной службе доставки",
        "description": "Prepared for delivery in the delivery depot",
        "source": "dhl",
    },
]

DELIVERED_DHL_EVENT: dict[str, Any] = {
    "key": "dhl-delivered",
    "at": "2026-07-08T16:45:00+00:00",
    "stage": "delivered",
    "title": "Доставлен",
    "description": "The shipment has been successfully delivered",
    "source": "dhl",
}


# Собирает supplier_tracking_json с полным DHL-таймлайном для локального превью.
def build_full_dhl_tracking_json(
    *,
    include_delivered: bool = False,
    purchased_at: str | None = None,
) -> dict[str, Any]:
    carrier_events = deepcopy(FULL_DHL_CARRIER_EVENTS)
    current_stage = "last_mile"
    if include_delivered:
        carrier_events.append(deepcopy(DELIVERED_DHL_EVENT))
        current_stage = "delivered"
    purchased_iso = purchased_at or datetime(2026, 7, 5, 9, 0, tzinfo=UTC).isoformat()
    return {
        "carrier_source": "dhl",
        "current_stage": current_stage,
        "carrier_label": "DHL",
        "store_events": [
            {
                "key": "store-purchased-demo",
                "at": purchased_iso,
                "stage": "purchased",
                "title": "Передан поставщику",
                "description": "Заказ оформлен у поставщика",
                "source": "store",
            }
        ],
        "supplier_events": [
            {
                "key": "pl-demo-dispatched",
                "at": "2026-07-06T11:30:00+00:00",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
                "raw_status": "InboundScan",
                "raw_text": "The goods have been sent.",
            },
            {
                "key": "pl-demo-transit",
                "at": "2026-07-07T06:15:00+00:00",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
                "raw_status": "InTransit",
                "raw_text": "In transit",
            },
        ],
        "carrier_events": carrier_events,
    }
