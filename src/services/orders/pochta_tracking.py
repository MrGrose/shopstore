import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from stealth_requests import AsyncStealthSession

logger = logging.getLogger(__name__)

POCHTA_TRACKING_URL = "https://www.pochta.ru/api/tracking/api/v1/trackings/by-barcodes"
POCHTA_PUBLIC_TRACKING_URL = "https://www.pochta.ru/tracking?barcode={barcode}"

POCHTA_STAGE_LABELS = {
    "preparing": "Принято в отделении связи",
    "dispatched": "Отправлено из страны отправления",
    "in_transit": "В пути",
    "destination": "В России",
    "last_mile": "В отделении / ожидает получения",
    "delivered": "Вручено",
}

_STAGE_PATTERNS: list[tuple[str, str]] = [
    ("вручено", "delivered"),
    ("вручение", "delivered"),
    ("хранится в отделении", "last_mile"),
    ("ожидает адресата", "last_mile"),
    ("в месте вручения", "last_mile"),
    ("готово к вручению", "last_mile"),
    ("доставка в место", "last_mile"),
    ("доставка по россии", "last_mile"),
    ("выпуск таможни", "destination"),
    ("таможн", "destination"),
    ("территорию россии", "destination"),
    ("регистрац", "destination"),
    ("отправлено из", "dispatched"),
    ("границ", "in_transit"),
    ("принято в отделении", "preparing"),
]

_GROUP_CODE_STAGE = {
    "READY_FOR_DELIVERY": "last_mile",
    "DELIVERED": "delivered",
    "IN_WAY": "in_transit",
    "RECEPTION_EXPECTED": "preparing",
}

_OPERATION_STAGE: dict[tuple[int, int | None], str] = {
    (1, 0): "preparing",
    (2, None): "delivered",
    (8, 5): "in_transit",
    (8, 13): "destination",
    (8, None): "in_transit",
    (9, 1): "destination",
    (10, 0): "dispatched",
    (11, None): "destination",
    (14, None): "destination",
}


@dataclass(frozen=True)
class PochtaTrackingFetchError(Exception):
    code: str
    message: str
    is_blocked: bool = False

    def __str__(self) -> str:
        return self.message


# Собирает kwargs прокси для AsyncStealthSession.
def _session_proxy_kwargs(proxy_url: str | None) -> dict[str, Any]:
    if not proxy_url:
        return {}
    return {"proxies": {"https": proxy_url, "http": proxy_url}}


# Публичная ссылка на трек Почты России по CJ/ШПИ.
def build_pochta_public_tracking_url(barcode: str) -> str:
    return POCHTA_PUBLIC_TRACKING_URL.format(barcode=quote(barcode.strip()))


# Определяет этап доставки по тексту статуса Почты России.
def _stage_from_status(status: str) -> str:
    value = status.lower()
    for pattern, stage in _STAGE_PATTERNS:
        if pattern in value:
            return stage
    return "in_transit"


# Определяет этап по operationType/operationAttr Почты России.
def _stage_from_operation(
    operation_type: int, operation_attr: int | None
) -> str | None:
    if (operation_type, operation_attr) in _OPERATION_STAGE:
        return _OPERATION_STAGE[(operation_type, operation_attr)]
    if (operation_type, None) in _OPERATION_STAGE:
        return _OPERATION_STAGE[(operation_type, None)]
    return None


# Определяет текущий этап по commonStatus/globalStatus и группам операций.
def _resolve_pochta_current_stage(
    tracking_item: dict[str, Any],
    events: list[dict[str, Any]],
) -> str | None:
    common_status = str(tracking_item.get("commonStatus") or "").lower()
    if "вручен" in common_status:
        return "delivered"
    if any(
        marker in common_status
        for marker in (
            "хранится в отделении",
            "ожидает адресата",
            "готово к вручению",
        )
    ):
        return "last_mile"

    global_status = str(tracking_item.get("globalStatus") or "").upper()
    if global_status == "DELIVERED":
        return "delivered"
    if global_status == "ARRIVED":
        return "last_mile"

    groups = tracking_item.get("trackingItemOperationGroupStatuses") or []
    for group in reversed(groups):
        code = str(group.get("code") or "")
        stage = _GROUP_CODE_STAGE.get(code)
        if stage:
            return stage

    return str(events[-1]["stage"]) if events else None


# Стабильный ключ события Почты России в russian_post_events.
def _event_key(at: str, stage: str, index: int) -> str:
    return f"pochta-{at}-{stage}-{index}"


# Нормализует ISO-дату Почты России в UTC ISO string.
def _normalize_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


# Собирает уникальные raw-события из payload Почты России.
def _collect_raw_events(tracking_item: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int | None]] = set()
    collected: list[dict[str, Any]] = []
    groups = tracking_item.get("trackingItemOperationGroupStatuses") or []
    for group in groups:
        for raw in group.get("originTrackingHistoryItems") or []:
            if not isinstance(raw, dict):
                continue
            at = str(raw.get("date") or "")
            status = str(raw.get("humanStatus") or "")
            operation_type = int(raw.get("operationType") or 0)
            operation_attr = raw.get("operationAttr")
            attr = int(operation_attr) if operation_attr is not None else None
            dedupe_key = (at, status, operation_type, attr)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            collected.append(raw)
    for raw in tracking_item.get("trackingHistoryItemList") or []:
        if not isinstance(raw, dict):
            continue
        at = str(raw.get("date") or "")
        status = str(raw.get("humanStatus") or "")
        operation_type = int(raw.get("operationType") or 0)
        operation_attr = raw.get("operationAttr")
        attr = int(operation_attr) if operation_attr is not None else None
        dedupe_key = (at, status, operation_type, attr)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        collected.append(raw)
    collected.sort(key=lambda item: str(item.get("date") or ""))
    return collected


# Нормализует JSON Почты России в russian_post_events.
def normalize_pochta_payload(payload: dict[str, Any], barcode: str) -> dict[str, Any]:
    detailed = payload.get("detailedTrackings") or []
    if not detailed:
        return {
            "tracking_number": barcode,
            "carrier_label": "Почта России",
            "carrier_source": "pochta",
            "carrier_url": build_pochta_public_tracking_url(barcode),
            "current_stage": None,
            "common_status": None,
            "expected_delivery_at": None,
            "storage_until_at": None,
            "events": [],
        }
    tracking_item = detailed[0].get("trackingItem") or {}
    raw_events = _collect_raw_events(tracking_item)
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_events):
        status = str(raw.get("humanStatus") or "").strip()
        if not status:
            continue
        operation_type = int(raw.get("operationType") or 0)
        operation_attr = raw.get("operationAttr")
        attr = int(operation_attr) if operation_attr is not None else None
        stage = _stage_from_status(status)
        if stage == "in_transit":
            stage = _stage_from_operation(operation_type, attr) or stage
        at = _normalize_at(str(raw.get("date") or "")) or ""
        location = str(raw.get("cityName") or raw.get("description") or "") or None
        events.append(
            {
                "key": _event_key(at, stage, index),
                "at": at,
                "stage": stage,
                "title": status,
                "description": status,
                "description_raw": status,
                "location": location,
                "source": "pochta",
            }
        )
    current_stage = _resolve_pochta_current_stage(tracking_item, events)
    shipment_trip = tracking_item.get("shipmentTripInfo") or {}
    expected_delivery_at = _normalize_at(
        str(shipment_trip.get("expectedDeliveryDate") or "") or None
    )
    storage_until_at = _normalize_at(
        str(tracking_item.get("endStorageDate") or "") or None
    )
    return {
        "tracking_number": str(tracking_item.get("barcode") or barcode),
        "carrier_label": "Почта России",
        "carrier_source": "pochta",
        "carrier_url": build_pochta_public_tracking_url(
            str(tracking_item.get("barcode") or barcode)
        ),
        "current_stage": current_stage,
        "common_status": str(tracking_item.get("commonStatus") or "") or None,
        "expected_delivery_at": expected_delivery_at,
        "storage_until_at": storage_until_at,
        "events": events,
    }


# Загружает и нормализует трек Почты России по CJ/ШПИ.
async def fetch_pochta_tracking(
    barcode: str,
    *,
    proxy_url: str | None = None,
) -> dict[str, Any]:
    params = {
        "language": "ru",
        "track-numbers": barcode.strip(),
    }
    try:
        async with AsyncStealthSession(**_session_proxy_kwargs(proxy_url)) as session:
            response = await session.get(
                POCHTA_TRACKING_URL,
                params=params,
                timeout=30,
            )
    except Exception as exc:
        raise PochtaTrackingFetchError(
            "network_error", "Не удалось подключиться к Почте России"
        ) from exc

    if response.status_code in {
        HTTPStatus.FORBIDDEN,
        HTTPStatus.TOO_MANY_REQUESTS,
    }:
        raise PochtaTrackingFetchError(
            "blocked",
            "Почта России временно заблокировала автоматическую проверку",
            True,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise PochtaTrackingFetchError(
            "provider_error", "Почта России временно недоступна"
        )
    if response.status_code != HTTPStatus.OK:
        raise PochtaTrackingFetchError(
            "unexpected_response",
            f"Почта России вернула HTTP {response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PochtaTrackingFetchError(
            "invalid_json", "Почта России вернула ответ неизвестного формата"
        ) from exc
    if not isinstance(payload, dict):
        raise PochtaTrackingFetchError(
            "invalid_json", "Почта России вернула ответ неизвестного формата"
        )
    return normalize_pochta_payload(payload, barcode)
