import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from stealth_requests import AsyncStealthSession

from src.utils.translate_descriptions import (
    is_mostly_russian,
    translate_plain_text_to_ru,
)

logger = logging.getLogger(__name__)

DHL_SEARCH_URL = "https://www.dhl.de/int-verfolgen/data/search"

_STAGE_PATTERNS: list[tuple[str, str]] = [
    ("successfully delivered", "delivered"),
    ("delivery successful", "delivered"),
    ("prepared for delivery in the delivery depot", "last_mile"),
    ("left the import parcel center", "in_transit"),
    ("customs clearance process", "in_transit"),
    ("arrived in the destination country", "destination"),
    ("transported to the destination country", "in_transit"),
    ("export parcel center", "dispatched"),
    ("parcel center of origin", "preparing"),
    ("instruction data for this shipment", "preparing"),
]

DHL_STAGE_LABELS = {
    "preparing": "Поставщик готовит отправление",
    "dispatched": "Передан перевозчику",
    "in_transit": "В пути",
    "destination": "Прибыл в страну назначения",
    "last_mile": "Передан местной службе доставки",
    "delivered": "Доставлен",
}

_DHL_STAGE_RANK = {
    "preparing": 30,
    "dispatched": 40,
    "in_transit": 50,
    "destination": 60,
    "last_mile": 70,
    "delivered": 80,
}

# Известные фразы DHL → русский текст (длинные паттерны первыми).
_DHL_STATUS_TRANSLATIONS: list[tuple[str, str]] = [
    (
        "the shipment will be transported to the destination country",
        "Отправление следует в страну назначения "
        "и будет передано местной службе доставки",
    ),
    (
        "the international shipment has been processed in the export parcel center",
        "Международное отправление обработано в экспортном сортировочном центре",
    ),
    (
        "the international shipment has been processed in the parcel center of origin",
        "Международное отправление обработано в сортировочном центре отправления",
    ),
    (
        "the instruction data for this shipment have been provided "
        "by the sender to dhl electronically",
        "Данные об отправлении переданы отправителем в DHL в электронном виде",
    ),
    (
        "instruction data for this shipment has been received",
        "Данные об отправлении получены",
    ),
    (
        "the shipment has been successfully delivered",
        "Отправление успешно доставлено",
    ),
    (
        "the shipment has left the export parcel center",
        "Отправление покинуло экспортный сортировочный центр",
    ),
    (
        "the shipment arrived in the destination country",
        "Отправление прибыло в страну назначения",
    ),
    (
        "the shipment has left the import parcel center",
        "Отправление покинуло импортный сортировочный центр",
    ),
    (
        "prepared for delivery in the delivery depot",
        "Подготовлено к доставке на складе выдачи",
    ),
    (
        "transported to the destination country",
        "Отправление следует в страну назначения",
    ),
    (
        "customs clearance process",
        "Прохождение таможенного оформления",
    ),
    (
        "arrived in the destination country",
        "Прибыло в страну назначения",
    ),
    (
        "left the import parcel center",
        "Покинуло импортный сортировочный центр",
    ),
    (
        "export parcel center",
        "Обработано в экспортном сортировочном центре",
    ),
    (
        "parcel center of origin",
        "Обработано в сортировочном центре отправления",
    ),
]

DHL_STAGE_DETAIL_RU = {
    "preparing": "Поставщик готовит отправление к отгрузке",
    "dispatched": "Отправление передано в международную доставку",
    "in_transit": "Отправление в пути",
    "destination": "Отправление прибыло в страну назначения",
    "last_mile": "Передано местной службе доставки",
    "delivered": "Отправление доставлено",
}


@dataclass(frozen=True)
class DhlTrackingFetchError(Exception):
    code: str
    message: str
    is_blocked: bool = False

    def __str__(self) -> str:
        return self.message


# Убирает HTML-теги из текста статуса DHL.
def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


# Выбирает актуальный этап: headline DHL не откатывает более позднее событие.
def _resolve_dhl_current_stage(
    events: list[dict[str, Any]], headline: str
) -> str | None:
    event_stage = str(events[-1]["stage"]) if events else None
    if not headline:
        return event_stage
    headline_stage = _stage_from_status(headline)
    if not event_stage:
        return headline_stage
    event_rank = _DHL_STAGE_RANK.get(event_stage, 0)
    headline_rank = _DHL_STAGE_RANK.get(headline_stage, 0)
    return event_stage if event_rank >= headline_rank else headline_stage


# Маппит английский статус DHL на внутренний stage.
def _stage_from_status(status: str) -> str:
    value = _strip_html(status).lower()
    for pattern, stage in _STAGE_PATTERNS:
        if pattern in value:
            return stage
    if "germany" in value:
        return "dispatched"
    if "russian federation" in value or "russia" in value:
        return "in_transit"
    return "in_transit"


# Конвертирует datum DHL в ISO UTC.
def _datum_to_iso(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat()


# Стабильный ключ события DHL в carrier_events.
def _event_key(at: str, stage: str, index: int) -> str:
    return f"dhl|{index}|{at}|{stage}"


# Человекочитаемый заголовок этапа DHL.
def _stage_label(stage: str) -> str:
    return DHL_STAGE_LABELS.get(stage, stage)


# Переводит статус DHL на русский; при парсинге — Google для неизвестных фраз.
def translate_dhl_status_text(
    status: str,
    stage: str | None = None,
    use_machine_translate: bool = False,
) -> str | None:
    cleaned = _strip_html(status)
    if not cleaned:
        return DHL_STAGE_DETAIL_RU.get(stage or "") if stage else None
    if is_mostly_russian(cleaned):
        return cleaned
    value = cleaned.lower()
    for pattern, translation in _DHL_STATUS_TRANSLATIONS:
        if pattern in value:
            return translation
    if use_machine_translate:
        machine = translate_plain_text_to_ru(cleaned, source="en")
        if machine and is_mostly_russian(machine):
            return machine
    if stage:
        return DHL_STAGE_DETAIL_RU.get(stage)
    return None


_BLOCKED_BODY_MARKERS = (
    "captcha",
    "cf-chl",
    "challenge-platform",
    "just a moment",
    "fehlermeldung",
    "technischer fehler",
    "akamai",
    "access denied",
)


# Определяет captcha/Akamai/HTML-ошибку по телу ответа.
def _looks_like_challenge(text: str) -> bool:
    value = text.lower()
    return any(marker in value for marker in _BLOCKED_BODY_MARKERS)


# Возвращает Content-Type из заголовков ответа DHL.
def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None) or {}
    if hasattr(headers, "get"):
        return str(headers.get("content-type") or headers.get("Content-Type") or "")
    return ""


# Определяет HTML-ошибку (Akamai/Fehlermeldung) по телу и Content-Type.
def _looks_like_html_body(text: str, content_type: str) -> bool:
    lowered_type = content_type.lower()
    if "json" in lowered_type:
        return False
    stripped = text.lstrip()
    if stripped.startswith("<"):
        return True
    return "html" in lowered_type


# Собирает kwargs прокси для AsyncStealthSession.
def _session_proxy_kwargs(proxy_url: str | None) -> dict[str, Any]:
    if not proxy_url:
        return {}
    return {"proxies": {"https": proxy_url, "http": proxy_url}}


# Поднимает blocked-ошибку для ответов DHL с challenge/HTML.
def _raise_blocked_dhl_response() -> None:
    raise DhlTrackingFetchError(
        "blocked", "DHL временно заблокировал автоматическую проверку", True
    )


# Парсит HTTP-ответ DHL (status + body) в JSON payload.
def parse_dhl_http_response(
    status_code: int, text: str, content_type: str = ""
) -> dict[str, Any]:
    if status_code in {
        HTTPStatus.FORBIDDEN,
        HTTPStatus.TOO_MANY_REQUESTS,
    } or _looks_like_challenge(text):
        _raise_blocked_dhl_response()
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise DhlTrackingFetchError("provider_error", "DHL временно недоступен")
    if status_code != HTTPStatus.OK:
        raise DhlTrackingFetchError(
            "unexpected_response", f"DHL вернул HTTP {status_code}"
        )
    if _looks_like_html_body(text, content_type):
        _raise_blocked_dhl_response()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        if _looks_like_challenge(text) or _looks_like_html_body(text, content_type):
            _raise_blocked_dhl_response()
        raise DhlTrackingFetchError(
            "invalid_json", "DHL вернул ответ неизвестного формата"
        ) from exc
    if not isinstance(payload, dict):
        raise DhlTrackingFetchError(
            "invalid_json", "DHL вернул ответ неизвестного формата"
        )
    return payload


# Парсит JSON ответа DHL из объекта response (stealth/playwright adapter).
def _parse_dhl_response_json(response: Any) -> dict[str, Any]:
    return parse_dhl_http_response(
        response.status_code,
        response.text,
        _response_content_type(response),
    )


# Нормализует raw DHL payload после успешного fetch.
def normalize_fetched_dhl_payload(
    payload: dict[str, Any], piececode: str
) -> dict[str, Any]:
    if not payload.get("sendungen"):
        return normalize_dhl_payload({}, piececode)
    return normalize_dhl_payload(payload, piececode)


# Нормализует JSON DHL в carrier_events и текущий этап.
def normalize_dhl_payload(payload: dict[str, Any], piececode: str) -> dict[str, Any]:
    shipments = payload.get("sendungen") or []
    if not shipments:
        return {
            "tracking_number": piececode,
            "carrier_label": "DHL",
            "carrier_source": "dhl",
            "current_stage": None,
            "events": [],
        }
    shipment = shipments[0]
    details = shipment.get("sendungsdetails") or {}
    progress = details.get("sendungsverlauf") or {}
    raw_events = list(progress.get("events") or [])
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_events):
        status = str(raw.get("status") or "")
        if not status:
            continue
        stage = _stage_from_status(status)
        at = _datum_to_iso(str(raw.get("datum") or ""))
        events.append(
            {
                "key": _event_key(at, stage, index),
                "at": at,
                "stage": stage,
                "title": _stage_label(stage),
                "description": translate_dhl_status_text(
                    status, stage, use_machine_translate=True
                ),
                "description_raw": _strip_html(status),
                "location": str(raw.get("ort") or "") or None,
                "source": "dhl",
            }
        )
    headline = _strip_html(str(progress.get("status") or ""))
    current_stage = _resolve_dhl_current_stage(events, headline)
    tracking_number = (
        details.get("sendungsnummern", {}).get("sendungsnummer") or piececode
    )
    return {
        "tracking_number": str(tracking_number),
        "carrier_label": "DHL",
        "carrier_source": "dhl",
        "current_stage": current_stage,
        "events": events,
    }


# Один HTTP-запрос к DHL search API (опционально через proxy).
async def _fetch_dhl_tracking_once(
    piececode: str,
    language: str = "ru",
    proxy_url: str | None = None,
) -> dict[str, Any]:
    params = {"piececode": piececode.strip(), "language": language}
    try:
        async with AsyncStealthSession(**_session_proxy_kwargs(proxy_url)) as session:
            response = await session.get(DHL_SEARCH_URL, params=params, timeout=30)
    except Exception as exc:
        raise DhlTrackingFetchError(
            "network_error", "Не удалось подключиться к DHL"
        ) from exc

    payload = _parse_dhl_response_json(response)
    return normalize_fetched_dhl_payload(payload, piececode)


# Загружает и нормализует трек DHL по CJ-номеру (HTTP direct + proxy).
async def fetch_dhl_tracking(
    piececode: str,
    language: str = "ru",
    proxy_url: str | None = None,
) -> dict[str, Any]:
    blocked_exc: DhlTrackingFetchError | None = None
    try:
        return await _fetch_dhl_tracking_once(piececode, language=language)
    except DhlTrackingFetchError as exc:
        if not exc.is_blocked:
            raise
        blocked_exc = exc

    if proxy_url:
        try:
            return await _fetch_dhl_tracking_once(
                piececode, language=language, proxy_url=proxy_url
            )
        except DhlTrackingFetchError as exc:
            if not exc.is_blocked:
                raise
            blocked_exc = exc

    if blocked_exc is not None:
        raise blocked_exc
    raise DhlTrackingFetchError(
        "blocked", "DHL временно заблокировал автоматическую проверку", True
    )


# CLI для ручной проверки парсера DHL.
async def _main() -> None:
    parser = argparse.ArgumentParser(description="DHL tracking parser spike")
    parser.add_argument("piececode")
    parser.add_argument("--language", default="ru")
    args = parser.parse_args()
    result = await fetch_dhl_tracking(args.piececode, language=args.language)
    for event in result.get("events") or []:
        print(event.get("at"), event.get("stage"), "|", event.get("description"))


if __name__ == "__main__":
    asyncio.run(_main())
