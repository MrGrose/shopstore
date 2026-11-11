import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.client_texts import customer_status_message
from src.core.config import settings
from src.core.customer_activity import customer_activity_status
from src.deps import get_db
from src.integrations.sbp.errors import SBPError, SBPTimeoutError
from src.jobs.supplier_tracking_scheduler import enqueue_supplier_tracking
from src.models.user import User
from src.repositories.notification_outbox_repo import NotificationOutboxRepo
from src.schemas.order import (
    AdminAvailabilityConfirmationUpdate,
    AdminAvailabilityItemDecision,
    AdminAvailabilityStockCheckUpdate,
    AdminOrderItemAdd,
    AdminOrderItemsUpdate,
    AdminOrderItemUpdate,
    AdminOrderProductSearchResponse,
    AdminOrderStatusUpdate,
    AdminOrderUpdate,
    AdminStartAssemblingUpdate,
    AdminStartDeliveryUpdate,
)
from src.services.delivery_profile_service import DeliveryProfileService
from src.services.orders.admin_action_rail import resolve_admin_action_rail
from src.services.orders.journey_channel_resolver import customer_outbox_keys_for_order
from src.services.orders.order_service import (
    OrderService,
    normalize_admin_order_status_filter,
)
from src.services.orders.shipments import (
    ShipmentError,
    ShipmentService,
    admin_shipment_completion_summary,
    admin_shipment_status_counts,
    admin_shipment_summary,
    apply_customer_notify_state,
    build_admin_list_tp_by_order_id,
    build_admin_shipment_cards,
    build_admin_supplier_parcels,
    customer_notify_outbox_keys_for_cards,
)
from src.services.orders.supplier_availability.queue import (
    enqueue_supplier_availability,
)
from src.services.orders.supplier_orders import (
    SupplierOrderAllocationError,
    SupplierOrderService,
    apply_assembly_notify_state,
    assembly_notify_outbox_keys_for_orders,
)
from src.services.orders.supplier_tracking import (
    SupplierTrackingService,
    customer_timeline_for_journey,
)
from src.services.payment_service import PaymentService
from src.services.support import SupportService
from src.utils.datetime_fmt import (
    format_datetime_msk_short,
    msk_date_end_exclusive_utc_naive,
    msk_date_start_utc_naive,
)
from src.web.admin_context import admin_page_context
from src.web.admin_labels import (
    ADMIN_ORDER_QUEUE_ICONS,
    ADMIN_ORDER_QUEUE_KEYS,
    ADMIN_ORDER_QUEUE_LABELS,
    ADMIN_ORDER_QUEUE_TONES,
    ALL_ORDER_STATUSES,
    AVAILABILITY_CONFIRMATION_LABELS,
    ORDER_EVENT_LABELS,
    ORDER_STATUS_LABELS,
)
from src.web.admin_order_events import build_order_journey, format_order_event_rows
from src.web.admin_redirect import orders_list_url, orders_return_from_form
from src.web.deps import require_admin_user_page
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-orders"],
    dependencies=[Depends(require_admin_user_page)],
)

logger = logging.getLogger(__name__)


# Собирает карточки операционных очередей для списка заказов.
def _build_admin_order_queue_cards(counts: dict[str, int]) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    for key in ADMIN_ORDER_QUEUE_KEYS:
        cards.append(
            {
                "key": key,
                "label": ADMIN_ORDER_QUEUE_LABELS[key],
                "icon": ADMIN_ORDER_QUEUE_ICONS[key],
                "tone": ADMIN_ORDER_QUEUE_TONES[key],
                "count": int(counts.get(key, 0)),
            }
        )
    return cards


# Разбирает query-параметр даты YYYY-MM-DD для списка заказов.
def parse_admin_date_param(value: str | None) -> tuple[date | None, str | None]:
    if value is None:
        return None, None
    text = value.strip()
    if not text:
        return None, None
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, "Некорректная дата"


# Нормализует status query для шаблона списка заказов.
def _admin_orders_status_filter_context(status: str | None) -> tuple[str, list[str]]:
    statuses = normalize_admin_order_status_filter(status) or []
    return ",".join(statuses), statuses


@dataclass(frozen=True)
class AdminDateRangeFilter:
    date_from: date | None
    date_to: date | None
    created_from_utc: datetime | None
    created_to_exclusive_utc: datetime | None
    error: str | None


# Нормализует диапазон дат списка заказов и границы created_at в UTC.
def resolve_admin_date_range_filter(
    date_from_raw: str | None,
    date_to_raw: str | None,
) -> AdminDateRangeFilter:
    date_from, err_from = parse_admin_date_param(date_from_raw)
    if err_from:
        return AdminDateRangeFilter(None, None, None, None, err_from)
    date_to, err_to = parse_admin_date_param(date_to_raw)
    if err_to:
        return AdminDateRangeFilter(None, None, None, None, err_to)

    if date_from is None and date_to is None:
        return AdminDateRangeFilter(None, None, None, None, None)

    effective_from = date_from or date_to
    effective_to = date_to or date_from
    assert effective_from is not None and effective_to is not None

    if effective_from > effective_to:
        return AdminDateRangeFilter(
            date_from,
            date_to,
            None,
            None,
            "Дата начала позже даты окончания",
        )

    return AdminDateRangeFilter(
        date_from,
        date_to,
        msk_date_start_utc_naive(effective_from),
        msk_date_end_exclusive_utc_naive(effective_to),
        None,
    )


# Разбирает radio-решения проверки наличия из POST-формы админки.
def parse_availability_decisions_from_form(
    form_items: list[tuple[str, str]],
) -> list[AdminAvailabilityItemDecision]:
    decisions: list[AdminAvailabilityItemDecision] = []
    for key, value in form_items:
        if not key.startswith("availability_item_") or not key.endswith("_decision"):
            continue
        item_id_str = key.removeprefix("availability_item_").removesuffix("_decision")
        try:
            order_item_id = int(item_id_str)
        except ValueError:
            continue
        confirmed = str(value).strip().lower() == "confirmed"
        decisions.append(
            AdminAvailabilityItemDecision(
                order_item_id=order_item_id,
                confirmed=confirmed,
            )
        )
    return decisions


# Разбирает checkbox «Уведомить клиента» из POST-формы админки.
def parse_notify_customer_from_form(raw: str | None) -> bool:
    return raw in ("1", "on", "true", "yes")


# Форматирует попытки оплаты для шаблона админки.
def _format_payment_attempt_rows(attempts: list) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for attempt in attempts:
        rows.append(
            {
                "id": attempt.id,
                "attempt_number": attempt.attempt_number,
                "provider_order_id": attempt.provider_order_id,
                "merchant_order_id": attempt.merchant_order_id,
                "provider_status": attempt.provider_status,
                "payment_amount_minor": attempt.payment_amount_minor,
                "payment_currency": attempt.payment_currency,
                "created_at_display": format_datetime_msk_short(attempt.created_at),
                "qr_expires_at_display": format_datetime_msk_short(
                    attempt.qr_expires_at
                ),
                "paid_at_display": format_datetime_msk_short(attempt.paid_at),
            }
        )
    return rows


_CANCELLATION_REASON_LABELS = {
    "payment_timeout": "срок оплаты истёк",
    "customer_request": "отменён клиентом",
}


# Тех. поля оплаты для сворачиваемого блока в карточке заказа.
def _build_payment_tech_display(order_schema, order_row) -> dict[str, object]:
    payment_meta = getattr(order_row, "payment_meta_json", None) or {}
    if not isinstance(payment_meta, dict):
        payment_meta = {}
    cancellation = getattr(order_row, "cancellation_reason", None)
    cancellation_label = _CANCELLATION_REASON_LABELS.get(
        str(cancellation or ""),
        cancellation,
    )
    return {
        "state": order_schema.payment_state,
        "state_label": order_schema.payment_label,
        "provider": getattr(order_row, "payment_provider", None),
        "method": order_schema.payment_method_label,
        "order_id": getattr(order_row, "payment_order_id", None),
        "external_order_id": getattr(order_row, "payment_external_order_id", None),
        "status": getattr(order_row, "payment_status", None),
        "qr_id": getattr(order_row, "payment_qr_id", None),
        "paid_at": order_schema.payment_paid_at_short_display
        or format_datetime_msk_short(getattr(order_row, "payment_paid_at", None)),
        "due_at": format_datetime_msk_short(getattr(order_row, "payment_due_at", None)),
        "last_callback_at": format_datetime_msk_short(
            getattr(order_row, "payment_last_callback_at", None)
        ),
        "allowed": "да" if order_schema.payment_allowed else "нет",
        "gateway_enabled": "да" if order_schema.payment_gateway_enabled else "нет",
        "attempts": (
            f"{order_schema.payment_attempts_used} / "
            f"{order_schema.payment_attempts_limit}"
        ),
        "cancellation_reason": cancellation_label,
        "init_state": payment_meta.get("init_state"),
    }


# Строки date_from/date_to для шаблонов и URL.
def _admin_date_query_strings(date_filter: AdminDateRangeFilter) -> tuple[str, str]:
    date_from_str = date_filter.date_from.isoformat() if date_filter.date_from else ""
    date_to_str = date_filter.date_to.isoformat() if date_filter.date_to else ""
    return date_from_str, date_to_str


# Подпись фильтра по дате оплаты для списка заказов.
def _paid_filter_label(paid_filter: AdminDateRangeFilter) -> str | None:
    if paid_filter.error:
        return None
    if paid_filter.date_from is None and paid_filter.date_to is None:
        return None
    date_from = paid_filter.date_from or paid_filter.date_to
    date_to = paid_filter.date_to or paid_filter.date_from
    assert date_from is not None and date_to is not None
    if date_from == date_to:
        return f"Оплата: {date_from.strftime('%d.%m.%Y')}"
    return f"Оплата: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"


# Счётчики pill-фильтров с учётом q и периода (без фильтра status).
async def _fetch_admin_orders_status_counts(
    service: OrderService,
    q: str | None,
    date_filter: AdminDateRangeFilter,
    paid_filter: AdminDateRangeFilter,
) -> dict[str, int]:
    if date_filter.error or paid_filter.error:
        return await service.get_admin_orders_status_counts(q=q)
    return await service.get_admin_orders_status_counts(
        q=q,
        created_from_utc=date_filter.created_from_utc,
        created_to_exclusive_utc=date_filter.created_to_exclusive_utc,
        paid_from_utc=paid_filter.created_from_utc,
        paid_to_exclusive_utc=paid_filter.created_to_exclusive_utc,
    )


# Собирает контекст детальной страницы заказа.
async def _build_order_detail_context(
    service: OrderService,
    order_id: int,
    *,
    status: str | None = None,
    page: int = 1,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    paid_from: str | None = None,
    paid_to: str | None = None,
    packing_preview: bool = False,
    packing_manual: bool = False,
    packing_add_to: int | None = None,
) -> dict | None:
    try:
        order = await service.get_order(order_id)
        tracking_admin = await service.order_crud.get_by_id(order_id)
        events = await service.get_order_events(order_id)
        payment_attempts = await service.list_payment_attempts(order_id)
        supplier_order_estimate = await service.get_supplier_order_estimate_display(
            tracking_admin, order_id
        )
        so_service = SupplierOrderService(service.session)
        supplier_orders = await so_service.list_for_order(order_id)
        packing = await so_service.packing_context(order_id)
        shipment_rows = await ShipmentService(service.session).list_for_order(order_id)
        admin_shipments = build_admin_shipment_cards(shipment_rows, supplier_orders)
        admin_supplier_parcels = build_admin_supplier_parcels(
            supplier_orders,
            shipment_rows,
            getattr(order, "supplier_order_id", None),
            getattr(order, "supplier_tracking_id", None),
        )
        shipment_counts = admin_shipment_status_counts(admin_shipments)
        shipment_summary = admin_shipment_summary(admin_shipments)
        shipment_completion_summary = admin_shipment_completion_summary(admin_shipments)
        packing_recommendation = None
        if packing_preview:
            packing_recommendation = await so_service.packing_recommendation(order_id)
    except ValueError:
        return None
    allowed = service.allowed_next_statuses_for_order(order)
    status_choices, status_select_hint = OrderService.admin_status_select_context(
        order, allowed
    )
    availability_stock_rows: list[dict[str, object]] = []
    if order.availability_confirmation_status in ("pending", "unavailable"):
        availability_stock_rows = await service.build_availability_stock_rows(order_id)
    has_duplicate_payment = any(
        event.event_type == "payment_duplicate_accepted" for event in events
    )
    has_late_payment_after_auto_cancel = any(
        event.event_type == "late_payment_after_auto_cancel" for event in events
    )
    payment_attempts_count = len(payment_attempts)
    latest_attempt = payment_attempts[-1] if payment_attempts else None
    composition_edit_allowed, composition_edit_block_reason, qr_expires_at = (
        OrderService.composition_edit_state(order, latest_attempt)
    )
    composition_qr_expires_at_display = (
        format_datetime_msk_short(qr_expires_at) if qr_expires_at else None
    )
    support_counts = await SupportService(
        service.session
    ).count_open_tickets_by_order_ids([order_id])
    is_new_customer = False
    customer_orders: list = []
    customer_orders_count = 0
    delivery_profile = None
    if order.user_id is not None:
        delivery_profile = await DeliveryProfileService(service.session).get_profile(
            order.user_id
        )
        user_order_counts = await service.count_orders_by_user_ids([order.user_id])
        orders_count = user_order_counts.get(order.user_id, 0)
        is_new_customer = customer_activity_status(orders_count) == "new"
        customer_orders_count = orders_count
        customer_orders = await service.order_crud.list_by_user(order.user_id, limit=5)
    event_rows = format_order_event_rows(
        events,
        event_labels=ORDER_EVENT_LABELS,
        status_labels={**ORDER_STATUS_LABELS, **AVAILABILITY_CONFIRMATION_LABELS},
    )
    outbox_keys = customer_outbox_keys_for_order(order_id)
    outbox_keys.extend(customer_notify_outbox_keys_for_cards(order_id, admin_shipments))
    outbox_keys.extend(
        assembly_notify_outbox_keys_for_orders(order_id, supplier_orders)
    )
    outbox_by_key = await NotificationOutboxRepo(service.session).status_by_keys(
        outbox_keys
    )
    admin_shipments = apply_customer_notify_state(
        admin_shipments, order_id, outbox_by_key, event_rows
    )
    supplier_orders = apply_assembly_notify_state(
        supplier_orders, order_id, outbox_by_key, event_rows
    )
    order_journey = build_order_journey(
        order,
        event_rows,
        tracking_json=getattr(tracking_admin, "supplier_tracking_json", None),
        outbox_by_key=outbox_by_key,
        supplier_orders=supplier_orders,
        shipments=shipment_rows,
    )
    if tracking_admin is not None and order.supplier_order_id:
        customer_preview = customer_timeline_for_journey(
            tracking_admin,
            events,
            getattr(tracking_admin, "supplier_tracking_json", None),
            tracking_updated_at=getattr(
                tracking_admin, "supplier_tracking_updated_at", None
            ),
        )
        order_journey = {
            **order_journey,
            "customer_timeline": customer_preview["events"],
            "customer_preview": {
                "current_status": customer_preview.get("current_status"),
                "current_description": customer_preview.get("current_description"),
            },
        }
    return {
        "order": order,
        "is_new_customer": is_new_customer,
        "customer_orders": customer_orders,
        "customer_orders_count": customer_orders_count,
        "delivery_profile": delivery_profile,
        "payment_attempt_rows": _format_payment_attempt_rows(payment_attempts),
        "payment_tech": _build_payment_tech_display(order, tracking_admin),
        "has_duplicate_payment": has_duplicate_payment,
        "has_late_payment_after_auto_cancel": has_late_payment_after_auto_cancel,
        "payment_attempts_count": payment_attempts_count,
        "payment_attempts_limit": order.payment_attempts_limit,
        "composition_edit_allowed": composition_edit_allowed,
        "composition_edit_block_reason": composition_edit_block_reason,
        "composition_qr_expires_at_display": composition_qr_expires_at_display,
        "event_rows": event_rows,
        "order_journey": order_journey,
        "allowed_statuses": allowed,
        "status_choices": status_choices,
        "status_select_hint": status_select_hint,
        "order_status_display": OrderService.resolve_admin_status_label(order),
        "start_assembling_allowed": OrderService.can_start_assembling(
            order, supplier_orders=supplier_orders, packing=packing
        ),
        "admin_action_rail": resolve_admin_action_rail(
            order,
            composition_edit_allowed=composition_edit_allowed,
            outbox_by_key=outbox_by_key,
            packing=packing,
            supplier_orders=supplier_orders,
            shipment_summary=shipment_summary,
        ),
        "availability_labels": AVAILABILITY_CONFIRMATION_LABELS,
        "availability_stock_rows": availability_stock_rows,
        "supplier_availability_snapshot": getattr(
            order, "supplier_availability_json", None
        ),
        "orders_return": {
            "status": status or None,
            "page": page,
            "q": q or None,
            "date_from": date_from or None,
            "date_to": date_to or None,
            "paid_from": paid_from or None,
            "paid_to": paid_to or None,
        },
        "support_open_count": support_counts.get(order_id, 0),
        "supplier_order_estimate": supplier_order_estimate,
        "supplier_orders": supplier_orders,
        "packing": packing,
        "admin_shipments": admin_shipments,
        "admin_supplier_parcels": admin_supplier_parcels,
        "shipment_counts": shipment_counts,
        "shipment_summary": shipment_summary,
        "shipment_completion_summary": shipment_completion_summary,
        "packing_recommendation": packing_recommendation,
        "packing_preview_url": orders_list_url(
            order_id=order_id,
            status=status,
            page=page,
            q=q,
            date_from=date_from,
            date_to=date_to,
            paid_from=paid_from,
            paid_to=paid_to,
            packing_preview=True,
            anchor="order-supplier-orders",
        ),
        "packing_manual_url": orders_list_url(
            order_id=order_id,
            status=status,
            page=page,
            q=q,
            date_from=date_from,
            date_to=date_to,
            paid_from=paid_from,
            paid_to=paid_to,
            packing_manual=True,
            anchor="order-supplier-orders",
        ),
        "packing_result_url": orders_list_url(
            order_id=order_id,
            status=status,
            page=page,
            q=q,
            date_from=date_from,
            date_to=date_to,
            paid_from=paid_from,
            paid_to=paid_to,
            anchor="order-supplier-orders",
        ),
        "packing_manual": packing_manual and not packing_preview,
        "packing_add_to": packing_add_to,
        "packing_add_urls": {
            so.id: orders_list_url(
                order_id=order_id,
                status=status,
                page=page,
                q=q,
                date_from=date_from,
                date_to=date_to,
                paid_from=paid_from,
                paid_to=paid_to,
                packing_manual=packing_manual and not packing_preview,
                packing_add_to=so.id,
                anchor="order-supplier-orders",
            )
            for so in supplier_orders
            if so.is_draft
        },
    }


# Редирект на страницу заказов после POST.
def _orders_redirect(
    order_id: int,
    orders_return: dict[str, object],
    *,
    success: str | None = None,
    error: str | None = None,
    warning: str | None = None,
    anchor: str | None = None,
) -> RedirectResponse:
    return RedirectResponse(
        url=orders_list_url(
            order_id=order_id,
            status=orders_return.get("status"),  # type: ignore[arg-type]
            page=int(orders_return.get("page") or 1),  # type: ignore[call-overload]
            q=orders_return.get("q"),  # type: ignore[arg-type]
            date_from=orders_return.get("date_from"),  # type: ignore[arg-type]
            date_to=orders_return.get("date_to"),  # type: ignore[arg-type]
            paid_from=orders_return.get("paid_from"),  # type: ignore[arg-type]
            paid_to=orders_return.get("paid_to"),  # type: ignore[arg-type]
            success=success,
            error=error or warning,
            anchor=anchor,
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Страница заказов: список или деталь по ?id=.
@router.get(
    "/internal/admin/orders", response_class=HTMLResponse, include_in_schema=False
)
async def admin_orders_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    selected_id: int | None = Query(default=None, alias="id"),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    paid_from: str | None = Query(default=None),
    paid_to: str | None = Query(default=None),
    queue: str | None = Query(default=None),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None),
    packing_preview: int = Query(default=0),
    packing_manual: int = Query(default=0),
    packing_add_to: int | None = Query(default=None),
) -> HTMLResponse:
    service = OrderService(db)
    orders_queues = await service.get_admin_orders_queues()
    orders_queue_cards = _build_admin_order_queue_cards(orders_queues)
    queue_filter = (queue or "").strip().lower()
    if queue_filter not in ADMIN_ORDER_QUEUE_KEYS:
        queue_filter = ""
    date_filter = resolve_admin_date_range_filter(date_from, date_to)
    paid_filter = resolve_admin_date_range_filter(paid_from, paid_to)
    date_from_str, date_to_str = _admin_date_query_strings(date_filter)
    paid_from_str, paid_to_str = _admin_date_query_strings(paid_filter)
    page_error = error or date_filter.error or paid_filter.error
    detail = None
    if selected_id:
        detail = await _build_order_detail_context(
            service,
            selected_id,
            status=status,
            page=page,
            q=q,
            date_from=date_from_str or None,
            date_to=date_to_str or None,
            paid_from=paid_from_str or None,
            paid_to=paid_to_str or None,
            packing_preview=bool(packing_preview),
            packing_manual=bool(packing_manual),
            packing_add_to=packing_add_to,
        )
    paid_filter_label = _paid_filter_label(paid_filter)
    status_filter, status_filters = _admin_orders_status_filter_context(status)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/orders.html",
        context=admin_page_context(
            request,
            admin_user,
            page=page,
            q=q or "",
            date_from=date_from_str,
            date_to=date_to_str,
            paid_from=paid_from_str,
            paid_to=paid_to_str,
            paid_filter_label=paid_filter_label,
            selected_id=selected_id,
            status_filter=status_filter,
            status_filters=status_filters,
            queue_filter=queue_filter,
            status_labels=ORDER_STATUS_LABELS,
            all_statuses=ALL_ORDER_STATUSES,
            orders_queues=orders_queues,
            orders_queue_cards=orders_queue_cards,
            queue_labels=ADMIN_ORDER_QUEUE_LABELS,
            orders_status_counts={},
            detail=detail,
            error=page_error,
            success=success,
            orders_bulk_delete_enabled=True,
        ),
    )


# TP колонки списка: placed SO.external_id, иначе legacy, одним запросом.
async def _admin_order_list_tp_ids(
    service: OrderService,
    orders: list,
) -> dict[int, list[str]]:
    if not orders:
        return {}
    headers = await SupplierOrderService(service.session).list_headers_for_order_ids(
        [int(row.id) for row in orders]
    )
    return build_admin_list_tp_by_order_id(headers, orders)


# HTMX-partial: таблица заказов.
@router.get(
    "/internal/admin/orders/table",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_orders_table_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    paid_from: str | None = Query(default=None),
    paid_to: str | None = Query(default=None),
    queue: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    date_filter = resolve_admin_date_range_filter(date_from, date_to)
    paid_filter = resolve_admin_date_range_filter(paid_from, paid_to)
    date_from_str, date_to_str = _admin_date_query_strings(date_filter)
    paid_from_str, paid_to_str = _admin_date_query_strings(paid_filter)
    queue_filter = (queue or "").strip().lower()
    if queue_filter not in ADMIN_ORDER_QUEUE_KEYS:
        queue_filter = ""
    service = OrderService(db)
    status_filter, status_filters = _admin_orders_status_filter_context(status)
    orders_status_counts = await _fetch_admin_orders_status_counts(
        service, q, date_filter, paid_filter
    )
    if date_filter.error or paid_filter.error:
        filter_error = date_filter.error or paid_filter.error
        return templates.TemplateResponse(
            request=request,
            name="site/admin/partials/orders_table.html",
            context=admin_page_context(
                request,
                admin_user,
                orders=[],
                total=0,
                page=page,
                page_size=page_size,
                total_pages=1,
                status_filter=status_filter,
                status_filters=status_filters,
                queue_filter=queue_filter,
                q=q or "",
                date_from=date_from_str,
                date_to=date_to_str,
                paid_from=paid_from_str,
                paid_to=paid_to_str,
                date_filter_error=filter_error,
                status_labels=ORDER_STATUS_LABELS,
                orders_status_counts=orders_status_counts,
                orders_bulk_delete_enabled=True,
                order_supplier_tps={},
            ),
        )
    listed = await service.list_admin_orders(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        q=q,
        created_from_utc=date_filter.created_from_utc,
        created_to_exclusive_utc=date_filter.created_to_exclusive_utc,
        paid_from_utc=paid_filter.created_from_utc,
        paid_to_exclusive_utc=paid_filter.created_to_exclusive_utc,
        queue=queue_filter or None,
    )
    total = int(listed["total"])  # type: ignore[call-overload]
    total_pages = max(1, (total + page_size - 1) // page_size)
    listed_items = listed["items"]
    order_ids: list[int] = []
    user_ids: list[int] = []
    if isinstance(listed_items, list):
        for row in listed_items:
            row_id = getattr(row, "id", None)
            if row_id is not None:
                order_ids.append(int(row_id))
            user_id = getattr(row, "user_id", None)
            if user_id is not None:
                user_ids.append(int(user_id))
    support_ticket_counts = await SupportService(db).count_open_tickets_by_order_ids(
        order_ids
    )
    user_order_counts = await service.count_orders_by_user_ids(user_ids)
    new_customer_user_ids = {
        user_id
        for user_id, orders_count in user_order_counts.items()
        if customer_activity_status(orders_count) == "new"
    }
    listed_orders = listed_items if isinstance(listed_items, list) else []
    order_supplier_tps = await _admin_order_list_tp_ids(service, listed_orders)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/orders_table.html",
        context=admin_page_context(
            request,
            admin_user,
            orders=listed["items"],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            status_filter=status_filter,
            status_filters=status_filters,
            queue_filter=queue_filter,
            q=q or "",
            date_from=date_from_str,
            date_to=date_to_str,
            paid_from=paid_from_str,
            paid_to=paid_to_str,
            date_filter_error=None,
            status_labels=ORDER_STATUS_LABELS,
            orders_status_counts=orders_status_counts,
            support_ticket_counts=support_ticket_counts,
            new_customer_user_ids=new_customer_user_ids,
            orders_bulk_delete_enabled=True,
            order_supplier_tps=order_supplier_tps,
        ),
    )


# POST: безвозвратно удалить выбранные заказы.
@router.post(
    "/internal/admin/orders/delete-selected",
    response_class=JSONResponse,
    include_in_schema=False,
)
async def admin_orders_delete_selected(
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    order_ids: list[int] = Form(default=[]),
) -> JSONResponse:
    _ = admin_user
    service = OrderService(db)
    try:
        deleted = await service.admin_delete_orders_by_ids(order_ids)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"deleted": deleted, "message": f"Удалено заказов: {deleted}"})


# GET: черновик сообщения клиенту при смене статуса.
@router.get(
    "/internal/admin/orders/{order_id}/status-message-preview",
    response_class=JSONResponse,
    include_in_schema=False,
)
async def admin_order_status_message_preview(
    order_id: int,
    status: str = Query(..., min_length=1, max_length=32),
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(require_admin_user_page),
) -> JSONResponse:
    _ = admin_user
    service = OrderService(db)
    order = await service.order_crud.get_by_id(order_id)
    if order is None:
        return JSONResponse({"detail": "Заказ не найден"}, status_code=404)
    next_status = status.strip().lower()
    allowed = service.allowed_next_statuses_for_order(order)
    if next_status != order.status and next_status not in allowed:
        return JSONResponse({"detail": "Недопустимый статус"}, status_code=400)
    message = customer_status_message(
        order_id=order_id,
        status=next_status,
        fmt="plain",
    )
    return JSONResponse({"message": message})


# POST: смена статуса заказа.
@router.post(
    "/internal/admin/orders/{order_id}/status",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_status_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    status: str = Form(...),
    event_message: str = Form(""),
    custom_message: str = Form(""),
    notify_customer: str | None = Form(default=None),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = OrderService(db)
    payload = AdminOrderStatusUpdate(
        status=status,
        event_message=event_message or None,
        custom_message=custom_message.strip() or None,
        notify_customer=parse_notify_customer_from_form(notify_customer),
    )
    try:
        await service.update_order_status(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
        return _orders_redirect(order_id, orders_return, success="Статус сохранён")
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: внутренний комментарий в историю заказа (без смены статуса).
@router.post(
    "/internal/admin/orders/{order_id}/comment",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_comment_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    event_message: str = Form(""),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await OrderService(db).add_admin_order_comment(
            order_id=order_id,
            message=event_message,
            actor=admin_user,
        )
        return _orders_redirect(order_id, orders_return, success="Комментарий добавлен")
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: передача заказа в сборку у поставщика.
@router.post(
    "/internal/admin/orders/{order_id}/start-assembling",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_start_assembling_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    supplier_order_id: str = Form(...),
    event_message: str = Form(""),
    notify_customer: str | None = Form(default=None),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = OrderService(db)
    try:
        payload = AdminStartAssemblingUpdate(
            supplier_order_id=supplier_order_id,
            event_message=event_message or None,
            notify_customer=parse_notify_customer_from_form(notify_customer),
        )
        await service.start_order_assembling(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
        try:
            enqueue_supplier_tracking(order_id)
        except Exception:
            logger.exception(
                "Не удалось поставить первую проверку трека order=%s", order_id
            )
        return _orders_redirect(
            order_id, orders_return, success="Заказ передан в сборку"
        )
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: поставить проверку трекинга в RQ-очередь.
@router.post(
    "/internal/admin/orders/{order_id}/tracking/check",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_tracking_check(
    request: Request,
    order_id: int,
    _admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    order = await OrderService(db).order_crud.get_by_id(order_id)
    if order is not None and str(order.status or "").lower() == "completed":
        return _orders_redirect(
            order_id,
            orders_return,
            error="Заказ выполнен — проверка доставки недоступна",
        )
    try:
        enqueue_supplier_tracking(order_id)
        return _orders_redirect(
            order_id, orders_return, success="Проверка поставлена в очередь"
        )
    except Exception:
        return _orders_redirect(
            order_id,
            orders_return,
            error="Проверка уже выполняется или очередь недоступна",
        )


# POST: ручное admin completion одной Shipment. Не finalize / B / C.
@router.post(
    "/internal/admin/orders/{order_id}/shipments/{shipment_id}/complete",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_shipment_complete_submit(
    request: Request,
    order_id: int,
    shipment_id: int,
    _admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    shipments = ShipmentService(db)
    try:
        await shipments.complete_shipment(shipment_id, order_id)
        return _orders_redirect(order_id, orders_return, success="Посылка завершена")
    except ShipmentError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: customer B для выбранных Shipment. Не complete и не finalize.
@router.post(
    "/internal/admin/orders/{order_id}/shipments/notify",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_shipments_notify_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    shipment_ids: list[int] = []
    for raw in form.getlist("shipment_ids"):
        try:
            shipment_ids.append(int(str(raw)))
        except ValueError:
            continue
    custom_message = str(form.get("custom_message") or "").strip() or None
    try:
        queued = await OrderService(db).notify_shipments_delivered(
            order_id,
            shipment_ids,
            custom_message,
            admin_user,
        )
        if queued:
            success = "Уведомление клиенту поставлено в очередь"
        else:
            success = "Уведомление по выбранным посылкам уже отправлено"
        return _orders_redirect(order_id, orders_return, success=success)
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: ручная сверка с ParcelLab (snapshot только для админки).
@router.post(
    "/internal/admin/orders/{order_id}/tracking/parcellab-compare",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_tracking_parcellab_compare(
    request: Request,
    order_id: int,
    _admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await SupplierTrackingService(db).compare_parcellab(order_id)
        return _orders_redirect(
            order_id, orders_return, success="Сверка с Supplier-Demo сохранена"
        )
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: ручной этап доставки в store_events.
@router.post(
    "/internal/admin/orders/{order_id}/tracking/manual",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_tracking_manual(
    request: Request,
    order_id: int,
    _admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    stage: str = Form(...),
    description: str = Form(""),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await SupplierTrackingService(db).add_manual_event(
            order_id, stage, description.strip() or None
        )
        return _orders_redirect(
            order_id, orders_return, success="Этап доставки добавлен"
        )
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: передача собранного заказа в доставку с трек-номером.
@router.post(
    "/internal/admin/orders/{order_id}/start-delivery",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_start_delivery_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    supplier_tracking_id: str = Form(...),
    event_message: str = Form(""),
    notify_customer: str | None = Form(default=None),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = OrderService(db)
    try:
        payload = AdminStartDeliveryUpdate(
            supplier_tracking_id=supplier_tracking_id,
            event_message=event_message or None,
            notify_customer=parse_notify_customer_from_form(notify_customer),
        )
        await service.start_order_delivery(order_id, payload, actor=admin_user)
        return _orders_redirect(
            order_id, orders_return, success="Заказ передан в доставку"
        )
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: подтверждение или отклонение наличия по пограничному остатку.
@router.post(
    "/internal/admin/orders/{order_id}/availability",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_availability_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    action: str = Form(...),
    event_message: str = Form(""),
    notify_customer: str | None = Form(default=None),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = OrderService(db)
    payload = AdminAvailabilityConfirmationUpdate(
        action=action,
        event_message=event_message or None,
        notify_customer=parse_notify_customer_from_form(notify_customer),
    )
    try:
        normalized_action = action.strip().lower()
        if normalized_action == "save_check":
            decisions = parse_availability_decisions_from_form(list(form.multi_items()))
            _order_schema, warning = await service.save_availability_stock_check(
                order_id=order_id,
                payload=AdminAvailabilityStockCheckUpdate(
                    items=decisions,
                    event_message=event_message or None,
                    notify_customer=parse_notify_customer_from_form(notify_customer),
                ),
                actor=admin_user,
            )
            return _orders_redirect(
                order_id,
                orders_return,
                success="Результат проверки наличия сохранён",
                warning=warning,
            )
        if normalized_action == "confirm":
            await service.confirm_availability(
                order_id=order_id,
                payload=payload,
                actor=admin_user,
            )
            return _orders_redirect(
                order_id, orders_return, success="Наличие подтверждено"
            )
        if normalized_action == "reject":
            await service.mark_availability_unavailable(
                order_id=order_id,
                payload=payload,
                actor=admin_user,
            )
            return _orders_redirect(
                order_id, orders_return, success="Отказ по наличию сохранён"
            )
        return _orders_redirect(order_id, orders_return, error="Неизвестное действие")
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: поставить автопроверку наличия у TP в RQ-очередь.
@router.post(
    "/internal/admin/orders/{order_id}/availability/recheck",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_availability_recheck(
    request: Request,
    order_id: int,
    _admin_user: User = Depends(require_admin_user_page),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    if not settings.SUPPLIER_AVAILABILITY_ENABLED:
        return _orders_redirect(
            order_id,
            orders_return,
            error="Автопроверка TP отключена (SUPPLIER_AVAILABILITY_ENABLED=false)",
        )
    try:
        job = enqueue_supplier_availability(order_id)
        if job is None:
            return _orders_redirect(
                order_id,
                orders_return,
                error="Не удалось поставить автопроверку TP в очередь",
            )
        return _orders_redirect(
            order_id,
            orders_return,
            success="Автопроверка TP поставлена в очередь",
        )
    except Exception:
        logger.exception(
            "Не удалось поставить автопроверку TP order=%s",
            order_id,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            error="Проверка уже выполняется или очередь недоступна",
        )


# POST: произвольное сообщение клиенту в Telegram.
@router.post(
    "/internal/admin/orders/{order_id}/notify",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_notify_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    message: str = Form(...),
    channel: str = Form("telegram"),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await OrderService(db).send_customer_message(
            order_id=order_id,
            message=message,
            channel=channel,
            actor=admin_user,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            success="Сообщение поставлено в выбранные каналы",
        )
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: сохранение адреса доставки заказа.
@router.post(
    "/internal/admin/orders/{order_id}/delivery",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_delivery_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    last_name: str = Form(""),
    first_name: str = Form(""),
    city: str = Form(""),
    street: str = Form(""),
    house: str = Form(""),
    apartment: str = Form(""),
    postal_code: str = Form(""),
    event_message: str = Form(""),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = OrderService(db)
    payload = AdminOrderUpdate(
        last_name=last_name or None,
        first_name=first_name or None,
        city=city or None,
        street=street or None,
        house=house or None,
        apartment=apartment or None,
        postal_code=postal_code or None,
        event_message=event_message or None,
    )
    try:
        await service.update_order_delivery(
            order_id=order_id,
            payload=payload,
            actor=admin_user,
        )
        return _orders_redirect(order_id, orders_return, success="Доставка сохранена")
    except ValueError as exc:
        return _orders_redirect(order_id, orders_return, error=str(exc))


# POST: создать draft SupplierOrder.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_create(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await SupplierOrderService(db).create_draft(order_id)
        return _orders_redirect(
            order_id,
            orders_return,
            success="Черновик заказа поставщика создан",
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: сохранить allocation draft SO.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders/{supplier_order_id}/lines",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_lines_submit(
    request: Request,
    order_id: int,
    supplier_order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    quantities: dict[int, int] = {}
    for key, value in form.multi_items():
        if not str(key).startswith("line_") or not str(key).endswith("_qty"):
            continue
        item_id_str = str(key).removeprefix("line_").removesuffix("_qty")
        try:
            quantities[int(item_id_str)] = int(str(value or "0"))
        except ValueError:
            return _orders_redirect(
                order_id,
                orders_return,
                error="Некорректное количество в заказе поставщика",
                anchor="order-supplier-orders",
            )
    try:
        await SupplierOrderService(db).save_draft_lines(
            order_id, supplier_order_id, quantities
        )
        return _orders_redirect(
            order_id,
            orders_return,
            success="Состав заказа поставщика сохранён",
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: удалить draft SupplierOrder.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders/{supplier_order_id}/delete",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_delete(
    request: Request,
    order_id: int,
    supplier_order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        await SupplierOrderService(db).delete_draft(order_id, supplier_order_id)
        return _orders_redirect(
            order_id,
            orders_return,
            success="Черновик заказа поставщика удалён",
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: ручной place draft SO по TP number.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders/{supplier_order_id}/place",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_place(
    request: Request,
    order_id: int,
    supplier_order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    external_id = str(form.get("external_id") or "")
    notify_customer = parse_notify_customer_from_form(
        str(form.get("notify_customer") or "") or None
    )
    custom_message = str(form.get("custom_message") or "").strip() or None
    try:
        await SupplierOrderService(db).place_draft(
            order_id,
            supplier_order_id,
            external_id,
            notify_customer=notify_customer,
            custom_message=custom_message,
            actor=admin_user,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            success="Заказ поставщика оформлен",
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: packing-notify для уже оформленной посылки. Не place.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders/{supplier_order_id}/notify",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_notify(
    request: Request,
    order_id: int,
    supplier_order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    custom_message = str(form.get("custom_message") or "").strip() or None
    try:
        queued = await SupplierOrderService(db).notify_placed_parcel(
            order_id,
            supplier_order_id,
            custom_message,
            admin_user,
        )
        if queued:
            success = "Уведомление клиенту поставлено в очередь"
        else:
            success = "Уведомление по этой посылке уже отправлено"
        return _orders_redirect(
            order_id,
            orders_return,
            success=success,
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: заменить draft посылки рекомендацией. Preview ничего не пишет.
@router.post(
    "/internal/admin/orders/{order_id}/supplier-orders/recommend",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_supplier_order_recommend(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    try:
        preview = await SupplierOrderService(db).apply_packing_recommendation(order_id)
        count = len(preview.parcels)
        success = (
            f"Рекомендация применена: {count} посыл"
            f"{'ка' if count == 1 else 'ки' if count < 5 else 'ок'}"
        )
        return _orders_redirect(
            order_id,
            orders_return,
            success=success,
            anchor="order-supplier-orders",
        )
    except (ValueError, SupplierOrderAllocationError) as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-supplier-orders"
        )


# POST: изменение позиций заказа.
@router.post(
    "/internal/admin/orders/{order_id}/items",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_order_items_submit(
    request: Request,
    order_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    event_message: str = Form(""),
    add_product_id: str = Form(""),
    add_variant_id: str = Form(""),
    add_quantity: str = Form(""),
    add_unit_price: str = Form(""),
    notify_customer: str | None = Form(default=None),
) -> HTMLResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    items: list[AdminOrderItemUpdate] = []
    remove_item_ids: list[int] = []
    for key, value in form.multi_items():
        if key == "remove_item_ids":
            try:
                remove_item_ids.append(int(value))
            except ValueError:
                continue
            continue
        if not key.startswith("item_") or not key.endswith("_qty"):
            continue
        item_id_str = key.removeprefix("item_").removesuffix("_qty")
        try:
            item_id = int(item_id_str)
            quantity = int(value)
        except ValueError:
            continue
        if item_id in remove_item_ids:
            continue
        price_key = f"item_{item_id}_price"
        price_raw = form.get(price_key, "")
        unit_price: Decimal | None = None
        if price_raw:
            try:
                unit_price = Decimal(str(price_raw).replace(",", "."))
            except InvalidOperation:
                return _orders_redirect(
                    order_id,
                    orders_return,
                    error=f"Некорректная цена для позиции {item_id}",
                    anchor="order-items",
                )
        items.append(
            AdminOrderItemUpdate(
                id=item_id,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
    add_items: list[AdminOrderItemAdd] = []
    if add_product_id.strip():
        try:
            product_id = int(add_product_id.strip())
            quantity = int(add_quantity.strip() or "1")
            variant_id: int | None = None
            if add_variant_id.strip():
                variant_id = int(add_variant_id.strip())
            add_unit_price_value: Decimal | None = None
            if add_unit_price.strip():
                add_unit_price_value = Decimal(add_unit_price.strip().replace(",", "."))
            add_items.append(
                AdminOrderItemAdd(
                    product_id=product_id,
                    variant_id=variant_id,
                    quantity=quantity,
                    unit_price=add_unit_price_value,
                )
            )
        except (ValueError, InvalidOperation):
            return _orders_redirect(
                order_id,
                orders_return,
                error="Некорректные данные для добавления товара",
                anchor="order-items",
            )
    service = OrderService(db)
    try:
        _order_schema, warning = await service.edit_order_composition(
            order_id=order_id,
            payload=AdminOrderItemsUpdate(
                items=items,
                remove_item_ids=remove_item_ids,
                add_items=add_items,
                event_message=event_message or None,
                notify_customer=parse_notify_customer_from_form(notify_customer),
            ),
            actor=admin_user,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            success="Позиции сохранены",
            warning=warning,
            anchor="order-items",
        )
    except ValueError as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-items"
        )


# JSON-поиск товаров для добавления в заказ.
@router.get(
    "/internal/admin/orders/product-search",
    response_model=AdminOrderProductSearchResponse,
    include_in_schema=False,
)
async def admin_order_product_search(
    q: str = Query(..., min_length=1, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> AdminOrderProductSearchResponse:
    return await OrderService(db).search_products_for_admin_pick(q)


# Ручная проверка статуса SBP для попытки оплаты.
@router.post(
    "/internal/admin/orders/{order_id}/payment-attempts/{attempt_id}/refresh",
    include_in_schema=False,
)
async def admin_refresh_payment_attempt(
    request: Request,
    order_id: int,
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    orders_return = orders_return_from_form(form)
    service = PaymentService(db)
    try:
        await service.refresh_payment_attempt_admin(attempt_id, order_id=order_id)
        return _orders_redirect(
            order_id,
            orders_return,
            success="Статус в SBP обновлён",
            anchor="order-payment",
        )
    except ValueError as exc:
        return _orders_redirect(
            order_id, orders_return, error=str(exc), anchor="order-payment"
        )
    except SBPTimeoutError as exc:
        logger.warning(
            "SBP timeout при refresh attempt_id=%s order_id=%s: %s",
            attempt_id,
            order_id,
            exc,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            error="SBP не ответил вовремя. Повторите через минуту.",
            anchor="order-payment",
        )
    except SBPError as exc:
        logger.warning(
            "Ошибка SBP при refresh attempt_id=%s order_id=%s: %s",
            attempt_id,
            order_id,
            exc,
        )
        return _orders_redirect(
            order_id,
            orders_return,
            error=(
                "Не удалось получить статус в SBP. "
                "Проверьте ID попытки или повторите позже."
            ),
            anchor="order-payment",
        )
