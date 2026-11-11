import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderStatus,
    ShipmentStatus,
    SupplierOrder,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import SupplierTrackingPublicSchema
from src.services.admin_notification_service import (
    sync_delivered_alert_after_tracking_check,
    sync_shipment_delivered_alert,
)
from src.services.orders.dhl_tracking import (
    DhlTrackingFetchError,
    fetch_dhl_tracking,
    translate_dhl_status_text,
)
from src.services.orders.parcellab_tracking import (
    PARCELLAB_STAGE_LABELS,
    SupplierTrackingFetchError,
    build_parcellab_admin_snapshot,
    discover_from_parcellab_payload,
    fetch_supplier_tracking,
    normalize_parcellab_body,
)
from src.services.orders.pochta_tracking import (
    PochtaTrackingFetchError,
    fetch_pochta_tracking,
)
from src.services.orders.shipments import (
    ShipmentService,
    all_shipments_delivered,
    apply_dhl_to_shipment,
    apply_parcellab_to_shipment,
    apply_pochta_to_shipment,
    is_legacy_tracking_mirror,
)
from src.services.orders.supplier_orders import normalize_legacy_supplier_order_id
from src.services.orders.supplier_tracking_shape import ensure_supplier_tracking_shape
from src.utils.datetime_fmt import format_iso_datetime_msk_short
from src.utils.translate_descriptions import is_mostly_russian

logger = logging.getLogger(__name__)

DhlBrowserFetchFn = Callable[[str], Awaitable[dict[str, Any]]]
SessionFactory = Callable[[], AsyncSession]


# Plain values одного placed SO; без ORM через I/O.
@dataclass(frozen=True)
class _PlacedSyncTarget:
    supplier_order_id: int
    tp_id: str
    existing_cj: str
    is_mirror: bool


# Snapshot заказа для внешнего I/O.
@dataclass(frozen=True)
class _OrderSyncSnapshot:
    order_id: int
    legacy_supplier_order_id: str | None
    legacy_supplier_tracking_id: str
    placed: tuple[_PlacedSyncTarget, ...]


# Результаты HTTP по одному placed SO.
@dataclass(frozen=True)
class _PlacedFetchResult:
    supplier_order_id: int
    parcellab_payload: dict[str, Any] | None
    parcellab_error: SupplierTrackingFetchError | None
    dhl_payload: dict[str, Any] | None
    dhl_error: DhlTrackingFetchError | None
    pochta_payload: dict[str, Any] | None
    pochta_error: PochtaTrackingFetchError | None


# Результаты HTTP legacy-ветки без placed SO.
@dataclass(frozen=True)
class _LegacyFetchResult:
    parcellab_payload: dict[str, Any] | None
    parcellab_error: SupplierTrackingFetchError | None
    dhl_payload: dict[str, Any] | None
    dhl_error: DhlTrackingFetchError | None
    pochta_payload: dict[str, Any] | None
    pochta_error: PochtaTrackingFetchError | None


# Все payload'ы после I/O, до persist.
@dataclass(frozen=True)
class _OrderFetchResult:
    placed: tuple[_PlacedFetchResult, ...]
    legacy: _LegacyFetchResult | None


# Названия этапов для ЛК (общие с ParcelLab берём из PARCELLAB_STAGE_LABELS).
STAGE_LABELS = {
    "created": "Заказ оформлен",
    "availability": "Наличие подтверждено",
    "paid": "Заказ оплачен",
    "assembling": "В сборке",
    "delivery_started": "Передан в доставку",
    "purchased": "Передан поставщику",
    "preparing": "Поставщик готовит отправление",
    "dispatched": PARCELLAB_STAGE_LABELS["dispatched"],
    "in_transit": PARCELLAB_STAGE_LABELS["in_transit"],
    "destination": "Прибыл в страну назначения",
    "last_mile": "Передан местной службе",
    "delivered": PARCELLAB_STAGE_LABELS["delivered"],
    "completed": "Заказ выполнен",
}

MANUAL_STAGES = tuple(key for key in STAGE_LABELS if key not in {"paid", "completed"})

# Ранги этапов для сортировки.
STAGE_RANK = {
    "created": 5,
    "availability": 8,
    "paid": 10,
    "assembling": 20,
    "purchased": 20,
    "delivery_started": 35,
    "pick_up_scheduled": 38,
    "preparing": 40,
    "unknown": 43,
    "dispatched": 45,
    "delivery_is_being_prepared": 48,
    "in_transit": 50,
    "border_crossing": 58,
    "destination": 60,
    "last_mile": 70,
    "delivered": 80,
    "problem": 85,
    "completed": 90,
}

TimelineMode = Literal["lk", "admin"]

PAID_PAYMENT_STATES = frozenset({"paid", "late_paid_after_cancel"})

LOCATION_LABELS = {
    "germany": "Германия",
    "russian federation": "Россия",
    "russia": "Россия",
}


# Возвращает naive UTC «сейчас» для полей синхронизации.
def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# Сериализует datetime в ISO для JSON трекинга.
def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


# Стабильный ключ события в supplier_tracking_json.
def _event_key(at: str, stage: str, source: str, external_id: str = "") -> str:
    return f"{external_id or at}|{stage}|{source}"


# Парсит ISO-время события для сортировки.
def _parse_event_at(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


# Ключ сортировки: сначала дата, потом ранг этапа (неизвестный — середина).
def _event_sort_key(item: dict[str, Any]) -> tuple[datetime, int]:
    stage = str(item.get("stage") or "")
    return _parse_event_at(item.get("at")), STAGE_RANK.get(stage, 50)


# Сортирует события по дате и рангу этапа.
def _sort_tracking_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=_event_sort_key)


# Локализует город/страну из DHL для клиентского UI.
def _location_label(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return LOCATION_LABELS.get(text.lower(), text)


# Проверяет, что событие пришло от перевозчика, а не из store/manual.
def _is_carrier_tracking_event(event: dict[str, Any]) -> bool:
    return str(event.get("source") or "") in {"dhl", "auto"}


# Единая проекция события для админки и ЛК.
def project_tracking_event_for_display(event: dict[str, Any]) -> dict[str, Any]:
    stage = str(event.get("stage") or "")
    title = str(event.get("title") or STAGE_LABELS.get(stage, stage))
    description: str | None
    location: str | None
    if _is_carrier_tracking_event(event):
        stored_description = str(event.get("description") or "").strip()
        raw_description = event.get("description_raw") or event.get("description")
        if stored_description and is_mostly_russian(stored_description):
            description = stored_description
        else:
            description = translate_dhl_status_text(
                str(raw_description or ""), stage, use_machine_translate=False
            )
        location = _location_label(event.get("location"))
    else:
        raw_description = event.get("description")
        description = str(raw_description).strip() if raw_description else None
        location = None
    return {
        "key": event.get("key"),
        "at": event.get("at"),
        "stage": stage,
        "title": title,
        "description": description,
        "location": location,
    }


# Возвращает ISO-время первого события заказа из списка типов.
def _first_order_event_iso(
    order_events: list[OrderEvent], *event_types: str
) -> str | None:
    wanted = set(event_types)
    for row in order_events:
        if row.event_type in wanted and row.created_at is not None:
            return _iso(row.created_at)
    return None


# Проверяет, что заказ оплачен (по полям заказа).
def _order_is_paid(order: Order) -> bool:
    payment_state = str(getattr(order, "payment_state", "") or "")
    if payment_state in PAID_PAYMENT_STATES:
        return True
    return order.payment_paid_at is not None


# Собирает Shopstore-этапы для ЛК: оформление → наличие → оплата → сборка → доставка.
def build_customer_store_journey_events(
    order: Order, order_events: list[OrderEvent]
) -> list[dict[str, Any]]:
    milestones: list[dict[str, Any]] = []
    created_at = _iso(order.created_at)
    if created_at:
        milestones.append(
            {
                "key": f"created-{order.id}",
                "at": created_at,
                "stage": "created",
                "title": STAGE_LABELS["created"],
                "source": "store",
            }
        )

    availability = str(
        order.availability_confirmation_status
        or AvailabilityConfirmationStatus.NOT_REQUIRED
    )
    if availability == AvailabilityConfirmationStatus.CONFIRMED:
        availability_at = _first_order_event_iso(
            order_events,
            "availability_confirmed",
            "availability_stock_check_saved",
        )
        if availability_at:
            milestones.append(
                {
                    "key": f"availability-{order.id}",
                    "at": availability_at,
                    "stage": "availability",
                    "title": STAGE_LABELS["availability"],
                    "source": "store",
                }
            )

    if _order_is_paid(order):
        paid_at = _iso(order.payment_paid_at) or _first_order_event_iso(
            order_events, "payment_accepted"
        )
        if paid_at:
            milestones.append(
                {
                    "key": f"paid-{order.id}",
                    "at": paid_at,
                    "stage": "paid",
                    "title": STAGE_LABELS["paid"],
                    "source": "store",
                }
            )

    supplier_order_id = str(order.supplier_order_id or "").strip()
    if supplier_order_id:
        assembling_at = _first_order_event_iso(order_events, "assembly_started")
        milestones.append(
            {
                "key": f"assembling-{order.id}",
                "at": assembling_at or created_at,
                "stage": "assembling",
                "title": STAGE_LABELS["assembling"],
                "source": "store",
            }
        )

    supplier_tracking_id = str(order.supplier_tracking_id or "").strip()
    if supplier_tracking_id or order.status in {
        OrderStatus.DELIVERY,
        OrderStatus.COMPLETED,
    }:
        delivery_at = _first_order_event_iso(order_events, "delivery_started")
        milestones.append(
            {
                "key": f"delivery-started-{order.id}",
                "at": delivery_at or created_at,
                "stage": "delivery_started",
                "title": STAGE_LABELS["delivery_started"],
                "source": "store",
            }
        )

    if order.status == OrderStatus.COMPLETED:
        completed_at = _iso(order.updated_at) or created_at
        if completed_at:
            milestones.append(
                {
                    "key": f"completed-{order.id}",
                    "at": completed_at,
                    "stage": "completed",
                    "title": STAGE_LABELS["completed"],
                    "source": "store",
                }
            )

    return milestones


# Текущий этап для блока «Сейчас» в ЛК (без carrier, если есть supplier).
def _customer_current_stage(
    order: Order,
    supplier_events: list[dict[str, Any]],
    carrier_events: list[dict[str, Any]],
    use_carrier_fallback: bool,
    store_events: list[dict[str, Any]] | None = None,
) -> str | None:
    if order.status == OrderStatus.COMPLETED:
        return "completed"
    stage_from_events = _compute_current_stage(
        supplier_events=list(supplier_events or []),
        store_events=list(store_events or []),
        carrier_events=list(carrier_events or []),
        use_carrier_fallback=use_carrier_fallback,
    )
    if stage_from_events is not None:
        return stage_from_events
    if order.supplier_tracking_id or order.status == OrderStatus.DELIVERY:
        return "delivery_started"
    if order.supplier_order_id or order.status == OrderStatus.ASSEMBLING:
        return "assembling"
    if _order_is_paid(order):
        return "paid"
    if (
        str(order.availability_confirmation_status or "")
        == AvailabilityConfirmationStatus.CONFIRMED
    ):
        return "availability"
    return "created"


# Подпись текущего этапа для ЛК.
def _customer_current_label(stage: str | None) -> str | None:
    if not stage:
        return None
    return PARCELLAB_STAGE_LABELS.get(stage) or STAGE_LABELS.get(stage, stage)


# Короткая подсказка под блоком «Сейчас» в ЛК.
def _lk_current_description(stage: str | None) -> str | None:
    if not stage:
        return None
    hints = {
        "assembling": "Оформлен на Supplier-Demo",
        "delivery_started": "Посылка у перевозчика",
    }
    return hints.get(stage)


# Проверяет, что supplier_events пустой или устарел для fallback на DHL.
def _supplier_events_stale(
    supplier_events: list[dict[str, Any]],
    tracking_updated_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if not supplier_events:
        return True
    if tracking_updated_at is None:
        logger.warning(
            "supplier_events есть, но tracking_updated_at=None — "
            "ЛК переключится на DHL fallback"
        )
        return True
    current = now or utc_now_naive()
    updated = tracking_updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    current_aware = current.replace(tzinfo=UTC)
    age = current_aware - updated.astimezone(UTC)
    return age > timedelta(hours=settings.SUPPLIER_TRACKING_ACTIVE_HOURS)


# Схлопывает подряд идущие одинаковые стадии (оставляет последнюю по времени).
def _collapse_consecutive_stages(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not events:
        return []
    sorted_events = _sort_tracking_events(list(events))
    collapsed: list[dict[str, Any]] = []
    for event in sorted_events:
        stage = str(event.get("stage") or "")
        if collapsed and str(collapsed[-1].get("stage") or "") == stage:
            collapsed[-1] = dict(event)
            continue
        collapsed.append(dict(event))
    collapsed.sort(key=_event_sort_key, reverse=True)
    return collapsed


# Короткая проекция carrier-событий для LK fallback без raw-текста.
def _carrier_events_for_lk_fallback(
    carrier_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback: list[dict[str, Any]] = []
    for event in carrier_events:
        stage = str(event.get("stage") or "")
        fallback.append(
            {
                "key": event.get("key"),
                "at": event.get("at"),
                "stage": stage,
                "title": STAGE_LABELS.get(stage, stage),
                "source": "dhl",
            }
        )
    return fallback


# Ставит событие current_stage первым в ЛК-таймлайне, если оно есть в списке.
def _promote_current_stage_in_timeline(
    events: list[dict[str, Any]],
    current_stage: str | None,
) -> list[dict[str, Any]]:
    if not current_stage or not events:
        return events
    idx = next(
        (i for i, event in enumerate(events) if event.get("stage") == current_stage),
        None,
    )
    if idx is None or idx == 0:
        return events
    promoted = dict(events[idx])
    return [promoted, *events[:idx], *events[idx + 1 :]]


# Проекция события для клиентского таймлайна.
def _project_lk_timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    stage = str(event.get("stage") or "")
    title = str(
        event.get("title")
        or PARCELLAB_STAGE_LABELS.get(stage)
        or STAGE_LABELS.get(stage, stage)
    )
    return {
        "key": event.get("key"),
        "at": event.get("at"),
        "stage": stage,
        "title": title,
        "description": None,
    }


# Склеивает русский статус DHL и локацию для однострочного UI.
def _carrier_description_line(
    description: str | None, location: str | None
) -> str | None:
    if description and location:
        return f"{description} · {location}"
    return description or location


# Проекция события для admin-таймлайна с source и raw-полями.
def _project_admin_timeline_row(event: dict[str, Any]) -> dict[str, Any]:
    source = str(event.get("source") or "")
    if source in {"dhl", "auto", "pochta"}:
        projected = project_tracking_event_for_display(event)
        at_raw = projected.get("at")
        return {
            "title": projected["title"],
            "description": _carrier_description_line(
                projected.get("description"),
                projected.get("location"),
            ),
            "at": at_raw,
            "at_display": format_iso_datetime_msk_short(at_raw),
            "source": source,
            "raw_text": event.get("description_raw") or event.get("description"),
            "location": projected.get("location"),
            "stage": projected.get("stage"),
        }
    at_raw = event.get("at")
    raw_text = event.get("raw_text") or event.get("description")
    return {
        "title": str(event.get("title") or ""),
        "description": raw_text,
        "at": at_raw,
        "at_display": format_iso_datetime_msk_short(at_raw),
        "source": source or "order",
        "raw_text": raw_text,
        "location": event.get("location"),
        "stage": event.get("stage"),
    }


# Единый агрегатор таймлайна для ЛК и админки.
def build_order_timeline(
    order: Order,
    order_events: list[OrderEvent],
    tracking_json: dict[str, Any] | None,
    mode: TimelineMode,
    tracking_updated_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    data = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    order_milestones = build_customer_store_journey_events(order, order_events)
    supplier_events = list(data.get("supplier_events") or [])
    carrier_events = list(data.get("carrier_events") or [])
    store_events = list(data.get("store_events") or [])

    if mode == "lk":
        use_carrier_fallback = _supplier_events_stale(
            supplier_events, tracking_updated_at, now
        )
        shipment_events = (
            _carrier_events_for_lk_fallback(carrier_events)
            if use_carrier_fallback
            else list(supplier_events)
        )
        # include store_events (manual stages) in lk timeline
        raw_events = order_milestones + store_events + shipment_events
        raw_events = _collapse_consecutive_stages(raw_events)
        stage = _customer_current_stage(
            order,
            supplier_events,
            carrier_events,
            use_carrier_fallback=use_carrier_fallback,
            store_events=store_events,
        )
        events = _promote_current_stage_in_timeline(
            [_project_lk_timeline_event(item) for item in raw_events],
            stage,
        )
        return {
            "events": events,
            "current_stage": stage,
            "current_status": _customer_current_label(stage),
            "current_description": _lk_current_description(stage),
            "carrier_label": data.get("carrier_label"),
            "use_carrier_fallback": use_carrier_fallback,
            "last_updated_at": tracking_updated_at,
        }

    raw_events = order_milestones + store_events + supplier_events + carrier_events
    raw_events.sort(key=_event_sort_key, reverse=True)
    events = [_project_admin_timeline_row(item) for item in raw_events]
    supplier_timeline = [_project_admin_timeline_row(item) for item in supplier_events]
    supplier_timeline.sort(key=_event_sort_key, reverse=True)
    carrier_timeline = [_project_admin_timeline_row(item) for item in carrier_events]
    carrier_timeline.sort(key=_event_sort_key, reverse=True)
    russian_post_events = list(data.get("russian_post_events") or [])
    russian_post_timeline = [
        _project_admin_timeline_row(item) for item in russian_post_events
    ]
    russian_post_timeline.sort(key=_event_sort_key, reverse=True)
    stage = _customer_current_stage(
        order,
        supplier_events,
        carrier_events,
        use_carrier_fallback=_supplier_events_stale(
            supplier_events, tracking_updated_at, now
        ),
        store_events=store_events,
    )
    return {
        "events": events,
        "current_stage": stage,
        "current_status": _customer_current_label(stage),
        "supplier_timeline": supplier_timeline,
        "carrier_timeline": carrier_timeline,
        "russian_post_timeline": russian_post_timeline,
        "carrier_label": data.get("carrier_label"),
        "carrier_source": data.get("carrier_source"),
        "carrier_url": data.get("carrier_url"),
        "russian_post_url": data.get("russian_post_url"),
        "russian_post_status": data.get("russian_post_status"),
        "russian_post_expected_delivery_at": data.get(
            "russian_post_expected_delivery_at"
        ),
    }


# События ParcelLab для карточки доставки в админке.
def supplier_timeline_for_journey(
    tracking_json: dict[str, Any] | None,
    supplier_order_id: str | None,
) -> list[dict[str, Any]]:
    if not supplier_order_id:
        return []
    shaped = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    timeline = [
        _project_admin_timeline_row(event)
        for event in shaped.get("supplier_events") or []
        if isinstance(event, dict)
    ]
    timeline.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return timeline


# События DHL под картой заказа (новые сверху).
def carrier_timeline_for_journey(
    tracking_json: dict[str, Any] | None,
    supplier_tracking_id: str | None,
) -> list[dict[str, Any]]:
    if not supplier_tracking_id:
        return []
    shaped = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    timeline = [
        _project_admin_timeline_row(event)
        for event in shaped.get("carrier_events") or []
        if isinstance(event, dict)
    ]
    timeline.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return timeline


# События Почты России для карточки доставки в админке.
def russian_post_timeline_for_journey(
    tracking_json: dict[str, Any] | None,
    supplier_tracking_id: str | None,
) -> list[dict[str, Any]]:
    if not supplier_tracking_id:
        return []
    shaped = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    timeline = [
        _project_admin_timeline_row(event)
        for event in shaped.get("russian_post_events") or []
        if isinstance(event, dict)
    ]
    timeline.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return timeline


# Мержит события Почты России в russian_post_events.
def _merge_russian_post_events(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    data = ensure_supplier_tracking_shape(current)
    incoming_events = _sort_tracking_events(list(incoming.get("events") or []))
    old_events = list(data.get("russian_post_events") or [])
    changed = incoming_events != old_events
    merged = {
        **data,
        "russian_post_events": incoming_events,
        "russian_post_url": incoming.get("carrier_url") or data.get("russian_post_url"),
        "russian_post_status": incoming.get("common_status")
        or data.get("russian_post_status"),
        "russian_post_expected_delivery_at": incoming.get("expected_delivery_at")
        or data.get("russian_post_expected_delivery_at"),
        "russian_post_storage_until_at": incoming.get("storage_until_at")
        or data.get("russian_post_storage_until_at"),
        "russian_post_last_error": None,
    }
    for key in (
        "russian_post_url",
        "russian_post_status",
        "russian_post_expected_delivery_at",
        "russian_post_storage_until_at",
        "russian_post_last_error",
    ):
        if data.get(key) != merged.get(key):
            changed = True
    if old_events != incoming_events:
        changed = True
    return merged, changed


# События store (только ручные этапы) для карты заказа в админке.
def store_timeline_for_journey(
    tracking_json: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    shaped = ensure_supplier_tracking_shape(dict(tracking_json or {}))
    timeline = [
        _project_admin_timeline_row(event)
        for event in shaped.get("store_events") or []
        if isinstance(event, dict) and str(event.get("source") or "") == "manual"
    ]
    timeline.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
    return timeline


# Превью ЛК-таймлайна для вкладки «Что видно у клиента» в админке.
def customer_timeline_for_journey(
    order: Order,
    order_events: list[OrderEvent],
    tracking_json: dict[str, Any] | None,
    tracking_updated_at: datetime | None = None,
) -> dict[str, Any]:
    timeline = build_order_timeline(
        order,
        order_events,
        tracking_json,
        "lk",
        tracking_updated_at=tracking_updated_at,
    )
    events: list[dict[str, Any]] = []
    for index, event in enumerate(timeline.get("events") or []):
        at_raw = event.get("at")
        events.append(
            {
                "title": event.get("title"),
                "description": event.get("description"),
                "at": at_raw,
                "at_display": format_iso_datetime_msk_short(at_raw),
                "stage": event.get("stage"),
                "is_current": index == 0,
            }
        )
    return {
        "events": events,
        "current_status": timeline.get("current_status"),
        "current_description": timeline.get("current_description"),
    }


# Создаёт начальное состояние трекинга при передаче в сборку.
def initialize_supplier_tracking(order: Order, now: datetime | None = None) -> None:
    current = now or utc_now_naive()
    raw_tracking = getattr(order, "supplier_tracking_json", None)
    data = ensure_supplier_tracking_shape(
        dict(raw_tracking) if isinstance(raw_tracking, dict) else {}
    )
    store_events = list(data.get("store_events") or [])
    if not any(item.get("stage") == "purchased" for item in store_events):
        at = _iso(current) or ""
        store_events.append(
            {
                "key": _event_key(at, "purchased", "store"),
                "at": at,
                "stage": "purchased",
                "title": STAGE_LABELS["purchased"],
                "description": "Заказ оформлен у поставщика",
                "source": "store",
            }
        )
    data.update(
        {
            "current_stage": data.get("current_stage") or "purchased",
            "store_events": _sort_tracking_events(store_events),
            "supplier_events": list(data.get("supplier_events") or []),
            "carrier_events": list(data.get("carrier_events") or []),
        }
    )
    order.supplier_tracking_json = data
    initialize_supplier_tracking_schedule(order, current)


# Ставит только таймер polling, без legacy blob.
def initialize_supplier_tracking_schedule(
    order: Order, now: datetime | None = None
) -> None:
    current = now or utc_now_naive()
    order.supplier_tracking_sync_state = "waiting"
    order.supplier_tracking_next_check_at = current
    order.supplier_tracking_last_error = None
    order.supplier_tracking_failures = 0


# Вычисляет current_stage по спискам событий (новейший stage по at).
def _compute_current_stage(
    supplier_events: list[dict[str, Any]] | None = None,
    store_events: list[dict[str, Any]] | None = None,
    carrier_events: list[dict[str, Any]] | None = None,
    use_carrier_fallback: bool = False,
) -> str | None:
    if use_carrier_fallback:
        all_events = list(store_events or [])
        if carrier_events:
            all_events.extend(carrier_events)
    else:
        all_events = list(supplier_events or [])
        if store_events:
            all_events.extend(store_events)
    if not all_events:
        return None
    sorted_events = _sort_tracking_events(all_events)
    stage = sorted_events[-1].get("stage")
    return str(stage) if stage else None


# Заменяет supplier_events свежим снимком ParcelLab.
def _merge_supplier_events(
    current: dict[str, Any],
    incoming: dict[str, Any],
    store_events: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    data = ensure_supplier_tracking_shape(current)
    incoming_events = _sort_tracking_events(list(incoming.get("events") or []))
    old_events = list(data.get("supplier_events") or [])
    changed = incoming_events != old_events
    merged = {
        **data,
        "supplier_events": incoming_events,
        "carrier_label": incoming.get("carrier_label") or data.get("carrier_label"),
        "carrier_url": incoming.get("carrier_url") or data.get("carrier_url"),
        "tracking_number": incoming.get("tracking_number")
        or data.get("tracking_number"),
    }
    store = (
        store_events
        if store_events is not None
        else list(data.get("store_events") or [])
    )
    merged["current_stage"] = _compute_current_stage(
        supplier_events=incoming_events,
        store_events=store,
        use_carrier_fallback=False,
    )
    for key in ("carrier_label", "carrier_url", "tracking_number", "current_stage"):
        if data.get(key) != merged.get(key):
            changed = True
    return merged, changed


# Мержит новые DHL-события в carrier_events без дублей.
def _merge_carrier_events(
    current: dict[str, Any],
    incoming: dict[str, Any],
    use_carrier_fallback: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    data = ensure_supplier_tracking_shape(current)
    store_events = list(data.get("store_events") or [])
    supplier_events = list(data.get("supplier_events") or [])
    carrier_events = list(data.get("carrier_events") or [])
    keys = {str(item.get("key")) for item in carrier_events}
    changed = False
    for event in incoming.get("events") or []:
        key = str(event.get("key"))
        if key in keys:
            continue
        carrier_events.append(event)
        keys.add(key)
        changed = True
    before_keys = [str(item.get("key")) for item in carrier_events]
    carrier_events = _sort_tracking_events(carrier_events)
    if [str(item.get("key")) for item in carrier_events] != before_keys:
        changed = True
    if use_carrier_fallback is None:
        fallback = not supplier_events
    else:
        fallback = use_carrier_fallback
    current_stage = _compute_current_stage(
        supplier_events=supplier_events,
        store_events=store_events,
        carrier_events=carrier_events,
        use_carrier_fallback=fallback,
    )
    merged = {
        **data,
        "tracking_number": (
            incoming.get("tracking_number") or data.get("tracking_number")
        ),
        "carrier_label": (
            incoming.get("carrier_label") or data.get("carrier_label") or "DHL"
        ),
        "carrier_source": (
            incoming.get("carrier_source") or data.get("carrier_source") or "dhl"
        ),
        "current_stage": current_stage,
        "store_events": store_events,
        "supplier_events": supplier_events,
        "carrier_events": carrier_events,
    }
    for key in ("tracking_number", "carrier_label", "carrier_source", "current_stage"):
        if data.get(key) != merged.get(key):
            changed = True
    return merged, changed


# True, если в session есть незакоммиченные записи caller'а.
def _session_has_pending_writes(session: AsyncSession) -> bool:
    try:
        return bool(len(session.new) or len(session.dirty) or len(session.deleted))
    except (AttributeError, TypeError):
        return False


# Snapshot TP/CJ расходится со свежим Order/Shipment.
def _tracking_target_changed(
    snapshot_tp: str | None,
    fresh_tp: str | None,
    snapshot_cj: str,
    fresh_cj: str,
) -> bool:
    snap_tp = str(snapshot_tp or "").strip()
    now_tp = str(fresh_tp or "").strip()
    if snap_tp and snap_tp != now_tp:
        return True
    snap_cj = str(snapshot_cj or "").strip()
    now_cj = str(fresh_cj or "").strip()
    return bool(snap_cj and snap_cj != now_cj)


# CJ из ParcelLab payload без ORM.
def _cj_from_parcellab_payload(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return ""
    discovered = discover_from_parcellab_payload(payload)
    if discovered is None or not discovered.tracking_number:
        return ""
    return str(discovered.tracking_number).strip()


class SupplierTrackingService:
    # Сервис синхронизации трекинга поставщика (ParcelLab + DHL).
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        dhl_browser_fetch: DhlBrowserFetchFn | None = None,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._session = session
        self._dhl_browser_fetch = dhl_browser_fetch
        self._session_factory = session_factory

    # Request-path или persist-сессия; None только до bind в sync_order.
    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("DB-сессия не задана")
        return self._session

    # Подставляет persist-сессию на время записи.
    @session.setter
    def session(self, value: AsyncSession | None) -> None:
        self._session = value

    # Snapshot → commit → I/O без txn → persist под FOR UPDATE на свежем Order.
    async def sync_order(self, order_id: int) -> dict[str, Any]:
        now = utc_now_naive()
        factory = self._session_factory
        if factory is not None:
            async with factory() as session:
                snapshot = await self._load_sync_snapshot(session, order_id)
                await self._close_load_transaction(session, owned=True)
            fetches = await self._fetch_sync_payloads(snapshot)
            async with factory() as session:
                result = await self._persist_sync_result(
                    session, snapshot, fetches, now
                )
            return await self._emit_placed_delivered_alerts(result, now)
        session = self._session
        if session is None:
            async with async_session_maker() as owned:
                snapshot = await self._load_sync_snapshot(owned, order_id)
                await self._close_load_transaction(owned, owned=True)
            fetches = await self._fetch_sync_payloads(snapshot)
            async with async_session_maker() as owned:
                result = await self._persist_sync_result(owned, snapshot, fetches, now)
            return await self._emit_placed_delivered_alerts(result, now)
        snapshot = await self._load_sync_snapshot(session, order_id)
        await self._close_load_transaction(session, owned=False)
        fetches = await self._fetch_sync_payloads(snapshot)
        result = await self._persist_sync_result(session, snapshot, fetches, now)
        return await self._emit_placed_delivered_alerts(result, now)

    # Читает идентификаторы для I/O; ORM наружу не отдаёт.
    async def _load_sync_snapshot(
        self, session: AsyncSession, order_id: int
    ) -> _OrderSyncSnapshot:
        crud = CrudOrder(session=session, model=Order)
        order = await crud.get_by_id(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        placed = await crud.list_placed_supplier_orders(order_id)
        if not placed and not order.supplier_order_id:
            raise ValueError("Сначала укажите номер заказа у поставщика")
        targets: list[_PlacedSyncTarget] = []
        for header in placed:
            shipment = await crud.get_shipment_by_supplier_order_id(int(header.id))
            existing_cj = (
                str(shipment.supplier_tracking_number or "").strip()
                if shipment is not None
                else ""
            )
            targets.append(
                _PlacedSyncTarget(
                    supplier_order_id=int(header.id),
                    tp_id=normalize_legacy_supplier_order_id(header.external_id) or "",
                    existing_cj=existing_cj,
                    is_mirror=is_legacy_tracking_mirror(order, header),
                )
            )
        legacy_so = (
            str(order.supplier_order_id).strip() if order.supplier_order_id else ""
        )
        return _OrderSyncSnapshot(
            order_id=int(order.id),
            legacy_supplier_order_id=legacy_so or None,
            legacy_supplier_tracking_id=str(order.supplier_tracking_id or "").strip(),
            placed=tuple(targets),
        )

    # Commit load-txn: owned session всегда; injected — только без чужого dirty state.
    async def _close_load_transaction(self, session: AsyncSession, owned: bool) -> None:
        if owned:
            await session.commit()
            return
        if _session_has_pending_writes(session):
            raise RuntimeError("sync_order не коммитит чужую незакоммиченную session")
        await session.commit()

    # ParcelLab / DHL / browser / Pochta без DB session.
    async def _fetch_sync_payloads(
        self, snapshot: _OrderSyncSnapshot
    ) -> _OrderFetchResult:
        if snapshot.placed:
            placed: list[_PlacedFetchResult] = []
            for target in snapshot.placed:
                placed.append(
                    await self._fetch_placed_target(
                        target, snapshot.legacy_supplier_tracking_id
                    )
                )
            return _OrderFetchResult(placed=tuple(placed), legacy=None)
        if not snapshot.legacy_supplier_order_id:
            raise ValueError("Сначала укажите номер заказа у поставщика")
        legacy = await self._fetch_legacy_target(
            snapshot.legacy_supplier_order_id,
            snapshot.legacy_supplier_tracking_id,
        )
        return _OrderFetchResult(placed=(), legacy=legacy)

    # I/O одного placed SO: ParcelLab, затем DHL/Pochta по CJ.
    async def _fetch_placed_target(
        self, target: _PlacedSyncTarget, legacy_cj: str
    ) -> _PlacedFetchResult:
        if not target.tp_id:
            return _PlacedFetchResult(
                supplier_order_id=target.supplier_order_id,
                parcellab_payload=None,
                parcellab_error=None,
                dhl_payload=None,
                dhl_error=None,
                pochta_payload=None,
                pochta_error=None,
            )
        payload: dict[str, Any] | None = None
        parcellab_error: SupplierTrackingFetchError | None = None
        try:
            payload = await fetch_supplier_tracking(target.tp_id)
        except SupplierTrackingFetchError as exc:
            parcellab_error = exc
            payload = None
        cj = _cj_from_parcellab_payload(payload)
        if not cj:
            cj = target.existing_cj
        if not cj and target.is_mirror:
            cj = legacy_cj
        if not cj:
            return _PlacedFetchResult(
                supplier_order_id=target.supplier_order_id,
                parcellab_payload=payload,
                parcellab_error=parcellab_error,
                dhl_payload=None,
                dhl_error=None,
                pochta_payload=None,
                pochta_error=None,
            )
        dhl_payload, dhl_error = await self._try_fetch_dhl(cj)
        pochta_payload, pochta_error = await self._try_fetch_pochta(cj)
        return _PlacedFetchResult(
            supplier_order_id=target.supplier_order_id,
            parcellab_payload=payload,
            parcellab_error=parcellab_error,
            dhl_payload=dhl_payload,
            dhl_error=dhl_error,
            pochta_payload=pochta_payload,
            pochta_error=pochta_error,
        )

    # I/O legacy-ветки: ParcelLab, затем DHL/Pochta если есть CJ.
    async def _fetch_legacy_target(
        self, supplier_order_id: str, legacy_cj: str
    ) -> _LegacyFetchResult:
        payload: dict[str, Any] | None = None
        parcellab_error: SupplierTrackingFetchError | None = None
        try:
            payload = await fetch_supplier_tracking(supplier_order_id)
        except SupplierTrackingFetchError as exc:
            return _LegacyFetchResult(
                parcellab_payload=None,
                parcellab_error=exc,
                dhl_payload=None,
                dhl_error=None,
                pochta_payload=None,
                pochta_error=None,
            )
        cj = _cj_from_parcellab_payload(payload) or legacy_cj
        if not cj:
            return _LegacyFetchResult(
                parcellab_payload=payload,
                parcellab_error=parcellab_error,
                dhl_payload=None,
                dhl_error=None,
                pochta_payload=None,
                pochta_error=None,
            )
        dhl_payload, dhl_error = await self._try_fetch_dhl(cj)
        pochta_payload, pochta_error = await self._try_fetch_pochta(cj)
        return _LegacyFetchResult(
            parcellab_payload=payload,
            parcellab_error=parcellab_error,
            dhl_payload=dhl_payload,
            dhl_error=dhl_error,
            pochta_payload=pochta_payload,
            pochta_error=pochta_error,
        )

    # HTTP Почты России; ошибки не пробрасывает — как в старом sync.
    async def _try_fetch_pochta(
        self, barcode: str
    ) -> tuple[dict[str, Any] | None, PochtaTrackingFetchError | None]:
        try:
            payload = await fetch_pochta_tracking(
                barcode, proxy_url=settings.POCHTA_TRACKING_PROXY_URL or None
            )
            return payload, None
        except PochtaTrackingFetchError as exc:
            return None, exc

    # Persist: FOR UPDATE на свежем Order, payload с DTO, без объектов session 1.
    async def _persist_sync_result(
        self,
        session: AsyncSession,
        snapshot: _OrderSyncSnapshot,
        fetches: _OrderFetchResult,
        now: datetime,
    ) -> dict[str, Any]:
        crud = CrudOrder(session=session, model=Order)
        order = await crud.get_by_id_for_update(snapshot.order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        prev = self._session
        self._session = session
        try:
            order.supplier_tracking_checked_at = now
            if snapshot.placed:
                return await self._persist_placed_sync(order, snapshot, fetches, now)
            assert fetches.legacy is not None
            return await self._persist_legacy_sync(order, snapshot, fetches.legacy, now)
        finally:
            self._session = prev

    # Пишет placed SO в Shipment на свежем Order.
    async def _persist_placed_sync(
        self,
        order: Order,
        snapshot: _OrderSyncSnapshot,
        fetches: _OrderFetchResult,
        now: datetime,
    ) -> dict[str, Any]:
        shipment_svc = ShipmentService(self.session)
        changed = False
        delay_hours: list[int] = []
        by_id = {item.supplier_order_id: item for item in fetches.placed}
        for target in snapshot.placed:
            result = by_id[target.supplier_order_id]
            so_changed, so_delay = await self._apply_placed_fetch(
                order,
                target,
                result,
                now,
                shipment_svc,
                snapshot.legacy_supplier_tracking_id,
            )
            changed = changed or so_changed
            if so_delay is not None:
                delay_hours.append(so_delay)
        await self._refresh_order_schedule(order, now, delay_hours)
        crud = CrudOrder(session=self.session, model=Order)
        shipments = await crud.list_shipments_for_order(int(order.id))
        delivered_ids = [
            int(row.id)
            for row in shipments
            if str(row.status or "") == ShipmentStatus.DELIVERED
        ]
        await self.session.commit()
        return {
            "status": order.supplier_tracking_sync_state,
            "changed": changed,
            "error": order.supplier_tracking_last_error,
            "delivered_shipment_ids": delivered_ids,
        }

    # Те же правила, что у старого _sync_supplier_order, без HTTP.
    async def _apply_placed_fetch(
        self,
        order: Order,
        target: _PlacedSyncTarget,
        result: _PlacedFetchResult,
        now: datetime,
        shipment_svc: ShipmentService,
        legacy_cj: str,
    ) -> tuple[bool, int | None]:
        row = await shipment_svc.create_from_placed_supplier_order(
            int(order.id), int(target.supplier_order_id), commit=False
        )
        header = await self.session.get(SupplierOrder, int(target.supplier_order_id))
        fresh_tp = (
            normalize_legacy_supplier_order_id(header.external_id) or ""
            if header is not None
            else ""
        )
        fresh_mirror = (
            is_legacy_tracking_mirror(order, header) if header is not None else False
        )
        fresh_cj = str(row.supplier_tracking_number or "").strip()
        if not fresh_cj and fresh_mirror:
            fresh_cj = str(order.supplier_tracking_id or "").strip()
        snapshot_cj = target.existing_cj
        if not snapshot_cj and target.is_mirror:
            snapshot_cj = legacy_cj
        if _tracking_target_changed(
            target.tp_id or None,
            fresh_tp or None,
            snapshot_cj,
            fresh_cj,
        ):
            return False, settings.SUPPLIER_TRACKING_WAIT_HOURS
        if not target.tp_id:
            return False, settings.SUPPLIER_TRACKING_WAIT_HOURS
        changed = False
        delay = settings.SUPPLIER_TRACKING_WAIT_HOURS
        if result.parcellab_error is not None:
            delay = (
                settings.SUPPLIER_TRACKING_BLOCKED_HOURS
                if result.parcellab_error.is_blocked
                else min(
                    24, 4 ** min(int(order.supplier_tracking_failures or 1) - 1, 2)
                )
            )
        elif result.parcellab_payload is not None:
            normalized = normalize_parcellab_body(result.parcellab_payload)
            apply_parcellab_to_shipment(row, normalized, now)
            changed = True
            delay = settings.SUPPLIER_TRACKING_ACTIVE_HOURS
            cj_now = str(row.supplier_tracking_number or "").strip()
            if cj_now:
                await self._maybe_start_delivery(order, tracking_id=cj_now)
        elif not str(row.supplier_tracking_number or "").strip():
            delay = settings.SUPPLIER_TRACKING_WAIT_HOURS

        cj = str(row.supplier_tracking_number or "").strip()
        if not cj and fresh_mirror:
            cj = str(order.supplier_tracking_id or "").strip()
        if not cj:
            return changed, delay

        if result.dhl_payload is not None:
            apply_dhl_to_shipment(row, result.dhl_payload, now)
            changed = True
            delay = settings.SUPPLIER_TRACKING_ACTIVE_HOURS
        elif result.dhl_error is not None:
            delay = (
                settings.SUPPLIER_TRACKING_BLOCKED_HOURS
                if result.dhl_error.is_blocked
                else min(24, 4 ** min(1, 2))
            )

        if result.pochta_error is not None:
            logger.warning(
                "Почта России: не удалось обновить трек %s — %s",
                cj,
                result.pochta_error.message,
            )
            return changed, delay
        if result.pochta_payload is not None:
            apply_pochta_to_shipment(row, result.pochta_payload, now)
            changed = True
        return changed, delay

    # Старый путь: один Order.supplier_order_id, persist на свежей строке.
    async def _persist_legacy_sync(
        self,
        order: Order,
        snapshot: _OrderSyncSnapshot,
        result: _LegacyFetchResult,
        now: datetime,
    ) -> dict[str, Any]:
        fresh_tp = str(order.supplier_order_id or "").strip() or None
        fresh_cj = str(order.supplier_tracking_id or "").strip()
        if _tracking_target_changed(
            snapshot.legacy_supplier_order_id,
            fresh_tp,
            snapshot.legacy_supplier_tracking_id,
            fresh_cj,
        ):
            await sync_delivered_alert_after_tracking_check(self.session, order, now)
            await self.session.commit()
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": False,
                "error": None,
            }
        if result.parcellab_error is not None:
            return await self._handle_fetch_error(
                order,
                now,
                result.parcellab_error.msg,
                result.parcellab_error.is_blocked,
            )

        changed = False
        if result.parcellab_payload is not None:
            pl_changed = self._apply_parcellab_payload(
                order, result.parcellab_payload, now
            )
            changed = changed or pl_changed
            await self._maybe_start_delivery(order)
        elif not order.supplier_tracking_id:
            order.supplier_tracking_last_error = None
            order.supplier_tracking_failures = 0
            order.supplier_tracking_sync_state = "waiting"
            order.supplier_tracking_next_check_at = now + timedelta(
                hours=settings.SUPPLIER_TRACKING_WAIT_HOURS
            )
            await sync_delivered_alert_after_tracking_check(self.session, order, now)
            await self.session.commit()
            return {"status": "waiting", "changed": False, "error": None}

        if order.supplier_tracking_id:
            dhl_result = self._apply_dhl_fetch(order, now, result)
            changed = changed or dhl_result["changed"]
            pochta_result = self._apply_russian_post_fetch(order, now, result)
            changed = changed or pochta_result["changed"]
            if dhl_result.get("error"):
                await sync_delivered_alert_after_tracking_check(
                    self.session, order, now
                )
                await self.session.commit()
                return dhl_result
            order.supplier_tracking_last_error = None
            order.supplier_tracking_failures = 0
            await sync_delivered_alert_after_tracking_check(self.session, order, now)
            await self.session.commit()
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": changed,
                "error": None,
            }

        order.supplier_tracking_last_error = None
        order.supplier_tracking_failures = 0
        order.supplier_tracking_sync_state = "waiting"
        order.supplier_tracking_next_check_at = now + timedelta(
            hours=settings.SUPPLIER_TRACKING_WAIT_HOURS
        )
        if changed:
            order.supplier_tracking_updated_at = now
        await sync_delivered_alert_after_tracking_check(self.session, order, now)
        await self.session.commit()
        return {
            "status": order.supplier_tracking_sync_state,
            "changed": changed,
            "error": None,
        }

    # Пишет DHL snapshot в Order; HTTP уже выполнен.
    def _apply_dhl_fetch(
        self, order: Order, now: datetime, result: _LegacyFetchResult
    ) -> dict[str, Any]:
        piececode = str(order.supplier_tracking_id or "").strip()
        if not piececode:
            order.supplier_tracking_sync_state = "waiting"
            order.supplier_tracking_next_check_at = now + timedelta(
                hours=settings.SUPPLIER_TRACKING_WAIT_HOURS
            )
            return {"status": "waiting", "changed": False, "error": None}
        if result.dhl_error is not None:
            hours = self._record_dhl_error(order, now, result.dhl_error)
            order.supplier_tracking_next_check_at = now + timedelta(hours=hours)
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": False,
                "error": result.dhl_error.message,
            }
        if result.dhl_payload is None:
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": False,
                "error": None,
            }
        changed = self._apply_dhl_normalized(order, result.dhl_payload, now)
        is_delivered = result.dhl_payload.get("current_stage") == "delivered"
        order.supplier_tracking_next_check_at = (
            None
            if is_delivered
            else now + timedelta(hours=settings.SUPPLIER_TRACKING_ACTIVE_HOURS)
        )
        return {
            "status": order.supplier_tracking_sync_state,
            "changed": changed,
            "error": None,
        }

    # Пишет russian_post_events; HTTP уже выполнен.
    def _apply_russian_post_fetch(
        self, order: Order, now: datetime, result: _LegacyFetchResult
    ) -> dict[str, Any]:
        barcode = str(order.supplier_tracking_id or "").strip()
        if not barcode:
            return {"status": "waiting", "changed": False, "error": None}
        if result.pochta_error is not None:
            data = ensure_supplier_tracking_shape(
                dict(order.supplier_tracking_json or {})
            )
            data["russian_post_last_error"] = result.pochta_error.message
            order.supplier_tracking_json = data
            logger.warning(
                "Почта России: не удалось обновить трек %s — %s",
                barcode,
                result.pochta_error.message,
            )
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": True,
                "error": result.pochta_error.message,
            }
        if result.pochta_payload is None:
            return {
                "status": order.supplier_tracking_sync_state,
                "changed": False,
                "error": None,
            }
        merged, changed = _merge_russian_post_events(
            dict(order.supplier_tracking_json or {}),
            result.pochta_payload,
        )
        order.supplier_tracking_json = merged
        if changed:
            order.supplier_tracking_updated_at = now
        return {
            "status": order.supplier_tracking_sync_state,
            "changed": changed,
            "error": None,
        }

    # После persist: TG на каждую delivered посылку, без persist-session.
    # Auto-complete сюда не ставить: сначала алерты (status ещё delivery),
    # потом тот же OrderService.finalize_order_delivery, что вызывает admin.
    async def _emit_placed_delivered_alerts(
        self, result: dict[str, Any], now: datetime
    ) -> dict[str, Any]:
        ids = [
            int(shipment_id)
            for shipment_id in (result.pop("delivered_shipment_ids", None) or [])
        ]
        for shipment_id in ids:
            await sync_shipment_delivered_alert(shipment_id, now)
        return result

    # Ставит next_check_at по недоставленным Shipment, не по одному delivered.
    async def _refresh_order_schedule(
        self, order: Order, now: datetime, delay_hours: list[int]
    ) -> None:
        crud = CrudOrder(session=self.session, model=Order)
        shipments = await crud.list_shipments_for_order(int(order.id))
        # Пустой список ≠ all_shipments_delivered; poll всё равно стопаем как раньше.
        # Auto-complete отсюда не вызывать.
        if all_shipments_delivered(shipments) or not shipments:
            order.supplier_tracking_next_check_at = None
            order.supplier_tracking_sync_state = "delivered"
            return
        hours = (
            min(delay_hours) if delay_hours else settings.SUPPLIER_TRACKING_ACTIVE_HOURS
        )
        order.supplier_tracking_next_check_at = now + timedelta(hours=hours)
        if str(order.supplier_tracking_sync_state or "") == "delivered":
            order.supplier_tracking_sync_state = "active"

    # HTTP DHL + proxy + browser fallback; не пишет Order/Shipment.
    async def _try_fetch_dhl(
        self, piececode: str
    ) -> tuple[dict[str, Any] | None, DhlTrackingFetchError | None]:
        dhl_error: DhlTrackingFetchError | None = None
        try:
            normalized = await fetch_dhl_tracking(
                piececode,
                proxy_url=settings.DHL_TRACKING_PROXY_URL or None,
            )
            return normalized, None
        except DhlTrackingFetchError as exc:
            dhl_error = exc
        if (
            dhl_error is not None
            and dhl_error.is_blocked
            and settings.DHL_TRACKING_USE_BROWSER
            and self._dhl_browser_fetch is not None
        ):
            try:
                normalized = await self._dhl_browser_fetch(piececode)
                return normalized, None
            except DhlTrackingFetchError as exc:
                return None, exc
            except Exception:
                return None, DhlTrackingFetchError(
                    "blocked",
                    "DHL заблокировал проверку (browser fallback не удался)",
                    True,
                )
        return None, dhl_error

    # Пишет DHL snapshot в Order json без next_check_at.
    def _apply_dhl_normalized(
        self, order: Order, normalized: dict[str, Any], now: datetime
    ) -> bool:
        data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json or {}))
        supplier_events = list(data.get("supplier_events") or [])
        merged, changed = _merge_carrier_events(
            dict(order.supplier_tracking_json or {}),
            normalized,
            use_carrier_fallback=_supplier_events_stale(
                supplier_events, order.supplier_tracking_updated_at, now
            ),
        )
        order.supplier_tracking_json = merged
        is_delivered = normalized.get("current_stage") == "delivered"
        order.supplier_tracking_sync_state = "delivered" if is_delivered else "active"
        if changed:
            order.supplier_tracking_updated_at = now
        return changed

    # Пишет backoff DHL в Order; возвращает hours до следующей проверки.
    def _record_dhl_error(
        self, order: Order, now: datetime, dhl_error: DhlTrackingFetchError
    ) -> int:
        failures = int(order.supplier_tracking_failures or 0) + 1
        order.supplier_tracking_failures = failures
        order.supplier_tracking_last_error = dhl_error.message
        order.supplier_tracking_sync_state = (
            "blocked" if dhl_error.is_blocked else "waiting"
        )
        hours = (
            settings.SUPPLIER_TRACKING_BLOCKED_HOURS
            if dhl_error.is_blocked
            else min(24, 4 ** min(failures - 1, 2))
        )
        return hours

    # Пишет backoff ParcelLab в Order без commit.
    def _record_fetch_error(
        self, order: Order, now: datetime, message: str, is_blocked: bool
    ) -> int:
        failures = int(order.supplier_tracking_failures or 0) + 1
        order.supplier_tracking_failures = failures
        order.supplier_tracking_last_error = message
        order.supplier_tracking_sync_state = "blocked" if is_blocked else "waiting"
        hours = (
            settings.SUPPLIER_TRACKING_BLOCKED_HOURS
            if is_blocked
            else min(24, 4 ** min(failures - 1, 2))
        )
        return hours

    # Пишет supplier_events и CJ из ParcelLab payload.
    def _apply_parcellab_payload(
        self, order: Order, payload: dict[str, Any], now: datetime
    ) -> bool:
        normalized = normalize_parcellab_body(payload)
        data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json or {}))
        store_events = list(data.get("store_events") or [])
        merged, changed = _merge_supplier_events(data, normalized, store_events)
        discovered = discover_from_parcellab_payload(payload)
        if discovered and discovered.tracking_number:
            if not order.supplier_tracking_id:
                order.supplier_tracking_id = discovered.tracking_number
            merged["tracking_number"] = discovered.tracking_number
            if discovered.carrier_label:
                merged["carrier_label"] = discovered.carrier_label
            if discovered.carrier_url:
                merged["carrier_url"] = discovered.carrier_url
        order.supplier_tracking_json = merged
        if changed or normalized.get("events"):
            order.supplier_tracking_updated_at = now
            order.supplier_tracking_sync_state = "active"
            order.supplier_tracking_next_check_at = now + timedelta(
                hours=settings.SUPPLIER_TRACKING_ACTIVE_HOURS
            )
        return changed

    # Записывает backoff после ошибки ParcelLab/DHL.
    async def _handle_fetch_error(
        self,
        order: Order,
        now: datetime,
        message: str,
        is_blocked: bool,
    ) -> dict[str, Any]:
        hours = self._record_fetch_error(order, now, message, is_blocked)
        order.supplier_tracking_next_check_at = now + timedelta(hours=hours)
        await sync_delivered_alert_after_tracking_check(self.session, order, now)
        await self.session.commit()
        return {
            "status": order.supplier_tracking_sync_state,
            "changed": False,
            "error": message,
        }

    # Переводит заказ в delivery при появлении CJ на Shipment или legacy Order.
    async def _maybe_start_delivery(
        self, order: Order, tracking_id: str | None = None
    ) -> None:
        if order.status != OrderStatus.ASSEMBLING:
            return
        cj = str(tracking_id or order.supplier_tracking_id or "").strip() or None
        self.session.add(
            OrderEvent(
                order_id=order.id,
                event_type="delivery_started",
                event_message="Трек поставщика получен автоматически",
                created_by="system",
                payload_json={
                    "before": OrderStatus.ASSEMBLING,
                    "after": OrderStatus.DELIVERY,
                    "supplier_tracking_id": cj,
                },
            )
        )
        order.status = OrderStatus.DELIVERY

    # Добавляет ручной этап в store_events (fallback для админа).
    async def add_manual_event(
        self,
        order_id: int,
        stage: str,
        description: str | None = None,
    ) -> None:
        if stage not in MANUAL_STAGES:
            raise ValueError("Неизвестный этап доставки")
        order = await self.session.get(Order, order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        if str(order.status or "").lower() == OrderStatus.COMPLETED:
            raise ValueError("Заказ выполнен — изменения доставки недоступны")
        now = utc_now_naive()
        data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json or {}))
        store_events = list(data.get("store_events") or [])
        at = _iso(now) or ""
        store_events.append(
            {
                "key": _event_key(at, stage, "manual"),
                "at": at,
                "stage": stage,
                "title": STAGE_LABELS[stage],
                "description": description or None,
                "source": "manual",
            }
        )
        supplier_events = list(data.get("supplier_events") or [])
        carrier_events = list(data.get("carrier_events") or [])
        use_carrier_fallback = _supplier_events_stale(
            supplier_events, order.supplier_tracking_updated_at, now
        )
        current_stage = _compute_current_stage(
            supplier_events=supplier_events,
            store_events=store_events,
            carrier_events=carrier_events,
            use_carrier_fallback=use_carrier_fallback,
        )
        data.update(
            {
                "current_stage": current_stage,
                "store_events": _sort_tracking_events(store_events),
            }
        )
        order.supplier_tracking_json = data
        order.supplier_tracking_updated_at = now
        if stage == "delivered":
            order.supplier_tracking_sync_state = "delivered"
            order.supplier_tracking_next_check_at = None
        if order.status == OrderStatus.ASSEMBLING and stage in {
            "dispatched",
            "in_transit",
            "destination",
            "last_mile",
        }:
            order.status = OrderStatus.DELIVERY
        await self.session.commit()

    # Обновляет supplier_events из ParcelLab (то же, что sync).
    async def compare_parcellab(self, order_id: int) -> dict[str, Any]:
        order = await self.session.get(Order, order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        if str(order.status or "").lower() == OrderStatus.COMPLETED:
            raise ValueError("Заказ выполнен — изменения доставки недоступны")
        if not order.supplier_order_id:
            raise ValueError("Сначала укажите номер заказа у поставщика")
        now = utc_now_naive()
        try:
            payload = await fetch_supplier_tracking(order.supplier_order_id)
        except SupplierTrackingFetchError as exc:
            raise ValueError(exc.msg) from exc
        if payload is None:
            raise ValueError("ParcelLab не вернул данные по заказу")
        self._apply_parcellab_payload(order, payload, now)
        await self._maybe_start_delivery(order)
        await sync_delivered_alert_after_tracking_check(self.session, order, now)
        await self.session.commit()
        return build_parcellab_admin_snapshot(payload, _iso(now) or "")

    # Публичная проекция трекинга для ЛК клиента.
    async def public_tracking(
        self,
        order_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> SupplierTrackingPublicSchema:
        order = await self.session.get(Order, order_id)
        if order is None or order.user_id != user_id:
            raise ValueError("Заказ не найден")
        order_events = list(
            await self.session.scalars(
                select(OrderEvent)
                .where(OrderEvent.order_id == order_id)
                .order_by(OrderEvent.created_at.asc())
            )
        )
        data = ensure_supplier_tracking_shape(dict(order.supplier_tracking_json or {}))
        timeline = build_order_timeline(
            order,
            order_events,
            data,
            "lk",
            tracking_updated_at=order.supplier_tracking_updated_at,
            now=now,
        )
        return SupplierTrackingPublicSchema(
            available=bool(timeline["events"]),
            current_status=timeline.get("current_status"),
            current_description=timeline.get("current_description"),
            current_stage=timeline["current_stage"],
            carrier_label=timeline.get("carrier_label"),
            last_updated_at=order.supplier_tracking_updated_at,
            events=timeline["events"],
        )
