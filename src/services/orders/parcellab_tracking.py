import re
from dataclasses import dataclass
from typing import Any

from stealth_requests import AsyncStealthSession

from src.core.config import settings

PARCELLAB_URL = "https://api.parcellab.com/v2/checkpoints"


# Названия этапов для ЛК.
PARCELLAB_STAGE_LABELS = {
    "pick_up_scheduled": "Перевозчик ожидает посылку",
    "dispatched": "Передан перевозчику",
    "delivery_is_being_prepared": "Готовится к доставке",
    "in_transit": "В пути",
    "border_crossing": "Прибыл в страну назначения",
    "delivered": "Доставлен",
    "problem": "Нужна проверка",
    "unknown": "Обновление доставки",
}

# Маппинг кодов ParcelLab на этапы.
_PARCELLAB_STATUS_CODES: dict[str, str] = {
    "pickupscheduled": "pick_up_scheduled",
    "scheduledforcollection": "pick_up_scheduled",
    "pickup": "pick_up_scheduled",
    "orderprocessed": "pick_up_scheduled",
    "inboundscan": "dispatched",
    "dispatched": "dispatched",
    "intransit": "in_transit",
    "outfordelivery": "delivery_is_being_prepared",
    "destinationdeliverycenter": "delivery_is_being_prepared",
    "import": "border_crossing",
    "importhub": "border_crossing",
    "customsin": "border_crossing",
    "customscleared": "border_crossing",
    "bordercrossing": "border_crossing",
    "delivered": "delivered",
    "deliverydelivered": "delivered",
    "exception": "problem",
    "failed": "problem",
    "returntosender": "problem",
    "returned": "problem",
}


# Ошибки при запросе трекинга.
@dataclass(frozen=True)
class SupplierTrackingFetchError(Exception):
    code: str
    msg: str
    is_blocked: bool = False

    def __str__(self) -> str:
        return self.msg


# Результат обнаружения трекинга ParcelLab.
@dataclass(frozen=True)
class ParcelLabDiscoverResult:
    tracking_number: str | None
    carrier_label: str | None
    carrier_url: str | None
    raw_header: dict[str, Any]


# Нормализует код/текст ParcelLab в внутреннюю стадию.
def _parcellab_stage_from_raw(status: str, status_details: str) -> str:
    normalized_code = re.sub(r"[^a-z0-9]", "", status.lower())
    mapped = _PARCELLAB_STATUS_CODES.get(normalized_code)
    if mapped:
        return mapped
    details = status_details.lower()
    if "pick-up scheduled" in details or "pickup scheduled" in details:
        return "pick_up_scheduled"
    if "delivery is being prepared" in details:
        return "delivery_is_being_prepared"
    if "border crossing" in details or "customs" in details:
        return "border_crossing"
    if "in transit" in details or "on its way" in details:
        return "in_transit"
    if (
        "dispatched" in details
        or "handed over" in details
        or "have been sent" in details
    ):
        return "dispatched"
    if "delivered" in details:
        return "delivered"
    if "exception" in details or "problem" in details or "failed" in details:
        return "problem"
    return "unknown"


# Парсит body ParcelLab в нормализованные supplier_events.
def normalize_parcellab_body(payload: dict[str, Any]) -> dict[str, Any]:
    discovered = discover_from_parcellab_payload(payload)
    events: list[dict[str, Any]] = []
    current_stage: str | None = None
    if discovered is not None:
        tracking_id = str(discovered.raw_header.get("id") or "")
        last_code = (discovered.raw_header.get("last_delivery_status") or {}).get(
            "code"
        )
        for raw in (payload.get("body") or {}).get(tracking_id, []):
            if not raw.get("shown", True):
                continue
            status = str(raw.get("status") or "")
            details = str(raw.get("status_details") or "")
            stage = _parcellab_stage_from_raw(status, details)
            at = str(raw.get("timestamp") or "")
            external_id = str(raw.get("id") or at)
            events.append(
                {
                    "key": f"pl-{external_id}",
                    "at": at,
                    "stage": stage,
                    "title": PARCELLAB_STAGE_LABELS.get(
                        stage, PARCELLAB_STAGE_LABELS["unknown"]
                    ),
                    "source": "parcellab",
                    "raw_status": status,
                    "raw_text": details or None,
                    "location": str(raw.get("location") or "") or None,
                }
            )
        if events:
            sorted_events = sorted(events, key=lambda item: str(item.get("at") or ""))
            current_stage = str(sorted_events[-1].get("stage") or "") or None
        elif last_code:
            current_stage = _parcellab_stage_from_raw(str(last_code), "")
    return {
        "events": events,
        "current_stage": current_stage,
        "carrier_label": discovered.carrier_label if discovered else None,
        "carrier_url": discovered.carrier_url if discovered else None,
        "tracking_number": discovered.tracking_number if discovered else None,
    }


# Определяет captcha/anti-bot по телу ответа ParcelLab.
def _looks_like_challenge(text: str) -> bool:
    value = text.lower()
    return any(
        marker in value
        for marker in ("captcha", "cf-chl", "challenge-platform", "just a moment")
    )


# Собирает подпись перевозчика из header ParcelLab.
def _carrier_label_from_header(header: dict[str, Any]) -> str | None:
    courier = header.get("courier") or {}
    destination = courier.get("destination_courier") or {}
    names = [courier.get("prettyname"), destination.get("prettyname")]
    label = " / ".join(str(name) for name in names if name)
    if label:
        return label
    name = courier.get("name")
    return str(name) if name else None


# Извлекает CJ и метаданные перевозчика из ParcelLab без body-событий.
def discover_from_parcellab_payload(
    payload: dict[str, Any],
) -> ParcelLabDiscoverResult | None:
    headers = payload.get("header") or []
    if not headers:
        return None
    header = headers[0]
    courier = header.get("courier") or {}
    tracking_number = header.get("tracking_number")
    if not tracking_number:
        return None
    return ParcelLabDiscoverResult(
        tracking_number=str(tracking_number),
        carrier_label=_carrier_label_from_header(header),
        carrier_url=str(courier.get("trackingurl") or "") or None,
        raw_header=dict(header),
    )


# Загружает сырой JSON ParcelLab по номеру TP.
async def fetch_supplier_tracking(supplier_order_id: str) -> dict[str, Any] | None:
    params = {
        "user": settings.SUPPLIER_TRACKING_USER_ID,
        "orderNo": supplier_order_id,
        "lang": "en",
    }
    try:
        async with AsyncStealthSession() as session:
            response = await session.get(PARCELLAB_URL, params=params, timeout=30)
    except Exception as exc:
        raise SupplierTrackingFetchError(
            "network_error", "Не удалось подключиться к ParcelLab"
        ) from exc

    if response.status_code in {403, 429} or _looks_like_challenge(response.text):
        raise SupplierTrackingFetchError(
            "blocked", "ParcelLab временно заблокировал автоматическую проверку", True
        )
    if response.status_code >= 500:
        raise SupplierTrackingFetchError(
            "provider_error", "ParcelLab временно недоступен"
        )
    if response.status_code != 200:
        raise SupplierTrackingFetchError(
            "unexpected_response", f"ParcelLab вернул HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise SupplierTrackingFetchError(
            "invalid_json", "ParcelLab вернул ответ неизвестного формата"
        ) from exc
    if not isinstance(payload, dict):
        raise SupplierTrackingFetchError(
            "invalid_json", "ParcelLab вернул ответ неизвестного формата"
        )
    if not payload.get("header"):
        return None
    return payload


# Снимок ParcelLab для admin debug (обёртка над normalize_parcellab_body).
def build_parcellab_admin_snapshot(
    payload: dict[str, Any], fetched_at: str
) -> dict[str, Any]:
    normalized = normalize_parcellab_body(payload)
    return {
        "fetched_at": fetched_at,
        "tracking_number": normalized.get("tracking_number"),
        "carrier_label": normalized.get("carrier_label"),
        "carrier_url": normalized.get("carrier_url"),
        "events": [
            {
                "at": item.get("at"),
                "status": item.get("raw_status"),
                "description": item.get("raw_text"),
                "location": item.get("location"),
                "stage": item.get("stage"),
                "title": item.get("title"),
            }
            for item in normalized.get("events") or []
        ],
    }
