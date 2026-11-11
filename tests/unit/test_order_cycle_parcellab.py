from src.services.orders.parcellab_tracking import (
    _parcellab_stage_from_raw,
    normalize_parcellab_body,
)
from tests.fixtures.order_cycle_parcellab import (
    PARCELLAB_CYCLE_STAGES,
    applied_parcellab_stages,
    build_parcellab_payload_through,
    next_parcellab_stage,
)


def test_build_parcellab_payload_cumulative() -> None:
    payload = build_parcellab_payload_through("in_transit")
    normalized = normalize_parcellab_body(payload)
    assert len(normalized["events"]) == 3
    assert normalized["tracking_number"] == "CJ-DEMO-CYCLE-DE"
    assert normalized["events"][-1]["stage"] == "in_transit"


def test_applied_parcellab_stages_from_keys() -> None:
    tracking = {
        "supplier_events": [
            {"key": "pl-event-preparing", "stage": "pick_up_scheduled"},
            {"key": "pl-event-dispatched", "stage": "dispatched"},
        ]
    }
    assert applied_parcellab_stages(tracking) == ["preparing", "dispatched"]
    assert next_parcellab_stage(tracking) == "in_transit"


def test_delivered_payload_has_terminal_stage() -> None:
    payload = build_parcellab_payload_through("delivered")
    normalized = normalize_parcellab_body(payload)
    assert normalized["current_stage"] == "delivered"
    assert len(normalized["events"]) == len(PARCELLAB_CYCLE_STAGES)


# ImportHub — тот же смысл, что import / border crossing.
def test_importhub_maps_to_border_crossing() -> None:
    assert _parcellab_stage_from_raw("ImportHub", "") == "border_crossing"
    assert _parcellab_stage_from_raw("import", "") == "border_crossing"
