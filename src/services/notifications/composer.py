from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.content.admin_texts import (
    admin_order_url,
    format_availability_review_message,
    format_duplicate_payment_message,
    format_late_payment_message,
    format_order_created_message,
    format_order_delivery_started_message,
    format_order_technical_problem_message,
    format_payment_accepted_message,
)
from src.content.client_texts import (
    CUSTOMER_ORDER_TG_PARSE_MODE,
    CustomerMessageFormat,
    build_customer_webapp_cta_keyboard,
    customer_status_message,
    format_customer_availability_check_message,
    format_customer_availability_confirmed_message,
    format_customer_availability_unavailable_message,
    format_customer_composition_changed_message,
    format_customer_manual_message,
    format_customer_payment_awaiting_message,
    format_customer_payment_failed_message,
    format_customer_payment_late_received_message,
    format_customer_payment_received_message,
    format_customer_telegram_delivery_text,
    is_customer_html_message,
    resolve_customer_notification_cta,
)
from src.content.support_texts import (
    format_support_group_ticket_message,
    format_support_staff_reply_to_customer,
)
from src.content.telegram_html import OPS_ORDER_TG_PARSE_MODE
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    variant_label_from_options,
)
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.services.identity_service import IdentityService
from src.services.notifications.admin_keyboards import (
    admin_orders_reply_markup,
    build_admin_support_ticket_keyboard,
)
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from src.utils.payment import normalize_order_payment_from_attempt

HTML = OPS_ORDER_TG_PARSE_MODE

# Типы для type hints.
if TYPE_CHECKING:
    from src.services.orders.order_service import OrderService


# Тип для composed notification.
@dataclass(frozen=True)
class ComposedNotification:
    chat_id: int
    text: str
    parse_mode: str | None = None
    order_id: int | None = None
    reply_markup: dict[str, object] | None = None


@dataclass(frozen=True)
class ComposedEmailNotification:
    email: str
    subject: str
    text: str
    order_id: int


async def compose_email_notification(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedEmailNotification | None:
    order_id = _require_int(dispatch.payload, "order_id")
    if order_id is None:
        return None
    order = await CrudOrder(session=session, model=Order).get_by_id(order_id)
    if order is None:
        return None
    email = order.notification_email
    if not email:
        user = await session.get(User, order.user_id)
        email = user.email if user is not None else None
    if not email:
        return None
    email_text = _customer_template_text(dispatch, order, None, fmt="plain")
    if email_text is None:
        return None
    return ComposedEmailNotification(
        email=email,
        subject=f"SHOPSTORE: обновление по заказу №{order.id}",
        text=email_text,
        order_id=order.id,
    )


# Собирает текст и chat_id для dispatch (без отправки).
async def compose_notification(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedNotification | None:
    if dispatch.channel == NotificationChannel.CUSTOMER:
        return await _compose_customer(session, dispatch)
    if dispatch.channel == NotificationChannel.ADMIN_ORDERS:
        return await _compose_admin_orders(session, dispatch)
    if dispatch.channel == NotificationChannel.SUPPORT_GROUP:
        return await _compose_support_group(session, dispatch)
    if dispatch.channel == NotificationChannel.SUPPORT_CUSTOMER:
        return await _compose_support_customer(session, dispatch)
    return None


# Собирает TG-сообщение клиенту по заказу.
async def _compose_customer(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedNotification | None:
    order_id = _require_int(dispatch.payload, "order_id")
    if order_id is None:
        return None
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.get_by_id(order_id)
    if not order:
        return None
    user = await session.get(User, order.user_id)
    identity = IdentityService(session)
    telegram_id = (
        await identity.get_telegram_id_for_user(user) if user is not None else None
    )
    if user is None or telegram_id is None:
        return None
    customer_name = user.name
    text = _customer_template_text(
        dispatch,
        order,
        customer_name,
        fmt="html",
        for_telegram=True,
    )
    if text is None:
        return None
    removed = dispatch.payload.get("removed_items")
    has_removed = isinstance(removed, list) and bool(removed)
    status_raw = dispatch.payload.get("order_status")
    order_status = (
        str(status_raw).strip()
        if status_raw is not None and str(status_raw).strip()
        else str(order.status or "")
    )
    cta = resolve_customer_notification_cta(
        dispatch.template,
        order_status=order_status,
        has_removed_items=has_removed,
    )
    reply_markup = (
        build_customer_webapp_cta_keyboard(cta[0], cta[1]) if cta is not None else None
    )
    return ComposedNotification(
        chat_id=int(telegram_id),
        text=text,
        parse_mode=CUSTOMER_ORDER_TG_PARSE_MODE,
        order_id=order_id,
        reply_markup=reply_markup,
    )


# Текст клиентского шаблона по ключу template.
def _customer_template_text(
    dispatch: NotificationDispatch,
    order: Order,
    customer_name: str | None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str | None:
    order_id = order.id
    payload = dispatch.payload
    template = dispatch.template
    if template == "customer.manual":
        raw = payload.get("message")
        if raw is None:
            raw = payload.get("custom_message")
        text = str(raw).strip() if raw is not None else ""
        if not text:
            return None
        return format_customer_manual_message(
            order_id,
            text,
            fmt=fmt,
            for_telegram=for_telegram,
        )
    if template == "order_status":
        custom = payload.get("custom_message")
        custom_text = str(custom).strip() if custom is not None else None
        if custom_text == "":
            custom_text = None
        status_raw = payload.get("order_status")
        if status_raw is not None and str(status_raw).strip():
            order_status = str(status_raw)
        else:
            order_status = str(order.status or "")
        if fmt == "plain" and custom_text:
            if is_customer_html_message(custom_text):
                return customer_status_message(
                    order_id,
                    order_status,
                    customer_name,
                    fmt="plain",
                )
            return custom_text
        if fmt == "plain":
            return customer_status_message(
                order_id,
                order_status,
                customer_name,
                fmt="plain",
            )
        return format_customer_telegram_delivery_text(
            custom_message=custom_text,
            order_id=order_id,
            order_status=order_status,
            customer_name=customer_name,
        )
    if template == "payment.received":
        return format_customer_payment_received_message(
            order_id, fmt=fmt, for_telegram=for_telegram
        )
    if template == "payment.late.received":
        return format_customer_payment_late_received_message(
            order_id, fmt=fmt, for_telegram=for_telegram
        )
    if template == "payment.awaiting":
        return format_customer_payment_awaiting_message(
            order_id, fmt=fmt, for_telegram=for_telegram
        )
    if template == "payment.failed":
        return format_customer_payment_failed_message(
            order_id, fmt=fmt, for_telegram=for_telegram
        )
    if template == "availability.confirmed":
        return format_customer_availability_confirmed_message(
            order_id,
            customer_name=customer_name,
            fmt=fmt,
            for_telegram=for_telegram,
        )
    if template == "availability.unavailable":
        return format_customer_availability_unavailable_message(
            order_id,
            customer_name=customer_name,
            fmt=fmt,
            for_telegram=for_telegram,
        )
    if template == "availability.check":
        removed = payload.get("removed_items")
        new_total = _decimal_or_none(payload.get("new_total"))
        if new_total is None or not isinstance(removed, list):
            return None
        removed_rows = [row for row in removed if isinstance(row, Mapping)]
        return format_customer_availability_check_message(
            order_id,
            removed_rows,
            new_total,
            customer_name=customer_name,
            fmt=fmt,
            for_telegram=for_telegram,
        )
    if template == "composition.changed":
        diff = payload.get("diff")
        new_total = _decimal_or_none(payload.get("new_total"))
        if new_total is None or not isinstance(diff, Mapping):
            return None
        return format_customer_composition_changed_message(
            order_id,
            diff,
            new_total,
            customer_name=customer_name,
            fmt=fmt,
            for_telegram=for_telegram,
        )
    return None


# Собирает TG-сообщение в группу заказов.
async def _compose_admin_orders(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedNotification | None:
    from src.core.config import settings
    from src.services.orders.order_service import OrderService

    chat_id = settings.TG_ORDERS_CHAT_ID
    if chat_id == 0:
        return None
    order_service = OrderService(session)
    order_id = _require_int(dispatch.payload, "order_id")
    if order_id is None:
        return None
    text = await _admin_orders_template_text(session, order_service, dispatch)
    if text is None:
        return None
    order_id = _require_int(dispatch.payload, "order_id")
    reply_markup = (
        admin_orders_reply_markup(dispatch.template, order_id)
        if order_id is not None
        else None
    )
    return ComposedNotification(
        chat_id=int(chat_id),
        text=text,
        parse_mode=OPS_ORDER_TG_PARSE_MODE,
        order_id=order_id,
        reply_markup=reply_markup,
    )


# Текст admin-шаблона для группы заказов.
async def _admin_orders_template_text(
    session: AsyncSession,
    order_service: "OrderService",
    dispatch: NotificationDispatch,
) -> str | None:
    order_id = _require_int(dispatch.payload, "order_id")
    if order_id is None:
        return None
    template = dispatch.template
    order = await order_service.order_crud.get_by_id(order_id)
    if template == "order.created":
        if not order:
            return None
        user = await session.get(User, order.user_id)
        payload = await order_service.build_supplier_order_payload(order_id)
        return format_order_created_message(
            payload=payload,
            user_email=user.email if user else None,
            promo_code_applied=order.promo_code_applied,
            for_telegram=True,
        )
    if template == "availability.review":
        if not order:
            return None
        if (
            str(order.availability_confirmation_status).lower()
            != AvailabilityConfirmationStatus.PENDING
        ):
            return None
        low_stock_items = await _admin_low_stock_items(order_service, order_id)
        return format_availability_review_message(
            order_id, low_stock_items, for_telegram=True
        )
    if template == "payment.accepted":
        attempt_id = _require_int(dispatch.payload, "attempt_id")
        attempt = (
            await order_service.order_crud.get_payment_attempt_by_id(attempt_id)
            if attempt_id is not None
            else None
        )
        user = await session.get(User, order.user_id) if order is not None else None
        customer_name: str | None = None
        if order is not None:
            first = str(order.first_name or "").strip()
            last = str(order.last_name or "").strip()
            customer_name = f"{first} {last}".strip() or None
        if not customer_name and user is not None and user.name:
            customer_name = str(user.name).strip() or None
        payment_provider = order.payment_provider if order is not None else None
        if not payment_provider and attempt is not None:
            payment_provider = attempt.provider
        payment_display = normalize_order_payment_from_attempt(
            payment_paid_at=order.payment_paid_at if order is not None else None,
            latest_attempt=attempt,
            payment_provider=payment_provider,
        )
        return format_payment_accepted_message(
            order_id=order_id,
            order_total=order.total_amount if order is not None else None,
            admin_url=admin_order_url(order_id),
            customer_name=customer_name,
            payment_method_label=payment_display.payment_method_label,
            for_telegram=True,
        )
    if template == "delivery.started":
        return format_order_delivery_started_message(
            order_id=order_id,
            admin_url=admin_order_url(order_id),
            for_telegram=True,
        )
    if template == "order.failed":
        return format_order_technical_problem_message(
            order_id=order_id,
            admin_url=admin_order_url(order_id),
            for_telegram=True,
        )
    if template == "payment.late":
        attempt_id = _require_int(dispatch.payload, "attempt_id")
        attempt = (
            await order_service.order_crud.get_payment_attempt_by_id(attempt_id)
            if attempt_id is not None
            else None
        )
        return format_late_payment_message(
            order_id=order_id,
            order_total=order.total_amount if order is not None else None,
            attempt_number=attempt.attempt_number if attempt is not None else None,
            provider_order_id=(
                attempt.provider_order_id if attempt is not None else None
            ),
            admin_url=admin_order_url(order_id),
            for_telegram=True,
        )
    if template == "payment.duplicate":
        attempt_id = _require_int(dispatch.payload, "attempt_id")
        attempt = (
            await order_service.order_crud.get_payment_attempt_by_id(attempt_id)
            if attempt_id is not None
            else None
        )
        return format_duplicate_payment_message(
            order_id=order_id,
            order_total=order.total_amount if order is not None else None,
            attempt_number=attempt.attempt_number if attempt is not None else None,
            admin_url=admin_order_url(order_id),
            for_telegram=True,
        )
    return None


# Позиции low-stock из event для admin availability review.
async def _admin_low_stock_items(
    order_service: "OrderService",
    order_id: int,
) -> list[dict[str, object]]:
    events = await order_service.order_crud.get_order_events(order_id)
    low_stock_items: list[dict[str, object]] = []
    for event in reversed(events):
        if event.event_type != "availability_confirmation_requested":
            continue
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        raw_items = payload.get("items")
        if isinstance(raw_items, list):
            low_stock_items = raw_items
        break
    order_items = await order_service.list_order_items_enriched(order_id)
    by_key = {(item.product_id, item.variant_id): item for item in order_items}
    product_ids = {item.product_id for item in order_items}
    products = await order_service.product_crud.get_by_ids(list(product_ids))
    products_map = {product.id: product for product in products}
    enriched: list[dict[str, object]] = []
    for raw in low_stock_items:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if not row.get("variant_label"):
            order_item = by_key.get((row.get("product_id"), row.get("variant_id")))
            if order_item is not None:
                row["variant_label"] = variant_label_from_options(
                    order_item.variant_option1,
                    order_item.variant_option2,
                    order_item.variant_option3,
                )
        if not row.get("category_l2"):
            product_id = row.get("product_id")
            if isinstance(product_id, int):
                product = products_map.get(product_id)
                if product is not None and product.category_l2:
                    row["category_l2"] = product.category_l2
        enriched.append(row)
    return enriched


# Собирает TG-сообщение в группу поддержки.
async def _compose_support_group(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedNotification | None:
    from src.core.config import settings

    chat_id = settings.TG_SUPPORT_CHAT_ID
    if chat_id == 0:
        return None
    ticket_id = _require_int(dispatch.payload, "ticket_id")
    if ticket_id is None:
        return None
    topic = str(dispatch.payload.get("topic") or "")
    body = str(dispatch.payload.get("body") or "")
    order_id = _require_int(dispatch.payload, "order_id")
    is_new_ticket = bool(dispatch.payload.get("is_new_ticket"))
    user_id = _require_int(dispatch.payload, "user_id")
    user = await session.get(User, user_id) if user_id is not None else None
    customer_label = await _support_customer_label(session, user)
    text = format_support_group_ticket_message(
        ticket_id=ticket_id,
        topic=topic,
        customer_label=customer_label,
        order_id=order_id,
        body=body,
        is_new_ticket=is_new_ticket,
        for_telegram=True,
    )
    return ComposedNotification(
        chat_id=int(chat_id),
        text=text,
        parse_mode=HTML,
        reply_markup=build_admin_support_ticket_keyboard(ticket_id),
    )


# Собирает TG-ответ поддержки клиенту.
async def _compose_support_customer(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> ComposedNotification | None:
    ticket_id = _require_int(dispatch.payload, "ticket_id")
    user_id = _require_int(dispatch.payload, "user_id")
    body = str(dispatch.payload.get("body") or "")
    if ticket_id is None or user_id is None:
        return None
    user = await session.get(User, user_id)
    if user is None:
        return None
    telegram_id = await IdentityService(session).get_telegram_id_for_user(user)
    if telegram_id is None:
        return None
    text = format_support_staff_reply_to_customer(ticket_id, body)
    return ComposedNotification(
        chat_id=int(telegram_id),
        text=text,
        parse_mode=CUSTOMER_ORDER_TG_PARSE_MODE,
    )


# Подпись клиента для TG группы поддержки.
async def _support_customer_label(session: AsyncSession, user: User | None) -> str:
    if user is None:
        return "—"
    identity = IdentityService(session)
    telegram_id = await identity.get_telegram_id_for_user(user)
    username = await identity.get_telegram_username_for_user(user)
    name = user.name or user.email or f"#{user.id}"
    if username:
        return f"{name} (@{username})"
    if telegram_id is not None:
        return f"{name} (TG {telegram_id})"
    return name


# int из payload или None.
def _require_int(payload: dict[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    return None


# Decimal из payload или None.
def _decimal_or_none(raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float, str)):
        return Decimal(str(raw))
    return None
