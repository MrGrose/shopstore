import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.client_texts import CUSTOMER_SHIPMENT_DELIVERED_DRAFT
from src.models.notification_outbox import NotificationOutboxStatus
from src.models.order import (
    Order,
    OrderItem,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.schemas.order import (
    OrderShipmentItemSchema,
    OrderShipmentSchema,
    OrderShipmentTrackingLinkSchema,
    OrderShipmentTrackingSchema,
)
from src.services.notifications.customer_notification_keys import (
    shipment_delivered_notify_key,
)
from src.services.orders.pochta_tracking import build_pochta_public_tracking_url
from src.services.orders.supplier_orders import normalize_legacy_supplier_order_id
from src.utils.datetime_fmt import format_datetime_msk_short, utc_now_naive
from src.utils.labels import display_product_title, translate_option_value


class ShipmentError(ValueError):
    pass


@dataclass(frozen=True)
class ShipmentView:
    id: int
    order_id: int
    supplier_order_id: int | None
    status: str
    supplier_carrier: str | None
    supplier_tracking_number: str | None
    supplier_tracking_url: str | None
    customer_carrier: str | None
    customer_tracking_number: str | None
    customer_tracking_url: str | None
    status_updated_at: datetime | None
    delivered_at: datetime | None
    delivered_alert: dict | None
    completed_at: datetime | None


@dataclass(frozen=True)
class ShipmentBackfillStats:
    scanned_placed: int
    created: int
    skipped_existing: int
    skipped_missing_so: int


_STAGE_TOKEN_RE = re.compile(r"[^a-z0-9]")
_DELIVERED_TOKENS = frozenset({"delivered", "deliverydelivered"})
_IN_TRANSIT_TOKENS = frozenset(
    {
        "intransit",
        "in_transit",
        "dispatched",
        "bordercrossing",
        "border_crossing",
        "destination",
        "outfordelivery",
        "out_for_delivery",
        "lastmile",
        "last_mile",
        "deliveryisbeingprepared",
        "delivery_is_being_prepared",
    }
)
_PREPARING_TOKENS = frozenset(
    {
        "preparing",
        "purchased",
        "created",
        "pickupscheduled",
        "pick_up_scheduled",
        "pickup",
        "orderprocessed",
        "scheduledforcollection",
        "labelcreated",
    }
)
_UNKNOWN_TOKENS = frozenset(
    {
        "exception",
        "failed",
        "returned",
        "returntosender",
        "unknown",
        "problem",
    }
)
_STATUS_RANK: dict[str, int] = {
    str(ShipmentStatus.PREPARING): 1,
    str(ShipmentStatus.IN_TRANSIT): 2,
    str(ShipmentStatus.DELIVERED): 3,
}


# Проверяет, что SO placed и принадлежит этому Order.
def validate_placed_source(order_id: int, header: SupplierOrder) -> None:
    if int(header.order_id) != int(order_id):
        raise ShipmentError("Заказ поставщика принадлежит другому заказу")
    if str(header.status or "") != SupplierOrderStatus.PLACED:
        raise ShipmentError(
            "Посылку можно создать только для оформленного заказа поставщика"
        )


# True если SO.external_id — тот же TP, что Order.supplier_order_id.
def is_legacy_tracking_mirror(order: Order, header: SupplierOrder) -> bool:
    order_tp = normalize_legacy_supplier_order_id(order.supplier_order_id)
    so_tp = normalize_legacy_supplier_order_id(header.external_id)
    return bool(order_tp and so_tp and order_tp == so_tp)


# CJ с Order только если это зеркало первого TP; URL в 3E-A не строим.
def legacy_supplier_tracking_number(order: Order, header: SupplierOrder) -> str | None:
    if not is_legacy_tracking_mirror(order, header):
        return None
    tracking = str(order.supplier_tracking_id or "").strip()
    return tracking or None


# Нормализует внешний/внутренний stage в token без разделителей.
def _stage_token(stage: str) -> str:
    return _STAGE_TOKEN_RE.sub("", stage.lower())


# Готовит preparing/in_transit/delivered или None, если нельзя классифицировать.
def shipment_status_from_stage(stage: str | None) -> str | None:
    if not stage:
        return None
    raw = str(stage).strip()
    if not raw:
        return None
    token = _stage_token(raw)
    lowered = raw.lower().replace("-", "_").replace(" ", "_")
    if token in _DELIVERED_TOKENS or lowered in _DELIVERED_TOKENS:
        return ShipmentStatus.DELIVERED
    if token in _IN_TRANSIT_TOKENS or lowered in _IN_TRANSIT_TOKENS:
        return ShipmentStatus.IN_TRANSIT
    if token in _PREPARING_TOKENS or lowered in _PREPARING_TOKENS:
        return ShipmentStatus.PREPARING
    if token in _UNKNOWN_TOKENS or lowered in _UNKNOWN_TOKENS:
        return None
    return None


# Двигает Shipment.status только вперёд; unknown не затирает текущий.
def apply_shipment_status(row: Shipment, new_status: str | None, now: datetime) -> bool:
    if new_status is None:
        return False
    current = str(row.status or ShipmentStatus.PREPARING)
    if current == ShipmentStatus.DELIVERED:
        return False
    new_rank = _STATUS_RANK.get(new_status)
    old_rank = _STATUS_RANK.get(current, 0)
    if new_rank is None or new_rank < old_rank:
        return False
    if new_status == current:
        return False
    row.status = new_status
    row.status_updated_at = now
    if new_status == ShipmentStatus.DELIVERED and row.delivered_at is None:
        row.delivered_at = now
    return True


# Admin fulfillment; повтор — no-op. Не трогает status / delivered_at / A.
def mark_shipment_completed(row: Shipment, now: datetime) -> bool:
    if getattr(row, "completed_at", None) is not None:
        return False
    row.completed_at = now
    return True


SHIPMENT_CUSTOMER_MESSAGE_TEMPLATE = CUSTOMER_SHIPMENT_DELIVERED_DRAFT

# Payload order_status для B: не текущий статус заказа (delivery = «В пути»).
SHIPMENT_CUSTOMER_NOTIFY_ORDER_STATUS = "shipment_delivered"


# Tracking delivered или admin completed — можно слать customer B.
def shipment_can_notify_customer(row: object) -> bool:
    status = str(getattr(row, "status", "") or "")
    if status == str(ShipmentStatus.DELIVERED):
        return True
    return getattr(row, "completed_at", None) is not None


# Status из outbox: ключ, :telegram и :email.
def outbox_status_for_customer_key(
    outbox_by_key: Mapping[str, str],
    key: str,
) -> str | None:
    statuses: list[str] = []
    for candidate in (key, f"{key}:telegram", f"{key}:email"):
        status = outbox_by_key.get(candidate)
        if status:
            statuses.append(str(status))
    if not statuses:
        return None
    if NotificationOutboxStatus.SENT in statuses:
        return NotificationOutboxStatus.SENT
    if any(
        status
        in {
            NotificationOutboxStatus.PENDING,
            NotificationOutboxStatus.PROCESSING,
        }
        for status in statuses
    ):
        return NotificationOutboxStatus.PENDING
    if NotificationOutboxStatus.FAILED in statuses:
        return NotificationOutboxStatus.FAILED
    return statuses[0]


# Подпись B на карточке по outbox status.
def customer_notify_label_for_outbox(status: str | None) -> str:
    if status == NotificationOutboxStatus.SENT:
        return SHIPMENT_TELEGRAM_SENT_MARK
    if status in {
        NotificationOutboxStatus.PENDING,
        NotificationOutboxStatus.PROCESSING,
    }:
        return "⟳ В очереди"
    if status == NotificationOutboxStatus.FAILED:
        return "⚠ Ошибка"
    return SHIPMENT_TELEGRAM_IDLE_MARK


# Подставляет order_id/seq/cj в черновик B.
def render_shipment_customer_message(
    template: str | None,
    order_id: int,
    seq: int,
    cj: str | None,
) -> str:
    raw = (template or "").strip() or SHIPMENT_CUSTOMER_MESSAGE_TEMPLATE
    cj_text = str(cj or "").strip()
    text = (
        raw.replace("{order_id}", str(order_id))
        .replace("{seq}", str(seq))
        .replace("{cj}", cj_text)
    )
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


# Если несколько посылок и нет плейсхолдеров — добавить номер и CJ.
def ensure_shipment_identity_in_message(
    rendered: str,
    template: str | None,
    seq: int,
    cj: str | None,
) -> str:
    source = template or ""
    if "{seq}" in source or "{cj}" in source:
        return rendered
    extra = f"Посылка №{seq}"
    cj_text = str(cj or "").strip()
    if cj_text:
        extra = f"{extra} · {cj_text}"
    if extra in rendered:
        return rendered
    return f"{rendered}\n\n{extra}".strip()


# Пишет ParcelLab CJ/URL/carrier и нормализованный status в Shipment.
def apply_parcellab_to_shipment(row: Shipment, normalized: dict, now: datetime) -> None:
    tracking = str(normalized.get("tracking_number") or "").strip()
    if tracking:
        row.supplier_tracking_number = tracking
    url = str(normalized.get("carrier_url") or "").strip()
    if url:
        row.supplier_tracking_url = url
    label = str(normalized.get("carrier_label") or "").strip()
    if label:
        row.supplier_carrier = label
    apply_shipment_status(
        row, shipment_status_from_stage(str(normalized.get("current_stage") or "")), now
    )


# Пишет DHL номер в customer_* и двигает status; URL DHL не строим.
def apply_dhl_to_shipment(row: Shipment, normalized: dict, now: datetime) -> None:
    tracking = str(normalized.get("tracking_number") or "").strip()
    if tracking:
        row.customer_tracking_number = tracking
    apply_shipment_status(
        row, shipment_status_from_stage(str(normalized.get("current_stage") or "")), now
    )


# Пишет Почту России в customer_* и двигает status.
def apply_pochta_to_shipment(row: Shipment, normalized: dict, now: datetime) -> None:
    tracking = str(normalized.get("tracking_number") or "").strip()
    if tracking:
        row.customer_tracking_number = tracking
    url = str(normalized.get("carrier_url") or "").strip()
    if url:
        row.customer_tracking_url = url
    row.customer_carrier = "Почта России"
    apply_shipment_status(
        row, shipment_status_from_stage(str(normalized.get("current_stage") or "")), now
    )


# Проекция Shipment для read-контракта 3E-A.
def shipment_view(row: Shipment) -> ShipmentView:
    return ShipmentView(
        id=int(row.id),
        order_id=int(row.order_id),
        supplier_order_id=(
            int(row.supplier_order_id) if row.supplier_order_id is not None else None
        ),
        status=str(row.status or ""),
        supplier_carrier=row.supplier_carrier,
        supplier_tracking_number=row.supplier_tracking_number,
        supplier_tracking_url=row.supplier_tracking_url,
        customer_carrier=row.customer_carrier,
        customer_tracking_number=row.customer_tracking_number,
        customer_tracking_url=row.customer_tracking_url,
        status_updated_at=row.status_updated_at,
        delivered_at=row.delivered_at,
        delivered_alert=(
            dict(row.delivered_alert) if isinstance(row.delivered_alert, dict) else None
        ),
        completed_at=row.completed_at,
    )


SHIPMENT_CUSTOMER_STATUS_LABELS = {
    str(ShipmentStatus.PREPARING): "Готовится",
    str(ShipmentStatus.IN_TRANSIT): "В пути",
    str(ShipmentStatus.DELIVERED): "Доставлена",
}


@dataclass(frozen=True)
class AdminShipmentCard:
    seq: int
    tp_id: str | None
    status: str
    status_label: str
    supplier_tracking_number: str | None
    supplier_carrier: str | None
    supplier_tracking_url: str | None
    customer_carrier: str | None
    customer_tracking_number: str | None
    customer_tracking_url: str | None

    dhl_tracking_url: str | None
    pochta_tracking_url: str | None
    delivered_at_display: str | None
    last_check_display: str | None
    telegram_label: str | None
    id: int
    completed_at_display: str | None
    is_completed: bool
    can_complete: bool
    completion_label: str
    can_notify: bool
    customer_notify_label: str
    customer_notify_draft: str


SHIPMENT_TELEGRAM_SENT_MARK = "✔✔"
SHIPMENT_TELEGRAM_IDLE_MARK = "—"


# Индикатор A на карточке: только delivered или pending retry.
def _shipment_telegram_label(alert: object, status: str) -> str | None:
    state = dict(alert) if isinstance(alert, dict) else {}
    pending = bool(state.get("pending_retry"))
    sent = bool(state.get("message_id"))
    if str(status) != ShipmentStatus.DELIVERED and not pending:
        return None
    if pending:
        return "⟳ Повтор"
    if sent:
        return SHIPMENT_TELEGRAM_SENT_MARK
    return SHIPMENT_TELEGRAM_IDLE_MARK


# Карточки admin delivery: TP с SO, CJ/status/carrier с Shipment.
def build_admin_shipment_cards(
    rows: Sequence[ShipmentView],
    supplier_orders: Sequence[object],
) -> list[AdminShipmentCard]:
    so_by_id: dict[int, object] = {}
    for so in supplier_orders:
        raw_id = getattr(so, "id", None)
        if raw_id is None:
            continue
        so_by_id[int(raw_id)] = so
    cards: list[AdminShipmentCard] = []
    for index, row in enumerate(rows, start=1):
        so_id = (
            int(row.supplier_order_id) if row.supplier_order_id is not None else None
        )
        so = so_by_id.get(so_id) if so_id is not None else None
        seq = int(getattr(so, "seq", 0) or 0) or index
        status = str(row.status or "")
        tp = str(getattr(so, "external_id", None) or "").strip() or None
        supplier_cj = str(row.supplier_tracking_number or "").strip() or None
        customer_number = str(row.customer_tracking_number or "").strip() or None
        link_cj = supplier_cj or customer_number
        tracking_links = customer_tracking_links_for_cj(link_cj) if link_cj else []
        dhl_tracking_url = tracking_links[0].url if len(tracking_links) > 0 else None
        pochta_tracking_url = tracking_links[1].url if len(tracking_links) > 1 else None
        completed_at = getattr(row, "completed_at", None)
        is_completed = completed_at is not None
        cards.append(
            AdminShipmentCard(
                seq=seq,
                tp_id=tp,
                status=status,
                status_label=SHIPMENT_CUSTOMER_STATUS_LABELS.get(status, status),
                supplier_tracking_number=supplier_cj,
                supplier_carrier=str(row.supplier_carrier or "").strip() or None,
                supplier_tracking_url=str(row.supplier_tracking_url or "").strip()
                or None,
                customer_carrier=str(row.customer_carrier or "").strip() or None,
                customer_tracking_number=customer_number,
                customer_tracking_url=str(row.customer_tracking_url or "").strip()
                or None,
                dhl_tracking_url=dhl_tracking_url,
                pochta_tracking_url=pochta_tracking_url,
                delivered_at_display=format_datetime_msk_short(
                    getattr(row, "delivered_at", None)
                ),
                last_check_display=format_datetime_msk_short(
                    getattr(row, "status_updated_at", None)
                ),
                telegram_label=_shipment_telegram_label(
                    getattr(row, "delivered_alert", None), status
                ),
                id=int(getattr(row, "id", 0) or 0),
                completed_at_display=format_datetime_msk_short(completed_at),
                is_completed=is_completed,
                can_complete=(
                    status == str(ShipmentStatus.DELIVERED) and not is_completed
                ),
                completion_label="Завершена" if is_completed else "Не завершена",
                can_notify=shipment_can_notify_customer(row),
                customer_notify_label=SHIPMENT_TELEGRAM_IDLE_MARK,
                customer_notify_draft=render_shipment_customer_message(
                    None,
                    int(getattr(row, "order_id", 0) or 0),
                    seq,
                    supplier_cj,
                ),
            )
        )
    cards.sort(key=lambda item: item.seq)
    return cards


# True если есть хотя бы одна посылка и все в terminal delivered.
# Пустой список — False: auto-complete на заказ без Shipment не должен срабатывать.
def all_shipments_delivered(shipments: Sequence[object]) -> bool:
    rows = list(shipments)
    if not rows:
        return False
    return all(
        str(getattr(row, "status", "") or "") == ShipmentStatus.DELIVERED
        for row in rows
    )


# True если есть хотя бы одна посылка и все с admin completed_at.
# Пустой список — False; tracking delivered сюда не входит.
def all_shipments_completed(shipments: Sequence[object]) -> bool:
    rows = list(shipments)
    if not rows:
        return False
    return all(getattr(row, "completed_at", None) is not None for row in rows)


# Сводка статусов для rail / delivery header.
def admin_shipment_status_counts(
    cards: Sequence[AdminShipmentCard],
) -> dict[str, int]:
    counts = {
        str(ShipmentStatus.PREPARING): 0,
        str(ShipmentStatus.IN_TRANSIT): 0,
        str(ShipmentStatus.DELIVERED): 0,
    }
    for card in cards:
        if card.status in counts:
            counts[card.status] += 1
    return counts


# Компактная пара TP/CJ для блока «Поставщик» в карточке заказа.
@dataclass(frozen=True)
class AdminSupplierParcel:
    seq: int
    tp_id: str
    supplier_tracking_number: str | None
    awaiting_tracking: bool


# Пустую строку и None схлопывает в None.
def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


# TP только у placed SO с непустым external_id.
def _placed_tp_id(so: object) -> str | None:
    if str(getattr(so, "status", "") or "") != SupplierOrderStatus.PLACED:
        return None
    return _text_or_none(getattr(so, "external_id", None))


# TP для одной строки списка: placed SO, иначе legacy Order.supplier_order_id.
def admin_list_tp_ids(
    supplier_orders: Sequence[object],
    legacy_tp: str | None,
) -> list[str]:
    tps = [tp for tp in (_placed_tp_id(so) for so in supplier_orders) if tp]
    if tps:
        return tps
    fallback = _text_or_none(legacy_tp)
    return [fallback] if fallback else []


# TP по order_id для колонки списка; покрывает каждый заказ страницы.
def build_admin_list_tp_by_order_id(
    supplier_orders: Sequence[object],
    orders: Sequence[object],
) -> dict[int, list[str]]:
    by_order: dict[int, list[object]] = {}
    for so in supplier_orders:
        raw_id = getattr(so, "order_id", None)
        if raw_id is None:
            continue
        by_order.setdefault(int(raw_id), []).append(so)
    result: dict[int, list[str]] = {}
    for order in orders:
        order_id = int(getattr(order, "id"))
        result[order_id] = admin_list_tp_ids(
            by_order.get(order_id, []),
            getattr(order, "supplier_order_id", None),
        )
    return result


# Пары TP/CJ по seq: SO.external_id + Shipment.supplier_tracking_number, иначе legacy.
def build_admin_supplier_parcels(
    supplier_orders: Sequence[object],
    shipments: Sequence[object],
    legacy_tp: str | None = None,
    legacy_cj: str | None = None,
) -> list[AdminSupplierParcel]:
    ship_by_so: dict[int, object] = {}
    for row in shipments:
        so_id = getattr(row, "supplier_order_id", None)
        if so_id is None:
            continue
        ship_by_so[int(so_id)] = row
    parcels: list[AdminSupplierParcel] = []
    shown = 0
    for so in supplier_orders:
        tp = _placed_tp_id(so)
        if tp is None:
            continue
        shown += 1
        seq = int(getattr(so, "seq", 0) or 0) or shown
        row = ship_by_so.get(int(getattr(so, "id")))
        cj = (
            _text_or_none(getattr(row, "supplier_tracking_number", None))
            if row is not None
            else None
        )
        parcels.append(
            AdminSupplierParcel(
                seq=seq,
                tp_id=tp,
                supplier_tracking_number=cj,
                awaiting_tracking=cj is None,
            )
        )
    if parcels:
        return parcels
    tp = _text_or_none(legacy_tp)
    cj = _text_or_none(legacy_cj)
    if tp is None and cj is None:
        return []
    return [
        AdminSupplierParcel(
            seq=1,
            tp_id=tp or "—",
            supplier_tracking_number=cj,
            awaiting_tracking=False,
        )
    ]


# Короткая подпись очереди Delivery.
def admin_shipment_summary(cards: Sequence[AdminShipmentCard]) -> str | None:
    if not cards:
        return None
    if all_shipments_delivered(cards):
        return "Все посылки доставлены"
    delivered = admin_shipment_status_counts(cards)[str(ShipmentStatus.DELIVERED)]
    return f"{delivered} / {len(cards)} доставлены"


# Admin fulfillment progress; не tracking delivered.
def admin_shipment_completion_summary(
    cards: Sequence[AdminShipmentCard],
) -> str | None:
    if not cards:
        return None
    done = sum(1 for card in cards if card.is_completed)
    return f"{done} из {len(cards)} посылок завершены"


# Guard после FOR UPDATE: чужая/несуществующая посылка и не-delivered.
def ensure_admin_shipment_completable(view: object | None, order_id: int) -> None:
    if view is None or int(getattr(view, "order_id", 0) or 0) != int(order_id):
        raise ShipmentError("Посылка не найдена")
    completed_at = getattr(view, "completed_at", None)
    status = str(getattr(view, "status", "") or "")
    if completed_at is None and status != ShipmentStatus.DELIVERED:
        raise ShipmentError("Завершить можно только доставленную посылку")


# Keys outbox для карточек B, включая суффикс канала.
def customer_notify_outbox_keys_for_cards(
    order_id: int,
    cards: Sequence[AdminShipmentCard],
) -> list[str]:
    keys: list[str] = []
    for card in cards:
        if not card.id:
            continue
        base = shipment_delivered_notify_key(order_id, card.id)
        keys.extend((base, f"{base}:telegram", f"{base}:email"))
    return keys


# Пишет sent в карту outbox по customer_notified (inline без строки outbox).
def merge_customer_notify_sent_from_events(
    outbox_by_key: Mapping[str, str],
    event_rows: Sequence[Mapping[str, object]] | None,
) -> dict[str, str]:
    merged = dict(outbox_by_key)
    if not event_rows:
        return merged
    for row in event_rows:
        if str(row.get("event_type") or "") != "customer_notified":
            continue
        payload = row.get("payload_json")
        if not isinstance(payload, dict):
            continue
        raw = payload.get("idempotency_key")
        if not raw:
            continue
        key = str(raw)
        merged.setdefault(key, NotificationOutboxStatus.SENT)
        if key.endswith(":telegram"):
            merged.setdefault(key[: -len(":telegram")], NotificationOutboxStatus.SENT)
        elif key.endswith(":email"):
            merged.setdefault(key[: -len(":email")], NotificationOutboxStatus.SENT)
    return merged


# Накладывает outbox-состояние B на карточки. Не трогает A.
def apply_customer_notify_state(
    cards: Sequence[AdminShipmentCard],
    order_id: int,
    outbox_by_key: Mapping[str, str],
    event_rows: Sequence[Mapping[str, object]] | None = None,
) -> list[AdminShipmentCard]:
    lookup = merge_customer_notify_sent_from_events(outbox_by_key, event_rows)
    updated: list[AdminShipmentCard] = []
    for card in cards:
        key = shipment_delivered_notify_key(order_id, card.id)
        status = outbox_status_for_customer_key(lookup, key)
        label = customer_notify_label_for_outbox(status)
        updated.append(replace(card, customer_notify_label=label))
    return updated


# Группирует посылки по order_id, сохраняя порядок строк.
def group_shipments_by_order_id(rows: Sequence[Shipment]) -> dict[int, list[Shipment]]:
    grouped: dict[int, list[Shipment]] = {}
    for row in rows:
        grouped.setdefault(int(row.order_id), []).append(row)
    return grouped


# Группирует allocation lines по SupplierOrder.id.
def group_lines_by_supplier_order_id(
    lines: Sequence[SupplierOrderLine],
) -> dict[int, list[SupplierOrderLine]]:
    grouped: dict[int, list[SupplierOrderLine]] = {}
    for line in lines:
        grouped.setdefault(int(line.supplier_order_id), []).append(line)
    return grouped


# RU-подпись опции для ЛК или None.
def _option_ru(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return translate_option_value(raw) or None


# Live setattr с fallback на captured snapshot.
def _item_text(item: OrderItem, live_name: str, captured_name: str) -> str | None:
    live = getattr(item, live_name, None)
    if live and str(live).strip():
        return str(live).strip()
    captured = getattr(item, captured_name, None)
    if captured and str(captured).strip():
        return str(captured).strip()
    return None


_DHL_PUBLIC_TRACKING_URL = (
    "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html"
    "?piececode={piececode}"
)


# Публичная DHL-ссылка по CJ; не ходит в DHL API.
def build_dhl_public_tracking_url(piececode: str) -> str:
    return _DHL_PUBLIC_TRACKING_URL.format(piececode=quote(piececode.strip()))


# DHL + Почта ссылки из одного CJ; пусто если CJ нет.
def customer_tracking_links_for_cj(
    cj: str | None,
) -> list[OrderShipmentTrackingLinkSchema]:
    number = str(cj or "").strip()
    if not number:
        return []
    return [
        OrderShipmentTrackingLinkSchema(
            carrier="DHL", url=build_dhl_public_tracking_url(number)
        ),
        OrderShipmentTrackingLinkSchema(
            carrier="Pochta", url=build_pochta_public_tracking_url(number)
        ),
    ]


# Customer tracking-нога: URL как в БД, links — публичные DHL/Почта от CJ.
def _public_tracking(
    carrier: str | None,
    number: str | None,
    url: str | None,
    links: list[OrderShipmentTrackingLinkSchema] | None = None,
) -> OrderShipmentTrackingSchema:
    return OrderShipmentTrackingSchema(
        carrier=carrier,
        tracking_number=number,
        tracking_url=url,
        links=list(links or ()),
    )


# Категория только из snapshot OrderItem, без live Product.
def _item_category_snapshot(item: OrderItem | None, captured_name: str) -> str | None:
    if item is None:
        return None
    captured = getattr(item, captured_name, None)
    if captured and str(captured).strip():
        return str(captured).strip()
    return None


# Public item посылки: qty из line, title/image из OrderItem, без TP/cost.
def _shipment_item_schema(
    line: SupplierOrderLine, item: OrderItem | None
) -> OrderShipmentItemSchema:
    title = None
    image = None
    option1 = option2 = option3 = None
    if item is not None:
        title = _item_text(item, "product_title", "product_title_captured")
        image_raw = getattr(item, "product_image_url", None)
        image = str(image_raw).strip() if image_raw else None
        option1 = _item_text(item, "variant_option1", "variant_option1_captured")
        option2 = _item_text(item, "variant_option2", "variant_option2_captured")
        option3 = _item_text(item, "variant_option3", "variant_option3_captured")
    display = ""
    if title:
        display = display_product_title(
            title, option1=option1, option2=option2, option3=option3
        )
    return OrderShipmentItemSchema(
        order_item_id=int(line.order_item_id),
        quantity=int(line.quantity),
        product_title=title,
        display_title=display or title,
        product_image_url=image or None,
        variant_option1_ru=_option_ru(option1),
        variant_option2_ru=_option_ru(option2),
        variant_option3_ru=_option_ru(option3),
        category_l2=_item_category_snapshot(item, "category_l2_captured"),
        category_l3=_item_category_snapshot(item, "category_l3_captured"),
    )


# Customer read-model посылок заказа: seq по id, без internal FK/cost/JSON.
def build_order_shipment_schemas(
    rows: Sequence[Shipment],
    lines_by_so_id: Mapping[int, Sequence[SupplierOrderLine]],
    order_items: Sequence[OrderItem],
) -> list[OrderShipmentSchema]:
    items_by_id = {
        int(item.id): item for item in order_items if getattr(item, "id", None)
    }
    schemas: list[OrderShipmentSchema] = []
    for seq, row in enumerate(rows, start=1):
        so_id = (
            int(row.supplier_order_id) if row.supplier_order_id is not None else None
        )
        line_rows = list(lines_by_so_id.get(so_id, ())) if so_id is not None else []
        status = str(row.status or "")
        schemas.append(
            OrderShipmentSchema(
                id=int(row.id),
                seq=seq,
                status=status,
                status_label=SHIPMENT_CUSTOMER_STATUS_LABELS.get(status, status),
                status_updated_at=row.status_updated_at,
                delivered_at=row.delivered_at,
                supplier_tracking=_public_tracking(
                    row.supplier_carrier,
                    row.supplier_tracking_number,
                    row.supplier_tracking_url,
                ),
                customer_tracking=_public_tracking(
                    row.customer_carrier,
                    row.customer_tracking_number,
                    row.customer_tracking_url,
                    customer_tracking_links_for_cj(row.supplier_tracking_number),
                ),
                items=[
                    _shipment_item_schema(
                        line, items_by_id.get(int(line.order_item_id))
                    )
                    for line in line_rows
                ],
            )
        )
    return schemas


class ShipmentService:
    # Read/create/backfill customer-facing Shipment; tracking apply — без commit.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)

    # Посылки заказа (read).
    async def list_for_order(self, order_id: int) -> list[ShipmentView]:
        rows = await self.order_crud.list_shipments_for_order(order_id)
        return [shipment_view(row) for row in rows]

    # Shipment по id или None.
    async def get_by_id(self, shipment_id: int) -> ShipmentView | None:
        row = await self.order_crud.get_shipment_by_id(shipment_id)
        if row is None:
            return None
        return shipment_view(row)

    # Admin completion этой посылки. Проверки под FOR UPDATE; не finalize / A / B / C.
    async def complete_shipment(
        self, shipment_id: int, order_id: int, commit: bool = True
    ) -> Shipment:
        row = await self.order_crud.get_shipment_by_id_for_update(shipment_id)
        ensure_admin_shipment_completable(row, order_id)
        assert row is not None
        mark_shipment_completed(row, utc_now_naive())
        if commit:
            await self.session.commit()
            await self.session.refresh(row)
        return row

    # Создаёт Shipment для placed SO; повтор того же SO — существующая строка.
    async def create_from_placed_supplier_order(
        self, order_id: int, supplier_order_id: int, commit: bool = True
    ) -> Shipment:
        row = await self._ensure_from_placed_supplier_order(order_id, supplier_order_id)
        if commit:
            await self.session.commit()
            await self.session.refresh(row)
        return row

    # Пишет Shipment status=preparing в текущей транзакции; без commit.
    async def _ensure_from_placed_supplier_order(
        self, order_id: int, supplier_order_id: int
    ) -> Shipment:
        existing = await self.order_crud.get_shipment_by_supplier_order_id(
            supplier_order_id
        )
        if existing is not None:
            if int(existing.order_id) != int(order_id):
                raise ShipmentError("Посылка уже связана с другим заказом")
            return existing
        order = await self.order_crud.get_by_id(order_id)
        if order is None:
            raise ShipmentError("Заказ не найден")
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        header = next((row for row in headers if row.id == supplier_order_id), None)
        if header is None:
            foreign = await self.session.get(SupplierOrder, supplier_order_id)
            if foreign is not None:
                validate_placed_source(order_id, foreign)
            raise ShipmentError("Заказ поставщика не найден")
        validate_placed_source(order_id, header)
        now = utc_now_naive()
        row = Shipment(
            order_id=order.id,
            supplier_order_id=header.id,
            status=ShipmentStatus.PREPARING,
            supplier_tracking_number=legacy_supplier_tracking_number(order, header),
            status_updated_at=now,
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            existing = await self.order_crud.get_shipment_by_supplier_order_id(
                supplier_order_id
            )
            if existing is not None and int(existing.order_id) == int(order_id):
                return existing
            raise ShipmentError("Посылка для этого заказа поставщика уже существует")
        return row

    # Идемпотентный backfill: placed SO без Shipment; TP без SO — только в stats.
    async def backfill_legacy(
        self, order_id: int | None = None
    ) -> ShipmentBackfillStats:
        missing = await self.order_crud.list_orders_with_tp_missing_placed_so(order_id)
        placed = await self.order_crud.list_placed_supplier_orders(order_id)
        created = 0
        skipped_existing = 0
        for header in placed:
            before = await self.order_crud.get_shipment_by_supplier_order_id(header.id)
            if before is not None:
                skipped_existing += 1
                continue
            await self.create_from_placed_supplier_order(header.order_id, header.id)
            created += 1
        return ShipmentBackfillStats(
            scanned_placed=len(placed),
            created=created,
            skipped_existing=skipped_existing,
            skipped_missing_so=len(missing),
        )
