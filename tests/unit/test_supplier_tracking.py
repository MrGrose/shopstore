from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.schemas.order import SupplierTrackingPublicSchema
from src.services.orders import parcellab_tracking
from src.services.orders.dhl_tracking import (
    normalize_dhl_payload,
    translate_dhl_status_text,
)
from src.services.orders.parcellab_tracking import (
    build_parcellab_admin_snapshot,
    discover_from_parcellab_payload,
    normalize_parcellab_body,
)
from src.services.orders.supplier_tracking import (
    SupplierTrackingService,
    _collapse_consecutive_stages,
    _compute_current_stage,
    _event_sort_key,
    _merge_carrier_events,
    _merge_supplier_events,
    _sort_tracking_events,
    _supplier_events_stale,
    build_customer_store_journey_events,
    build_order_timeline,
    carrier_timeline_for_journey,
    initialize_supplier_tracking,
    project_tracking_event_for_display,
    supplier_timeline_for_journey,
)
from src.services.orders.supplier_tracking_shape import ensure_supplier_tracking_shape


def _parcellab_payload() -> dict:
    return {
        "header": [
            {
                "id": "tracking-1",
                "tracking_number": "CJ687378245DE",
                "courier": {
                    "name": "dhl-germany",
                    "prettyname": "DHL",
                    "trackingurl": "https://example.test/track/CJ687378245DE",
                    "destination_courier": {"prettyname": "Russian Post"},
                },
                "last_delivery_status": {"code": "InTransit"},
            }
        ],
        "body": {
            "tracking-1": [
                {
                    "shown": True,
                    "id": "event-1",
                    "timestamp": "2026-07-07T17:17:59Z",
                    "status": "InboundScan",
                    "status_details": "The goods have been sent.",
                }
            ]
        },
    }


def _dhl_payload_delivered() -> dict:
    return {
        "sendungen": [
            {
                "sendungsdetails": {
                    "sendungsnummern": {"sendungsnummer": "CJ686803119DE"},
                    "sendungsverlauf": {
                        "status": "The shipment has been successfully delivered",
                        "events": [
                            {
                                "datum": "2026-06-10T08:12:00+02:00",
                                "status": (
                                    "The instruction data for this shipment have been "
                                    "provided by the sender to DHL"
                                ),
                                "ort": "Germany",
                            },
                            {
                                "datum": "2026-06-18T14:22:00+02:00",
                                "status": (
                                    "The shipment has been successfully delivered"
                                ),
                                "ort": "Russian Federation",
                            },
                        ],
                    },
                }
            }
        ]
    }


def test_normalize_parcellab_body_maps_stages() -> None:
    normalized = normalize_parcellab_body(_parcellab_payload())
    assert normalized["tracking_number"] == "CJ687378245DE"
    assert len(normalized["events"]) == 1
    assert normalized["events"][0]["stage"] == "dispatched"
    assert normalized["events"][0]["title"] == "Передан перевозчику"
    assert normalized["events"][0]["source"] == "parcellab"


def test_build_parcellab_admin_snapshot_keeps_body_for_admin() -> None:
    fetched_at = "2026-07-08T10:00:00+00:00"
    snapshot = build_parcellab_admin_snapshot(_parcellab_payload(), fetched_at)
    assert snapshot["fetched_at"] == fetched_at
    assert snapshot["tracking_number"] == "CJ687378245DE"
    assert len(snapshot["events"]) == 1
    assert snapshot["events"][0]["status"] == "InboundScan"
    assert snapshot["events"][0]["stage"] == "dispatched"


def test_merge_supplier_events_replaces_snapshot() -> None:
    incoming = normalize_parcellab_body(_parcellab_payload())
    merged, changed = _merge_supplier_events({"supplier_events": []}, incoming)
    assert changed is True
    assert len(merged["supplier_events"]) == 1
    second, changed_again = _merge_supplier_events(merged, incoming)
    assert changed_again is False
    assert len(second["supplier_events"]) == 1


def test_build_order_timeline_lk_uses_supplier_not_dhl() -> None:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-07T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported to the destination country",
                "location": "Germany",
                "source": "dhl",
            }
        ],
        "carrier_label": "DHL",
    }
    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 7, 12, 0, 0),
        now=datetime(2026, 7, 7, 13, 0, 0),
    )
    shipment_titles = [
        item["title"] for item in timeline["events"] if item["stage"] == "in_transit"
    ]
    assert shipment_titles == ["В пути"]
    assert timeline["use_carrier_fallback"] is False
    assert all("location" not in item for item in timeline["events"])
    assert all(
        "Germany" not in str(item.get("description") or "")
        for item in timeline["events"]
    )
    assert timeline["current_status"] == "В пути"


def test_build_order_timeline_lk_falls_back_to_dhl() -> None:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "supplier_events": [],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-07T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported to the destination country",
                "location": "Germany",
                "source": "dhl",
            }
        ],
    }
    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=None,
        now=datetime(2026, 7, 7, 13, 0, 0),
    )
    assert timeline["use_carrier_fallback"] is True
    assert any(item["stage"] == "in_transit" for item in timeline["events"])
    assert all("location" not in item for item in timeline["events"])
    assert all(
        "Germany" not in str(item.get("description") or "")
        for item in timeline["events"]
    )


def test_build_order_timeline_lk_carrier_fallback_first_event_matches_current_stage() -> (  # noqa: E501
    None
):
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "supplier_events": [],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-08T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported to the destination country",
                "location": "Germany",
                "source": "dhl",
            }
        ],
    }

    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=None,
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    assert timeline["use_carrier_fallback"] is True
    assert timeline["current_stage"] == "in_transit"
    assert timeline["events"][0]["stage"] == "in_transit"
    assert timeline["current_stage"] == timeline["events"][0]["stage"]


def test_build_order_timeline_lk_completed_promoted_over_newer_milestone() -> None:
    from src.models.order import OrderStatus

    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 5, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = OrderStatus.COMPLETED

    delivery_started_event = MagicMock()
    delivery_started_event.event_type = "delivery_started"
    delivery_started_event.created_at = datetime(2026, 7, 10, 12, 0, 0)
    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-08T10:00:00Z",
                "stage": "delivered",
                "title": "Доставлен",
                "source": "parcellab",
            }
        ],
    }

    timeline = build_order_timeline(
        order,
        [delivery_started_event],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0),
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    assert timeline["current_stage"] == "completed"
    assert timeline["events"][0]["stage"] == "completed"
    assert timeline["events"][1]["stage"] == "delivery_started"
    assert timeline["events"][0]["at"] < timeline["events"][1]["at"]


def test_build_order_timeline_lk_nonconsecutive_in_transit_collapse_and_promote() -> (
    None
):
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "supplier_events": [
            {
                "key": "pl-dispatched",
                "at": "2026-07-09T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "manual-in-transit-old",
                "at": "2026-07-08T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            },
            {
                "key": "manual-in-transit-new",
                "at": "2026-07-10T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            },
        ],
    }

    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0),
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    in_transit_events = [
        item for item in timeline["events"] if item["stage"] == "in_transit"
    ]
    assert len(in_transit_events) == 2
    assert timeline["current_stage"] == "in_transit"
    assert timeline["events"][0]["stage"] == "in_transit"
    assert timeline["events"][0]["key"] == "manual-in-transit-new"


def test_build_order_timeline_admin_has_both_sources() -> None:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
                "raw_text": "In transit",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-07T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported",
                "location": "Germany",
                "source": "dhl",
            }
        ],
    }
    timeline = build_order_timeline(order, [], tracking, "admin")
    assert len(timeline["supplier_timeline"]) == 1
    assert len(timeline["carrier_timeline"]) == 1
    assert timeline["supplier_timeline"][0]["source"] == "parcellab"
    assert timeline["carrier_timeline"][0]["source"] == "dhl"


def test_supplier_timeline_for_journey() -> None:
    timeline = supplier_timeline_for_journey(
        {
            "supplier_events": [
                {
                    "key": "pl-1",
                    "at": "2026-07-07T10:00:00Z",
                    "stage": "in_transit",
                    "title": "В пути",
                    "source": "parcellab",
                    "raw_text": "Moving",
                }
            ]
        },
        "TP-1",
    )
    assert timeline[0]["title"] == "В пути"
    assert timeline[0]["source"] == "parcellab"


def test_carrier_timeline_for_journey_newest_first() -> None:
    timeline = carrier_timeline_for_journey(
        {
            "carrier_events": [
                {
                    "key": "1",
                    "at": "2026-07-07T10:00:00Z",
                    "stage": "dispatched",
                    "title": "Передан перевозчику",
                    "source": "dhl",
                    "location": "Germany",
                    "description": "The international shipment has been processed",
                },
                {
                    "key": "2",
                    "at": "2026-07-08T10:00:00Z",
                    "stage": "in_transit",
                    "title": "В пути",
                    "source": "dhl",
                    "location": "Germany",
                    "description": "Transported to the destination country",
                },
            ]
        },
        "CJ123DE",
    )
    assert [item["title"] for item in timeline] == ["В пути", "Передан перевозчику"]
    assert timeline[0]["source"] == "dhl"
    assert "Германия" in (timeline[0]["description"] or "")
    assert timeline[0]["at_display"] == "08.07, 13:00"
    assert timeline[1]["at_display"] == "07.07, 13:00"
    assert carrier_timeline_for_journey({}, None) == []


def test_discover_parcellab_returns_tracking_without_body_events() -> None:
    result = discover_from_parcellab_payload(_parcellab_payload())
    assert result is not None
    assert result.tracking_number == "CJ687378245DE"
    assert result.carrier_label == "DHL / Russian Post"
    assert result.carrier_url == "https://example.test/track/CJ687378245DE"


def test_normalize_dhl_payload_maps_stages() -> None:
    result = normalize_dhl_payload(_dhl_payload_delivered(), "CJ686803119DE")
    assert result["tracking_number"] == "CJ686803119DE"
    assert result["carrier_source"] == "dhl"
    assert result["current_stage"] == "delivered"
    assert len(result["events"]) == 2
    assert result["events"][0]["stage"] == "preparing"
    assert result["events"][-1]["stage"] == "delivered"
    assert result["events"][-1]["source"] == "dhl"


def test_normalize_dhl_payload_prefers_newer_event_over_stale_headline() -> None:
    payload = {
        "sendungen": [
            {
                "sendungsdetails": {
                    "sendungsnummern": {"sendungsnummer": "CJ687378245DE"},
                    "sendungsverlauf": {
                        "status": "Export parcel center.",
                        "events": [
                            {
                                "datum": "2026-07-06T09:01:27+00:00",
                                "status": (
                                    "The instruction data for this shipment have been "
                                    "provided by the sender to DHL electronically"
                                ),
                                "ort": None,
                            },
                            {
                                "datum": "2026-07-08T01:02:42+00:00",
                                "status": (
                                    "The shipment will be transported to the "
                                    "destination country/destination area and, from "
                                    "there, handed over to the delivery organization."
                                ),
                                "ort": "Germany",
                            },
                        ],
                    },
                }
            }
        ]
    }
    result = normalize_dhl_payload(payload, "CJ687378245DE")
    assert result["current_stage"] == "in_transit"


def test_project_tracking_event_for_display_translates_dhl_text() -> None:
    projected = project_tracking_event_for_display(
        {
            "key": "dhl-1",
            "at": "2026-07-08T01:02:42+00:00",
            "stage": "in_transit",
            "title": "В пути",
            "description": (
                "The shipment will be transported to the destination country"
            ),
            "location": "Germany",
            "source": "dhl",
        }
    )
    assert projected["title"] == "В пути"
    assert projected["description"] == (
        "Отправление следует в страну назначения "
        "и будет передано местной службе доставки"
    )
    assert projected["location"] == "Германия"


def test_translate_dhl_status_text_keeps_cyrillic() -> None:
    assert (
        translate_dhl_status_text("Отправление уже в пути", "in_transit")
        == "Отправление уже в пути"
    )


def test_translate_dhl_status_text_uses_machine_translate_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.services.orders.dhl_tracking.translate_plain_text_to_ru",
        lambda text, source="en": "Новый неизвестный статус DHL",
    )
    result = translate_dhl_status_text(
        "Brand new DHL phrase we never saw before",
        "in_transit",
        use_machine_translate=True,
    )
    assert result == "Новый неизвестный статус DHL"


def test_project_lk_timeline_event_omits_store_descriptions() -> None:
    from src.services.orders.supplier_tracking import _project_lk_timeline_event

    projected = _project_lk_timeline_event(
        {
            "key": "store-1",
            "at": "2026-07-09T11:11:28+00:00",
            "stage": "assembling",
            "title": "В сборке",
            "description": "Заказ оформлен у поставщика",
            "source": "store",
        }
    )
    assert projected["description"] is None
    assert projected["title"] == "В сборке"


def test_project_tracking_event_for_display_keeps_store_text() -> None:
    projected = project_tracking_event_for_display(
        {
            "key": "store-1",
            "at": "2026-07-09T11:11:28+00:00",
            "stage": "assembling",
            "title": "В сборке",
            "description": "Заказ оформлен у поставщика",
            "source": "store",
        }
    )
    assert projected["description"] == "Заказ оформлен у поставщика"


def test_build_customer_store_journey_events_full_path() -> None:
    from datetime import datetime
    from unittest.mock import MagicMock

    order = MagicMock()
    order.id = 1485
    order.created_at = datetime(2026, 7, 9, 11, 0, 0)
    order.updated_at = datetime(2026, 7, 9, 12, 0, 0)
    order.availability_confirmation_status = "confirmed"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 9, 11, 10, 0)
    order.supplier_order_id = "TP-2712965"
    order.supplier_tracking_id = "CJ687378245DE"
    order.status = "delivery"

    class Event:
        def __init__(self, event_type: str, created_at: datetime) -> None:
            self.event_type = event_type
            self.created_at = created_at

    events = [
        Event("order_created", datetime(2026, 7, 9, 11, 0, 0)),
        Event("availability_confirmed", datetime(2026, 7, 9, 11, 5, 0)),
        Event("payment_accepted", datetime(2026, 7, 9, 11, 10, 0)),
        Event("assembly_started", datetime(2026, 7, 9, 11, 11, 0)),
        Event("delivery_started", datetime(2026, 7, 9, 11, 20, 0)),
    ]
    milestones = build_customer_store_journey_events(order, events)
    assert [item["stage"] for item in milestones] == [
        "created",
        "availability",
        "paid",
        "assembling",
        "delivery_started",
    ]
    assert milestones[0]["title"] == "Заказ оформлен"
    assert milestones[3]["title"] == "В сборке"
    assert "description" not in milestones[3]
    assert milestones[4]["title"] == "Передан в доставку"


def test_merge_carrier_events_deduplicates() -> None:
    incoming = normalize_dhl_payload(_dhl_payload_delivered(), "CJ686803119DE")
    first, changed = _merge_carrier_events({"store_events": []}, incoming)
    second, changed_again = _merge_carrier_events(first, incoming)
    assert changed is True
    assert changed_again is False
    assert len(second["carrier_events"]) == 2


def test_ensure_tracking_shape_splits_legacy_events() -> None:
    legacy = {
        "events": [
            {
                "key": "1",
                "stage": "purchased",
                "source": "manual",
                "at": "2026-07-01T00:00:00Z",
            },
            {
                "key": "2",
                "stage": "in_transit",
                "source": "auto",
                "at": "2026-07-02T00:00:00Z",
            },
            {
                "key": "3",
                "stage": "in_transit",
                "source": "dhl",
                "at": "2026-07-03T00:00:00Z",
            },
        ]
    }
    shaped = ensure_supplier_tracking_shape(legacy)
    assert len(shaped["store_events"]) == 1
    assert len(shaped["supplier_events"]) == 1
    assert len(shaped["carrier_events"]) == 1
    assert shaped["carrier_events"][0]["source"] == "dhl"


def test_sort_tracking_events_uses_datetime_first() -> None:
    events = _sort_tracking_events(
        [
            {
                "key": "destination",
                "at": "2026-07-08T00:46:59.000Z",
                "stage": "destination",
                "title": "Прибыл в страну назначения",
            },
            {
                "key": "in-transit",
                "at": "2026-07-08T01:02:42.000Z",
                "stage": "in_transit",
                "title": "В пути",
            },
            {
                "key": "paid",
                "at": "2026-07-08T09:05:13.919379+00:00",
                "stage": "paid",
                "title": "Заказ оплачен",
            },
        ]
    )
    assert [item["stage"] for item in events] == [
        "destination",
        "in_transit",
        "paid",
    ]


def test_initialize_supplier_tracking_is_idempotent() -> None:
    order = MagicMock()
    order.supplier_tracking_json = None
    now = datetime(2026, 7, 7, 12, 0, 0)
    initialize_supplier_tracking(order, now)
    initialize_supplier_tracking(order, now)
    assert order.supplier_tracking_sync_state == "waiting"
    assert order.supplier_tracking_next_check_at == now
    assert len(order.supplier_tracking_json["store_events"]) == 1


@pytest.mark.asyncio
async def test_parser_marks_captcha_as_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 403
        text = "captcha challenge"

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(parcellab_tracking, "AsyncStealthSession", Session)
    with pytest.raises(parcellab_tracking.SupplierTrackingFetchError) as err:
        await parcellab_tracking.fetch_supplier_tracking("TP-1")
    assert err.value.code == "blocked"
    assert err.value.is_blocked is True


def test_event_sort_key_unknown_stage_gets_middle_rank() -> None:
    known = {
        "at": "2026-07-07T10:00:00Z",
        "stage": "preparing",
    }
    unknown = {
        "at": "2026-07-07T10:00:00Z",
        "stage": "brand_new_stage",
    }
    events = sorted([known, unknown], key=_event_sort_key)
    # unknown не тонет в начало (rank 50 > preparing rank 30),
    # но при равном at известный ранг «preparing» ниже, поэтому unknown идёт позже.
    assert events[0]["stage"] == "preparing"
    assert events[1]["stage"] == "brand_new_stage"


def _lk_order_for_public_tracking() -> MagicMock:
    order = MagicMock()
    order.id = 1
    order.user_id = 42
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    order.supplier_tracking_updated_at = datetime(2026, 7, 7, 12, 0, 0)
    order.supplier_tracking_json = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-07T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported to the destination country",
                "description_raw": "Transported to the destination country",
                "location": "Germany",
                "source": "dhl",
            }
        ],
        "carrier_label": "DHL",
    }
    return order


@pytest.mark.asyncio
async def test_public_tracking_omits_carrier_raw_fields() -> None:
    order = _lk_order_for_public_tracking()
    session = MagicMock()
    session.get = AsyncMock(return_value=order)
    session.scalars = AsyncMock(
        return_value=MagicMock(list=lambda: [])  # type: ignore[call-arg]
    )

    result = await SupplierTrackingService(session).public_tracking(
        order_id=1, user_id=42, now=datetime(2026, 7, 7, 13, 0, 0)
    )

    assert isinstance(result, SupplierTrackingPublicSchema)
    assert result.available is True
    assert result.current_stage == "in_transit"
    for event in result.events:
        assert "location" not in event.model_dump()
        assert "description_raw" not in event.model_dump()
        assert event.description is None
        assert "source" not in event.model_dump()


def test_supplier_events_stale_when_updated_at_is_none() -> None:
    events = [
        {
            "key": "pl-1",
            "at": "2026-07-07T10:00:00Z",
            "stage": "in_transit",
            "title": "В пути",
            "source": "parcellab",
        }
    ]
    assert _supplier_events_stale(events, None) is True


def test_collapse_consecutive_stages_keeps_latest() -> None:
    events = [
        {
            "key": "pl-1",
            "at": "2026-07-07T10:00:00Z",
            "stage": "in_transit",
            "title": "В пути",
            "source": "parcellab",
        },
        {
            "key": "dhl-1",
            "at": "2026-07-07T11:00:00Z",
            "stage": "in_transit",
            "title": "В пути",
            "source": "dhl",
        },
    ]
    collapsed = _collapse_consecutive_stages(events)
    assert len(collapsed) == 1
    assert collapsed[0]["key"] == "dhl-1"


@pytest.mark.asyncio
async def test_compare_parcellab_updates_supplier_events_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.models.order import OrderStatus
    from src.services.orders import supplier_tracking as st_module

    order = MagicMock()
    order.id = 5
    order.user_id = 7
    order.supplier_order_id = "TP-2712965"
    order.supplier_tracking_id = None
    order.status = OrderStatus.ASSEMBLING
    order.supplier_tracking_json = None

    payload = {
        "header": [
            {
                "id": "tp-2712965",
                "tracking_number": "CJ687378245DE",
                "courier": {
                    "name": "dhl-germany",
                    "prettyname": "DHL",
                    "trackingurl": "https://example.test/track/CJ687378245DE",
                    "destination_courier": {"prettyname": "Russian Post"},
                    "last_delivery_status": {"code": "InTransit"},
                },
            }
        ],
        "body": {
            "tp-2712965": [
                {
                    "shown": True,
                    "id": "evt-1",
                    "timestamp": "2026-07-07T17:17:59Z",
                    "status": "InboundScan",
                    "status_details": "The goods have been sent.",
                }
            ]
        },
    }

    async def _fake_fetch(supplier_order_id: str) -> dict | None:
        assert supplier_order_id == "TP-2712965"
        return payload

    monkeypatch.setattr(st_module, "fetch_supplier_tracking", _fake_fetch)
    monkeypatch.setattr(
        st_module,
        "sync_delivered_alert_after_tracking_check",
        AsyncMock(),
    )

    session = MagicMock()
    session.get = AsyncMock(return_value=order)
    session.commit = AsyncMock(return_value=None)

    result = await SupplierTrackingService(session).compare_parcellab(order_id=5)

    stored = order.supplier_tracking_json
    assert stored is not None
    assert "supplier_events" in stored
    assert len(stored["supplier_events"]) == 1
    assert stored["supplier_events"][0]["stage"] == "dispatched"
    assert "parcellab_snapshot" not in stored
    assert stored.get("tracking_number") == "CJ687378245DE"
    assert order.supplier_tracking_id == "CJ687378245DE"
    assert order.supplier_tracking_sync_state == "active"
    assert result["tracking_number"] == "CJ687378245DE"
    assert len(result["events"]) == 1


def test_store_timeline_for_journey() -> None:
    from src.services.orders.supplier_tracking import store_timeline_for_journey

    timeline = store_timeline_for_journey(
        {
            "store_events": [
                {
                    "key": "store-1",
                    "at": "2026-07-07T10:00:00Z",
                    "stage": "purchased",
                    "title": "Передан поставщику",
                    "description": "Заказ оформлен у поставщика",
                    "source": "manual",
                },
                {
                    "key": "store-2",
                    "at": "2026-07-08T11:00:00Z",
                    "stage": "assembling",
                    "title": "В сборке",
                    "description": "Ручной этап",
                    "source": "manual",
                },
            ]
        },
    )
    assert len(timeline) == 2
    assert timeline[0]["title"] == "В сборке"
    assert timeline[1]["title"] == "Передан поставщику"
    assert timeline[0]["source"] == "manual"
    # description = raw_text for non-DHL events
    assert timeline[0]["description"] == "Ручной этап"
    assert "Ручной этап" in (timeline[0]["raw_text"] or "")


def test_store_timeline_for_journey_filters_only_manual() -> None:
    from src.services.orders.supplier_tracking import store_timeline_for_journey

    # store_events содержит как manual, так и автоматические (source="store")
    timeline = store_timeline_for_journey(
        {
            "store_events": [
                # Ручное событие - должно попасть в результат
                {
                    "key": "store-manual-1",
                    "at": "2026-07-08T10:00:00Z",
                    "stage": "assembling",
                    "title": "В сборке",
                    "description": "Ручной этап",
                    "source": "manual",
                },
                # Автоматическое событие - НЕ должно попасть в "Ручные этапы"
                {
                    "key": "store-auto-1",
                    "at": "2026-07-07T11:00:00Z",
                    "stage": "purchased",
                    "title": "Передан поставщику",
                    "description": "Автоматический этап",
                    "source": "store",
                },
                # Другое автоматическое событие - тоже НЕ должно попасть
                {
                    "key": "store-auto-2",
                    "at": "2026-07-07T12:00:00Z",
                    "stage": "paid",
                    "title": "Заказ оплачен",
                    "description": "Автоматический этап",
                    "source": "auto",
                },
            ]
        },
    )
    # Только ручное событие должно быть в результате
    assert len(timeline) == 1
    assert timeline[0]["title"] == "В сборке"
    assert timeline[0]["source"] == "manual"


def test_build_order_timeline_lk_includes_store_events() -> None:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "assembling",
                "title": "В сборке",
                "description": "Заказ оформлен у поставщика",
                "source": "manual",
            }
        ],
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
    }
    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 9, 12, 0, 0),
        now=datetime(2026, 7, 9, 13, 0, 0),
    )
    stages = [item["stage"] for item in timeline["events"]]
    # store_events включаются в lk timeline
    assert "assembling" in stages
    assert "in_transit" in stages
    # manual event не содержит description/source/raw
    # store_events имеют stage='assembling' (как и order_milestones)
    # найти store_event по ключу
    store_event = next(
        (e for e in timeline["events"] if e.get("key") == "store-1"), None
    )
    assert store_event is not None, "store event should be in timeline"
    assert store_event["description"] is None
    assert "source" not in store_event
    assert "raw_text" not in store_event
    assert "description_raw" not in store_event
    assert "location" not in store_event


def test_build_order_timeline_admin_includes_store_events() -> None:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    tracking = {
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "assembling",
                "title": "В сборке",
                "description": "Заказ оформлен у поставщика",
                "source": "manual",
            }
        ],
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-07T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "description": "Transported",
                "location": "Germany",
                "source": "dhl",
            }
        ],
    }
    timeline = build_order_timeline(order, [], tracking, "admin")
    # all three types included in admin events (store + supplier + carrier)
    # order_milestones добавляются дополнительно
    store_events_in_timeline = [
        e for e in timeline["events"] if e.get("source") == "manual"
    ]
    assert len(store_events_in_timeline) >= 1
    # admin timeline includes store_events
    store_titles = [e["title"] for e in store_events_in_timeline]
    assert "В сборке" in store_titles


def test_current_stage_uses_store_events_and_matches_timeline() -> None:
    # supplier dispatched 09.07, manual in_transit 10.07 → current in_transit
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "confirmed"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    order.supplier_tracking_updated_at = datetime(2026, 7, 10, 13, 0, 0)

    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
    }

    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0),
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    # current_stage should match the newest event
    assert timeline["current_stage"] == "in_transit"
    assert timeline["current_status"] == "В пути"
    # First event in timeline should be the newest (in_transit)
    assert timeline["events"][0]["stage"] == "in_transit"
    assert timeline["events"][0]["title"] == "В пути"
    # store event does not expose description/source to client
    assert timeline["events"][0]["description"] is None
    assert "source" not in timeline["events"][0]


def test_current_stage_prefers_newest_supplier_event_over_manual() -> None:
    # supplier in_transit 10.07 новее manual dispatched 09.07
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "confirmed"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    order.supplier_tracking_updated_at = datetime(2026, 7, 10, 13, 0, 0)

    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "manual",
            }
        ],
    }

    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0),
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    # current_stage should match the newest event (supplier in_transit)
    assert timeline["current_stage"] == "in_transit"
    assert timeline["current_status"] == "В пути"
    # First event in timeline should be the newest (supplier in_transit)
    assert timeline["events"][0]["stage"] == "in_transit"
    assert timeline["events"][0]["title"] == "В пути"
    # source not exposed to client in lk mode
    assert "source" not in timeline["events"][0]


def test_current_stage_matches_first_timeline_event() -> None:
    # Regression test: current_stage должен совпадать с самым новым событием в timeline
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "confirmed"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    order.supplier_tracking_updated_at = datetime(2026, 7, 10, 13, 0, 0)

    # Сценарий 1: supplier event старее, manual event новее
    tracking1 = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
    }
    timeline1 = build_order_timeline(
        order, [], tracking1, "lk", tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0)
    )
    # Проверяем инвариант: current_stage == stage первого события (самого нового)
    assert timeline1["events"]
    assert timeline1["current_stage"] == timeline1["events"][0]["stage"]

    # Сценарий 2: manual event старее, supplier event новее
    tracking2 = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "manual",
            }
        ],
    }
    timeline2 = build_order_timeline(
        order, [], tracking2, "lk", tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0)
    )
    # Проверяем инвариант: current_stage == stage первого события (самого нового)
    assert timeline2["events"]
    assert timeline2["current_stage"] == timeline2["events"][0]["stage"]


def test_build_order_timeline_lk_promotes_tracking_over_newer_milestone() -> None:
    # delivery_started milestone может быть новее supplier по дате admin action
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"

    delivery_started_event = MagicMock()
    delivery_started_event.event_type = "delivery_started"
    delivery_started_event.created_at = datetime(2026, 7, 10, 12, 0, 0)
    order_events = [delivery_started_event]
    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-08T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "parcellab",
            }
        ],
    }

    timeline = build_order_timeline(
        order,
        order_events,
        tracking,
        "lk",
        tracking_updated_at=datetime(2026, 7, 10, 13, 0, 0),
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    assert timeline["current_stage"] == "in_transit"
    assert timeline["events"][0]["stage"] == "in_transit"


def test_manual_delivered_sync_state_contract() -> None:
    # Regression test: контракт для ручного этапа delivered
    # Проверка того, что при ручном delivered:
    # - sync_state = "delivered"
    # - next_check_at = None
    # - store_events сохраняются (не перезаписываются)

    order = MagicMock()
    order.id = 1
    order.supplier_tracking_json = None
    now = datetime(2026, 7, 9, 12, 0, 0)
    initialize_supplier_tracking(order, now)

    # Добавляем ручной этап delivered
    data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json or {}))
    store_events = list(data.get("store_events") or [])
    store_events.append(
        {
            "key": "store-delivered",
            "at": "2026-07-09T12:30:00Z",
            "stage": "delivered",
            "title": "Заказ выполнен",
            "description": "Ручной этап доставки",
            "source": "manual",
        }
    )
    data.update(
        {
            "current_stage": "delivered",
            "store_events": store_events,
        }
    )
    order.supplier_tracking_json = data
    order.supplier_tracking_sync_state = "delivered"
    order.supplier_tracking_next_check_at = None
    order.supplier_tracking_updated_at = datetime(2026, 7, 9, 12, 30, 0)

    # Проверяем контракт
    assert order.supplier_tracking_sync_state == "delivered"
    assert order.supplier_tracking_next_check_at is None

    # Проверяем, что store_events сохраняется
    updated_data = ensure_supplier_tracking_shape(
        dict(order.supplier_tracking_json or {})
    )
    assert len(updated_data.get("store_events") or []) == 2  # +1 созданный + 1 manual
    assert any(
        e.get("stage") == "delivered" and e.get("source") == "manual"
        for e in updated_data.get("store_events") or []
    )


def test_merge_supplier_events_does_not_overwrite_store_events() -> None:
    # Regression test: _merge_supplier_events не трогает store_events
    # Но! _merge_supplier_events перезаписывает current_stage из incoming
    # Это потенциальный конфликт, если в store_events есть более новый этап

    current = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
        "current_stage": "in_transit",
    }

    incoming = {
        "tracking_number": "CJ123",
        "current_stage": "dispatched",
        "events": [
            {
                "key": "pl-2",
                "at": "2026-07-07T12:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
    }

    merged, changed = _merge_supplier_events(current, incoming)

    # store_events остаются неизменными
    assert len(merged.get("store_events") or []) == 1
    assert merged["store_events"][0]["source"] == "manual"
    assert merged["store_events"][0]["stage"] == "in_transit"

    # supplier_events обновляются
    assert len(merged.get("supplier_events") or []) == 1
    assert merged["supplier_events"][0]["source"] == "parcellab"

    # current_stage остается из текущих данных (не перезаписывается из incoming)
    # Это исправленное поведение: current_stage не теряется при merge
    assert merged["current_stage"] == "in_transit"


def test_merge_supplier_events_preserves_manual_stage() -> None:
    # Regression test: после merge ParcelLab current_stage не должен перезаписываться
    # если в store_events есть более новый ручной этап

    # initial state: store_events has manual in_transit (10.07)
    current = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
        "current_stage": "in_transit",
    }

    incoming = {
        "tracking_number": "CJ123",
        "current_stage": "dispatched",
        "events": [
            {
                "key": "pl-2",
                "at": "2026-07-07T12:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
    }

    merged, changed = _merge_supplier_events(current, incoming)

    # store_events не потерялись
    assert len(merged.get("store_events") or []) == 1
    assert merged["store_events"][0]["source"] == "manual"
    assert merged["store_events"][0]["stage"] == "in_transit"

    # current_stage остался на ручном этапе (in_transit), не перезаписался на dispatched
    assert merged["current_stage"] == "in_transit"


def test_merge_supplier_events_updates_stage_when_parcellab_is_newer() -> None:
    # ParcelLab delivered новее manual dispatched → current_stage = delivered
    current = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-08T11:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "manual",
            }
        ],
        "current_stage": "dispatched",
    }

    # incoming: ParcelLab delivered (11.07) — новее ручного
    incoming = {
        "tracking_number": "CJ123",
        "current_stage": "delivered",
        "events": [
            {
                "key": "pl-2",
                "at": "2026-07-09T12:00:00Z",
                "stage": "delivered",
                "title": "Доставлен",
                "source": "parcellab",
            }
        ],
    }

    merged, changed = _merge_supplier_events(current, incoming)

    # store_events не потерялись
    assert len(merged.get("store_events") or []) == 1
    assert merged["store_events"][0]["source"] == "manual"

    # current_stage обновился на ParcelLab delivered (11.07) — новее ручного (10.07)
    assert merged["current_stage"] == "delivered"


def _delivery_order_mock() -> MagicMock:
    order = MagicMock()
    order.id = 1
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    return order


def test_carrier_fallback_manual_newer_is_current_stage() -> None:
    order = _delivery_order_mock()
    tracking = {
        "supplier_events": [
            {
                "key": "pl-1",
                "at": "2026-07-07T10:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "parcellab",
            }
        ],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-10T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-09T12:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "dhl",
            }
        ],
    }
    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=None,
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    assert timeline["use_carrier_fallback"] is True
    assert timeline["events"][0]["stage"] == "in_transit"
    assert timeline["current_stage"] == "in_transit"
    assert timeline["current_status"] == "В пути"


def test_merge_carrier_events_preserves_manual_current_stage() -> None:
    current = {
        "supplier_events": [],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-10T11:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
        "carrier_events": [],
        "current_stage": "in_transit",
    }
    incoming = {
        "tracking_number": "CJ1",
        "current_stage": "dispatched",
        "events": [
            {
                "key": "dhl-1",
                "at": "2026-07-09T12:00:00Z",
                "stage": "dispatched",
                "title": "Передан перевозчику",
                "source": "dhl",
            }
        ],
    }

    merged, changed = _merge_carrier_events(current, incoming)

    assert len(merged.get("store_events") or []) == 1
    assert merged["store_events"][0]["stage"] == "in_transit"
    assert merged["current_stage"] == "in_transit"
    assert changed is True


def test_carrier_fallback_carrier_newer_than_manual() -> None:
    order = _delivery_order_mock()
    tracking = {
        "supplier_events": [],
        "store_events": [
            {
                "key": "store-1",
                "at": "2026-07-09T12:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ],
        "carrier_events": [
            {
                "key": "dhl-1",
                "at": "2026-07-10T11:00:00Z",
                "stage": "delivered",
                "title": "Доставлен",
                "source": "dhl",
            }
        ],
    }
    timeline = build_order_timeline(
        order,
        [],
        tracking,
        "lk",
        tracking_updated_at=None,
        now=datetime(2026, 7, 10, 14, 0, 0),
    )

    assert timeline["use_carrier_fallback"] is True
    assert timeline["events"][0]["stage"] == "delivered"
    assert timeline["current_stage"] == "delivered"
    assert timeline["current_status"] == "Доставлен"


def _order_for_manual_event(
    tracking: dict,
    *,
    updated_at: datetime | None = None,
) -> MagicMock:
    order = MagicMock()
    order.id = 1
    order.user_id = 42
    order.created_at = datetime(2026, 7, 1, 10, 0, 0)
    order.updated_at = datetime(2026, 7, 1, 10, 0, 0)
    order.availability_confirmation_status = "not_required"
    order.payment_state = "paid"
    order.payment_paid_at = datetime(2026, 7, 1, 11, 0, 0)
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ1"
    order.status = "delivery"
    order.supplier_tracking_updated_at = updated_at
    order.supplier_tracking_json = tracking
    return order


@pytest.mark.asyncio
async def test_add_manual_event_stored_stage_matches_compute_when_supplier_newer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import supplier_tracking as st_mod

    manual_now = datetime(2026, 7, 10, 11, 0, 0)
    monkeypatch.setattr(st_mod, "utc_now_naive", lambda: manual_now)

    order = _order_for_manual_event(
        {
            "supplier_events": [
                {
                    "key": "pl-1",
                    "at": "2026-07-10T12:00:00Z",
                    "stage": "in_transit",
                    "title": "В пути",
                    "source": "parcellab",
                }
            ],
            "store_events": [],
            "carrier_events": [],
        },
        updated_at=datetime(2026, 7, 10, 13, 0, 0),
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=order)
    session.commit = AsyncMock()
    session.scalars = AsyncMock(
        return_value=MagicMock(list=lambda: [])  # type: ignore[call-arg]
    )

    await SupplierTrackingService(session).add_manual_event(
        order_id=1, stage="dispatched", description="ручной"
    )

    data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json))
    use_fallback = _supplier_events_stale(
        list(data.get("supplier_events") or []),
        order.supplier_tracking_updated_at,
        manual_now,
    )
    expected = _compute_current_stage(
        supplier_events=list(data.get("supplier_events") or []),
        store_events=list(data.get("store_events") or []),
        carrier_events=list(data.get("carrier_events") or []),
        use_carrier_fallback=use_fallback,
    )
    assert order.supplier_tracking_json["current_stage"] == expected
    assert expected == "in_transit"

    result = await SupplierTrackingService(session).public_tracking(
        order_id=1, user_id=42, now=manual_now
    )
    assert result.current_stage == expected


@pytest.mark.asyncio
async def test_add_manual_event_stored_stage_matches_public_tracking_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import supplier_tracking as st_mod

    manual_now = datetime(2026, 7, 10, 11, 0, 0)
    monkeypatch.setattr(st_mod, "utc_now_naive", lambda: manual_now)

    scenarios = [
        (
            "supplier",
            {
                "supplier_events": [
                    {
                        "key": "pl-1",
                        "at": "2026-07-10T12:00:00Z",
                        "stage": "in_transit",
                        "title": "В пути",
                        "source": "parcellab",
                    }
                ],
                "store_events": [],
                "carrier_events": [],
            },
            datetime(2026, 7, 10, 13, 0, 0),
            "dispatched",
            "in_transit",
        ),
        (
            "manual",
            {
                "supplier_events": [],
                "store_events": [],
                "carrier_events": [],
            },
            None,
            "in_transit",
            "in_transit",
        ),
        (
            "manual+supplier",
            {
                "supplier_events": [
                    {
                        "key": "pl-1",
                        "at": "2026-07-10T09:00:00Z",
                        "stage": "dispatched",
                        "title": "x",
                        "source": "parcellab",
                    }
                ],
                "store_events": [],
                "carrier_events": [],
            },
            datetime(2026, 7, 10, 13, 0, 0),
            "in_transit",
            "in_transit",
        ),
        (
            "carrier fallback",
            {
                "supplier_events": [],
                "store_events": [],
                "carrier_events": [
                    {
                        "key": "dhl-1",
                        "at": "2026-07-10T09:00:00Z",
                        "stage": "dispatched",
                        "title": "x",
                        "source": "dhl",
                    }
                ],
            },
            None,
            "in_transit",
            "in_transit",
        ),
        (
            "manual+carrier",
            {
                "supplier_events": [],
                "store_events": [],
                "carrier_events": [
                    {
                        "key": "dhl-1",
                        "at": "2026-07-10T12:00:00Z",
                        "stage": "delivered",
                        "title": "x",
                        "source": "dhl",
                    }
                ],
            },
            None,
            "in_transit",
            "delivered",
        ),
    ]

    for name, tracking, updated_at, manual_stage, expected_stage in scenarios:
        order = _order_for_manual_event(tracking, updated_at=updated_at)
        session = MagicMock()
        session.get = AsyncMock(return_value=order)
        session.commit = AsyncMock()
        session.scalars = AsyncMock(
            return_value=MagicMock(list=lambda: [])  # type: ignore[call-arg]
        )

        await SupplierTrackingService(session).add_manual_event(
            order_id=1, stage=manual_stage
        )

        data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json))
        use_fallback = _supplier_events_stale(
            list(data.get("supplier_events") or []),
            order.supplier_tracking_updated_at,
            manual_now,
        )
        computed = _compute_current_stage(
            supplier_events=list(data.get("supplier_events") or []),
            store_events=list(data.get("store_events") or []),
            carrier_events=list(data.get("carrier_events") or []),
            use_carrier_fallback=use_fallback,
        )
        assert order.supplier_tracking_json["current_stage"] == computed, name
        assert computed == expected_stage, name

        result = await SupplierTrackingService(session).public_tracking(
            order_id=1, user_id=42, now=manual_now
        )
        assert result.current_stage == expected_stage, name


@pytest.mark.asyncio
async def test_add_manual_event_rejects_completed_order() -> None:
    order = MagicMock()
    order.status = "completed"
    session = MagicMock()
    session.get = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="выполнен"):
        await SupplierTrackingService(session).add_manual_event(1, "in_transit")
