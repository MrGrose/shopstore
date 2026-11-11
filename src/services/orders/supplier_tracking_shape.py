from collections.abc import Mapping, Sequence
from typing import Any


# Приводит legacy tracking JSON к store/supplier/carrier_events.
def ensure_supplier_tracking_shape(data: dict[str, Any]) -> dict[str, Any]:
    if "store_events" in data or "carrier_events" in data or "supplier_events" in data:
        result = dict(data)
        result.setdefault("store_events", [])
        result.setdefault("carrier_events", [])
        result.setdefault("supplier_events", [])
        result.setdefault("russian_post_events", [])
        return result
    events = list(data.get("events") or [])
    store_events: list[dict[str, Any]] = []
    supplier_events: list[dict[str, Any]] = []
    carrier_events: list[dict[str, Any]] = []
    russian_post_events: list[dict[str, Any]] = []
    for item in events:
        source = str(item.get("source") or "")
        stage = str(item.get("stage") or "")
        if source == "dhl":
            carrier_events.append(item)
            continue
        if source == "pochta":
            russian_post_events.append(item)
            continue
        if source in {"auto", "parcellab"}:
            supplier_events.append(item)
            continue
        if source in {"manual", "store"} or stage in {"paid", "purchased"}:
            store_events.append(item)
    return {
        **data,
        "store_events": store_events,
        "supplier_events": supplier_events,
        "carrier_events": carrier_events,
        "russian_post_events": russian_post_events,
    }


# Список событий из tracking JSON для mypy-safe итерации.
def _tracking_event_list(raw: object) -> list[object]:
    return list(raw) if isinstance(raw, list) else []


# Есть ли terminal delivered в списке событий и время последнего.
def delivered_source_from_events(
    events: Sequence[object],
) -> tuple[bool, str | None]:
    delivered_events = [
        event
        for event in events
        if isinstance(event, Mapping) and str(event.get("stage") or "") == "delivered"
    ]
    if not delivered_events:
        return False, None
    newest = max(delivered_events, key=lambda item: str(item.get("at") or ""))
    at_raw = newest.get("at")
    return True, str(at_raw) if at_raw else None


# Есть ли terminal delivered от ParcelLab или DHL.
def has_terminal_delivered_signal(tracking_json: Mapping[str, object] | None) -> bool:
    data = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    parcellab_confirmed, _ = delivered_source_from_events(
        _tracking_event_list(data.get("supplier_events"))
    )
    dhl_confirmed, _ = delivered_source_from_events(
        _tracking_event_list(data.get("carrier_events"))
    )
    pochta_confirmed, _ = delivered_source_from_events(
        _tracking_event_list(data.get("russian_post_events"))
    )
    return parcellab_confirmed or dhl_confirmed or pochta_confirmed
