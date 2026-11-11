import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.content.admin_texts import (
    delivered_alert_snapshot_hash,
    format_admin_delivered_alert_message,
    format_order_completed_alert_message,
    format_placed_delivered_alert_message,
    order_completed_alert_snapshot_hash,
    placed_delivered_alert_snapshot_hash,
)
from src.content.telegram_html import OPS_ORDER_TG_PARSE_MODE
from src.core.config import settings
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderStatus,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.notifications import (
    NotificationChannel,
    NotificationDispatch,
    notification_dispatcher,
)
from src.services.notifications.admin_keyboards import (
    build_admin_delivered_alert_keyboard,
    build_admin_order_keyboard,
    build_placed_delivered_alert_keyboard,
)
from src.services.orders.supplier_orders import normalize_legacy_supplier_order_id
from src.services.orders.supplier_tracking_shape import (
    delivered_source_from_events,
    ensure_supplier_tracking_shape,
    has_terminal_delivered_signal,
)
from src.utils.datetime_fmt import utc_now_naive

logger = logging.getLogger(__name__)

ADMIN_DELIVERED_ALERT_KEY = "admin_delivered_alert"
ADMIN_COMPLETED_ALERT_KEY = "admin_completed_alert"
SHIPMENT_ALERT_CLAIM_SECONDS = 120


# Проверить, нужно ли повторно отправить оповещение о доставке заказа.
def delivered_alert_needs_retry(order: Order) -> bool:
    tracking_data = dict(order.supplier_tracking_json or {})
    alert_state = _read_admin_delivered_alert_state(tracking_data)
    if alert_state.get("pending_retry"):
        return True
    if not has_terminal_delivered_signal(tracking_data):
        return False
    return not _coerce_int(alert_state.get("message_id"))


# Проверить, нужно ли повторно отправить оповещение о доставке заказа.
def delivered_alert_retry_is_due(order: Order, now: datetime | None = None) -> bool:
    tracking_data = dict(order.supplier_tracking_json or {})
    alert_state = _read_admin_delivered_alert_state(tracking_data)
    if not alert_state.get("pending_retry"):
        return False
    next_raw = alert_state.get("next_retry_at")
    if not isinstance(next_raw, str) or not next_raw.strip():
        return True
    try:
        next_at = datetime.fromisoformat(next_raw)
    except ValueError:
        return True
    current = now or utc_now_naive()
    return current >= next_at


# Запланировать повторную отправку оповещения о доставке заказа.
def schedule_delivered_alert_retry(order: Order, now: datetime) -> None:
    tracking_data = ensure_supplier_tracking_shape(
        dict(order.supplier_tracking_json or {})
    )
    alert_state = _read_admin_delivered_alert_state(tracking_data)
    alert_state["pending_retry"] = True
    alert_state["next_retry_at"] = (
        now + timedelta(minutes=settings.DELIVERED_ALERT_RETRY_MINUTES)
    ).isoformat()
    tracking_data[ADMIN_DELIVERED_ALERT_KEY] = alert_state
    order.supplier_tracking_json = tracking_data


class AdminNotificationService:
    # Инициализирует сервис TG-уведомлений в группу заказов.
    def __init__(self, session: AsyncSession) -> None:
        from src.services.orders.order_service import OrderService

        self.session = session
        self.order_service = OrderService(session)
        self.dispatcher = notification_dispatcher()

    @property
    def telegram_client(self):
        return self.dispatcher.telegram_client

    # Отправляет dispatch в группу заказов (best-effort).
    async def _send_to_orders_group(
        self,
        dispatch: NotificationDispatch,
        context: str,
    ) -> None:
        if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
            order_id = dispatch.payload.get("order_id")
            logger.warning(
                "TG группа заказов пропущена: нет TG_ORDERS_CHAT_ID "
                "или TG_BOT_SHOP (%s order_id=%s)",
                context,
                order_id,
            )
            return
        success = await self.dispatcher.enqueue(self.session, dispatch)
        if not success:
            logger.warning(
                "TG группа заказов: сообщение не доставлено (%s order_id=%s)",
                context,
                dispatch.payload.get("order_id"),
            )

    # Отправляет уведомление о новом заказе в группу заказов.
    async def send_order_created(self, order_id: int) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="order.created",
                payload={"order_id": order_id},
                created_by="system",
                idempotency_key=f"admin:order.created:order:{order_id}",
            ),
            "new_order",
        )

    # Отправляет уведомление о проверке наличия в группу заказов.
    async def send_availability_review_required(self, order_id: int) -> None:
        order = await self.order_service.order_crud.get_by_id(order_id)
        if not order:
            return
        if (
            str(order.availability_confirmation_status).lower()
            != AvailabilityConfirmationStatus.PENDING
        ):
            return
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="availability.review",
                payload={"order_id": order_id},
                created_by="system",
                idempotency_key=f"admin:availability.review:order:{order_id}",
            ),
            "availability_review",
        )

    # Уведомляет группу заказов об успешной оплате.
    async def send_order_payment_accepted(
        self,
        order_id: int,
        attempt_id: int,
    ) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="payment.accepted",
                payload={"order_id": order_id, "attempt_id": attempt_id},
                created_by="sbp",
                idempotency_key=(
                    f"admin:payment.accepted:order:{order_id}:attempt:{attempt_id}"
                ),
            ),
            "payment_accepted",
        )

    # Уведомляет группу заказов о передаче заказа в доставку.
    async def send_order_delivery_started(self, order_id: int) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="delivery.started",
                payload={"order_id": order_id},
                created_by="system",
                idempotency_key=f"admin:delivery.started:order:{order_id}",
            ),
            "delivery_started",
        )

    # Уведомляет группу заказов о технической проблеме с заказом.
    async def send_order_technical_problem(self, order_id: int) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="order.failed",
                payload={"order_id": order_id},
                created_by="system",
                idempotency_key=f"admin:order.failed:order:{order_id}",
            ),
            "order_failed",
        )

    # Уведомляет группу заказов о поздней оплате после автоотмены.
    async def send_late_payment_after_auto_cancel(
        self,
        order_id: int,
        attempt_id: int,
    ) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="payment.late",
                payload={"order_id": order_id, "attempt_id": attempt_id},
                created_by="sbp",
                idempotency_key=(
                    f"admin:payment.late:order:{order_id}:attempt:{attempt_id}"
                ),
            ),
            "late_payment",
        )

    # Уведомляет группу заказов о повторной успешной оплате.
    async def send_payment_duplicate(
        self,
        order_id: int,
        attempt_id: int,
    ) -> None:
        await self._send_to_orders_group(
            NotificationDispatch(
                channel=NotificationChannel.ADMIN_ORDERS,
                template="payment.duplicate",
                payload={"order_id": order_id, "attempt_id": attempt_id},
                created_by="sbp",
                idempotency_key=(
                    f"admin:payment.duplicate:order:{order_id}:attempt:{attempt_id}"
                ),
            ),
            "payment_duplicate",
        )

    # Legacy order-level A для заказов без Shipment.
    async def sync_delivered_alert(
        self,
        order_id: int,
        checked_at: datetime,
    ) -> bool:
        if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
            return True

        locked = await self.order_service.order_crud.get_by_id_for_update(order_id)
        if locked is None:
            return False

        # Per-shipment A живёт в Shipment.delivered_alert; сюда не дублируем.
        if await self.order_service.order_crud.list_shipments_for_order(order_id):
            await self.session.commit()
            return True

        current_status = str(locked.status or "").lower()
        if current_status != OrderStatus.DELIVERY:
            return False
        else:
            tracking = dict(locked.supplier_tracking_json or {})
            if not has_terminal_delivered_signal(
                tracking
            ) and not delivered_alert_needs_retry(locked):
                return False

        tracking_data = ensure_supplier_tracking_shape(
            dict(locked.supplier_tracking_json or {})
        )
        (
            snapshot_hash,
            parcellab_confirmed,
            parcellab_at,
            dhl_confirmed,
            dhl_at,
        ) = _delivered_alert_snapshot(tracking_data)

        alert_state = _read_admin_delivered_alert_state(tracking_data)
        stored_hash = str(alert_state.get("snapshot_hash") or "")
        chat_id = _coerce_int(alert_state.get("chat_id")) or settings.TG_ORDERS_CHAT_ID
        message_id = _coerce_int(alert_state.get("message_id"))
        if message_id and stored_hash == snapshot_hash:
            return True

        text = format_admin_delivered_alert_message(
            order_id=locked.id,
            supplier_order_id=locked.supplier_order_id,
            tracking_id=locked.supplier_tracking_id,
            parcellab_confirmed=parcellab_confirmed,
            parcellab_at=parcellab_at,
            dhl_confirmed=dhl_confirmed,
            dhl_at=dhl_at,
            checked_at=checked_at,
            for_telegram=True,
        )
        keyboard = build_admin_delivered_alert_keyboard(locked.id)

        next_message_id = message_id
        tg_ok = False
        if message_id:
            edited = await self.telegram_client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=OPS_ORDER_TG_PARSE_MODE,
                reply_markup=keyboard,
            )
            if edited:
                tg_ok = True
            else:
                sent = await self.telegram_client.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=OPS_ORDER_TG_PARSE_MODE,
                    reply_markup=keyboard,
                )
                if sent.ok and sent.message_id is not None:
                    next_message_id = sent.message_id
                    tg_ok = True
        else:
            sent = await self.telegram_client.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=OPS_ORDER_TG_PARSE_MODE,
                reply_markup=keyboard,
            )
            if sent.ok and sent.message_id is not None:
                next_message_id = sent.message_id
                tg_ok = True

        if not tg_ok:
            logger.warning(
                "ТГ: оповещение о доставке не отправлено (order_id=%s)",
                order_id,
            )
            schedule_delivered_alert_retry(locked, now=checked_at)
            await self.session.commit()
            return False

        tracking_data = ensure_supplier_tracking_shape(
            dict(locked.supplier_tracking_json or {})
        )
        alert_state = _read_admin_delivered_alert_state(tracking_data)
        if (
            _coerce_int(alert_state.get("message_id"))
            and str(alert_state.get("snapshot_hash") or "") == snapshot_hash
        ):
            await self.session.commit()
            return True

        tracking_data[ADMIN_DELIVERED_ALERT_KEY] = {
            "chat_id": chat_id,
            "message_id": next_message_id,
            "snapshot_hash": snapshot_hash,
            "pending_retry": False,
            "next_retry_at": None,
        }
        locked.supplier_tracking_json = tracking_data
        if (
            str(locked.status or "").lower() == OrderStatus.DELIVERY
            and has_terminal_delivered_signal(tracking_data)
            and not delivered_alert_needs_retry(locked)
        ):
            locked.supplier_tracking_next_check_at = None
        await self.session.commit()
        return True


# Снимок delivered alert из актуального tracking JSON.
def _delivered_alert_snapshot(
    tracking_data: dict[str, Any],
) -> tuple[str, bool, str | None, bool, str | None]:
    parcellab_confirmed, parcellab_at = delivered_source_from_events(
        list(tracking_data.get("supplier_events") or [])
    )
    dhl_confirmed, dhl_at = delivered_source_from_events(
        list(tracking_data.get("carrier_events") or [])
    )
    snapshot_hash = delivered_alert_snapshot_hash(
        parcellab_confirmed=parcellab_confirmed,
        parcellab_at=parcellab_at,
        dhl_confirmed=dhl_confirmed,
        dhl_at=dhl_at,
    )
    return (
        snapshot_hash,
        parcellab_confirmed,
        parcellab_at,
        dhl_confirmed,
        dhl_at,
    )


# Чтение состояния оповещения о доставке заказа из tracking_data.
def _read_admin_delivered_alert_state(
    tracking_data: dict[str, Any],
) -> dict[str, Any]:
    raw = tracking_data.get(ADMIN_DELIVERED_ALERT_KEY)
    if isinstance(raw, dict):
        return raw
    return {}


# Преобразование значения в целое число.
def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


# После sync трека: Order-level TG только для legacy без Shipment.
async def sync_delivered_alert_after_tracking_check(
    session: AsyncSession,
    order: Order,
    checked_at: datetime,
) -> None:
    status = str(order.status or "").lower()
    if status != OrderStatus.DELIVERY:
        return
    crud = CrudOrder(session=session, model=Order)
    if await crud.list_shipments_for_order(int(order.id)):
        return
    tracking = dict(order.supplier_tracking_json or {})
    if not has_terminal_delivered_signal(tracking) and not delivered_alert_needs_retry(
        order
    ):
        return
    await AdminNotificationService(session).sync_delivered_alert(
        order.id,
        checked_at=checked_at,
    )


# Состояние delivered_alert JSONB одной посылки.
def _read_shipment_delivered_alert_state(row: Shipment) -> dict[str, Any]:
    raw = row.delivered_alert
    if isinstance(raw, dict):
        return dict(raw)
    return {}


# TP с header SO; CJ с Shipment.supplier_tracking_number.
def _placed_alert_tp_cj(
    row: Shipment, header: SupplierOrder | None
) -> tuple[str | None, str | None]:
    tp: str | None = None
    if header is not None:
        tp = normalize_legacy_supplier_order_id(header.external_id) or None
        if not tp:
            raw = str(header.external_id or "").strip()
            tp = raw or None
    cj = str(row.supplier_tracking_number or "").strip() or None
    return tp, cj


# A для delivered Shipment, пока заказ delivery или уже completed.
def _shipment_delivered_alert_eligible(row: Shipment, order: Order | None) -> bool:
    if order is None:
        return False
    # A про посылку, не про заказ. Finalize может обогнать TG; cancelled — нет.
    order_status = str(order.status or "").lower()
    if order_status not in {OrderStatus.DELIVERY, OrderStatus.COMPLETED}:
        return False
    return str(row.status or "") == ShipmentStatus.DELIVERED


# Нужно ли повторить TG для этой посылки.
def shipment_delivered_alert_needs_retry(row: Shipment) -> bool:
    alert_state = _read_shipment_delivered_alert_state(row)
    if alert_state.get("pending_retry"):
        return True
    if str(row.status or "") != ShipmentStatus.DELIVERED:
        return False
    return not _coerce_int(alert_state.get("message_id"))


# Due-проверка retry placed delivered alert.
def shipment_delivered_alert_retry_is_due(
    row: Shipment, now: datetime | None = None
) -> bool:
    alert_state = _read_shipment_delivered_alert_state(row)
    if not alert_state.get("pending_retry"):
        return False
    next_at = _parse_iso_datetime(alert_state.get("next_retry_at"))
    current = now or utc_now_naive()
    if next_at is None:
        return True
    return current >= next_at


# Пишет pending_retry на Shipment.delivered_alert.
def schedule_shipment_delivered_alert_retry(row: Shipment, now: datetime) -> None:
    alert_state = _read_shipment_delivered_alert_state(row)
    alert_state["pending_retry"] = True
    alert_state["next_retry_at"] = (
        now + timedelta(minutes=settings.DELIVERED_ALERT_RETRY_MINUTES)
    ).isoformat()
    row.delivered_alert = alert_state


# ISO datetime из JSONB; битые строки → None.
def _parse_iso_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# True если другой воркер уже claim'нул этот snapshot и TTL не истёк.
def _shipment_send_claim_is_active(
    alert_state: dict[str, Any], snapshot_hash: str, now: datetime
) -> bool:
    if str(alert_state.get("send_claimed_hash") or "") != snapshot_hash:
        return False
    claimed_at = _parse_iso_datetime(alert_state.get("send_claimed_at"))
    if claimed_at is None:
        return False
    return now < claimed_at + timedelta(seconds=SHIPMENT_ALERT_CLAIM_SECONDS)


# Claim до Telegram: pending_retry на TTL, чтобы crash не потерял retry.
def _claim_shipment_delivered_send(
    row: Shipment, snapshot_hash: str, now: datetime
) -> None:
    alert_state = _read_shipment_delivered_alert_state(row)
    alert_state["send_claimed_at"] = now.isoformat()
    alert_state["send_claimed_hash"] = snapshot_hash
    alert_state["pending_retry"] = True
    alert_state["next_retry_at"] = (
        now + timedelta(seconds=SHIPMENT_ALERT_CLAIM_SECONDS)
    ).isoformat()
    row.delivered_alert = alert_state


# Грузит Shipment + Order + SO; for_update блокирует посылку.
async def _load_shipment_alert_context(
    session: AsyncSession,
    shipment_id: int,
    for_update: bool,
) -> tuple[Shipment, Order | None, SupplierOrder | None] | None:
    crud = CrudOrder(session=session, model=Order)
    if for_update:
        row = await crud.get_shipment_by_id_for_update(shipment_id)
    else:
        row = await crud.get_shipment_by_id(shipment_id)
    if row is None:
        return None
    order = await crud.get_by_id(int(row.order_id))
    header: SupplierOrder | None = None
    if row.supplier_order_id is not None:
        header = await session.get(SupplierOrder, int(row.supplier_order_id))
    return row, order, header


# Send или edit TG placed delivered alert; возвращает (ok, message_id).
async def _send_placed_delivered_telegram(
    chat_id: int,
    message_id: int | None,
    text: str,
    keyboard: dict[str, object] | None,
) -> tuple[bool, int | None]:
    client = notification_dispatcher().telegram_client
    if message_id:
        edited = await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=OPS_ORDER_TG_PARSE_MODE,
            reply_markup=keyboard,
        )
        if edited:
            return True, message_id
        sent = await client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=OPS_ORDER_TG_PARSE_MODE,
            reply_markup=keyboard,
        )
        if sent.ok and sent.message_id is not None:
            return True, sent.message_id
        return False, message_id
    sent = await client.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=OPS_ORDER_TG_PARSE_MODE,
        reply_markup=keyboard,
    )
    if sent.ok and sent.message_id is not None:
        return True, sent.message_id
    return False, None


# PLACED: TG delivered alert одной посылки. I/O вне DB session.
async def sync_shipment_delivered_alert(
    shipment_id: int,
    checked_at: datetime,
    session_factory: (
        Callable[[], AbstractAsyncContextManager[AsyncSession]] | None
    ) = None,
) -> bool:
    if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
        return True
    factory = session_factory or async_session_maker

    async with factory() as session:
        ctx = await _load_shipment_alert_context(session, shipment_id, for_update=True)
        if ctx is None:
            await session.commit()
            return False
        row, order, header = ctx
        if not _shipment_delivered_alert_eligible(row, order):
            await session.commit()
            return False
        tp, cj = _placed_alert_tp_cj(row, header)
        snapshot_hash = placed_delivered_alert_snapshot_hash(tp, cj)
        alert_state = _read_shipment_delivered_alert_state(row)
        chat_id = _coerce_int(alert_state.get("chat_id")) or settings.TG_ORDERS_CHAT_ID
        message_id = _coerce_int(alert_state.get("message_id"))
        stored_hash = str(alert_state.get("snapshot_hash") or "")
        order_id = int(row.order_id)
        if message_id and stored_hash == snapshot_hash:
            await session.commit()
            return True
        if _shipment_send_claim_is_active(alert_state, snapshot_hash, checked_at):
            await session.commit()
            return True
        _claim_shipment_delivered_send(row, snapshot_hash, checked_at)
        await session.commit()

    text = format_placed_delivered_alert_message(
        order_id=order_id,
        tp=tp,
        cj=cj,
        checked_at=checked_at,
        for_telegram=True,
    )
    keyboard = build_placed_delivered_alert_keyboard(order_id, cj)
    tg_ok, next_message_id = await _send_placed_delivered_telegram(
        chat_id, message_id, text, keyboard
    )

    async with factory() as session:
        ctx = await _load_shipment_alert_context(session, shipment_id, for_update=True)
        if ctx is None:
            await session.commit()
            return False
        row, order, header = ctx
        if not _shipment_delivered_alert_eligible(row, order):
            await session.commit()
            return False
        tp, cj = _placed_alert_tp_cj(row, header)
        snapshot_hash = placed_delivered_alert_snapshot_hash(tp, cj)
        alert_state = _read_shipment_delivered_alert_state(row)
        stored_hash = str(alert_state.get("snapshot_hash") or "")
        stored_message_id = _coerce_int(alert_state.get("message_id"))
        if not tg_ok:
            logger.warning(
                "ТГ: оповещение о доставке посылки не отправлено (shipment_id=%s)",
                shipment_id,
            )
            schedule_shipment_delivered_alert_retry(row, now=checked_at)
            await session.commit()
            return False
        if stored_message_id and stored_hash == snapshot_hash:
            await session.commit()
            return True
        persist_chat_id = (
            _coerce_int(alert_state.get("chat_id")) or settings.TG_ORDERS_CHAT_ID
        )
        row.delivered_alert = {
            "chat_id": persist_chat_id,
            "message_id": next_message_id,
            "snapshot_hash": snapshot_hash,
            "pending_retry": False,
            "next_retry_at": None,
            "send_claimed_at": None,
            "send_claimed_hash": None,
        }
        await session.commit()
        return True


# Состояние C JSONB на Order.supplier_tracking_json.
def _read_admin_completed_alert_state(tracking: dict[str, Any]) -> dict[str, Any]:
    raw = tracking.get(ADMIN_COMPLETED_ALERT_KEY)
    if isinstance(raw, dict):
        return dict(raw)
    return {}


# Пары TP/CJ для C: Shipment + SO.external_id, иначе legacy колонки Order.
async def _completion_parcels_for_order(
    session: AsyncSession, order: Order
) -> list[tuple[str | None, str | None]]:
    crud = CrudOrder(session=session, model=Order)
    shipments = await crud.list_shipments_for_order(int(order.id))
    headers = await crud.list_placed_supplier_orders(int(order.id))
    header_by_id = {int(row.id): row for row in headers}
    parcels: list[tuple[str | None, str | None]] = []
    for row in shipments:
        header = None
        if row.supplier_order_id is not None:
            header = header_by_id.get(int(row.supplier_order_id))
        tp, cj = _placed_alert_tp_cj(row, header)
        parcels.append((tp, cj))
    if parcels:
        return parcels
    tp = normalize_legacy_supplier_order_id(order.supplier_order_id) or None
    if not tp:
        raw_tp = str(order.supplier_order_id or "").strip()
        tp = raw_tp or None
    cj = str(order.supplier_tracking_id or "").strip() or None
    if tp is None and cj is None:
        return []
    return [(tp, cj)]


# C: Order-level admin TG после COMPLETED. Не edit A. I/O вне DB session.
async def sync_order_completed_admin_alert(
    order_id: int,
    checked_at: datetime,
    session_factory: (
        Callable[[], AbstractAsyncContextManager[AsyncSession]] | None
    ) = None,
) -> bool:
    if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
        return True
    factory = session_factory or async_session_maker

    async with factory() as session:
        crud = CrudOrder(session=session, model=Order)
        locked = await crud.get_by_id_for_update(order_id)
        if locked is None:
            await session.commit()
            return False
        if str(locked.status or "").lower() != OrderStatus.COMPLETED:
            await session.commit()
            return False
        parcels = await _completion_parcels_for_order(session, locked)
        snapshot_hash = order_completed_alert_snapshot_hash(parcels)
        tracking = dict(locked.supplier_tracking_json or {})
        alert_state = _read_admin_completed_alert_state(tracking)
        chat_id = _coerce_int(alert_state.get("chat_id")) or settings.TG_ORDERS_CHAT_ID
        message_id = _coerce_int(alert_state.get("message_id"))
        stored_hash = str(alert_state.get("snapshot_hash") or "")
        if message_id and stored_hash == snapshot_hash:
            await session.commit()
            return True
        await session.commit()

    text = format_order_completed_alert_message(
        order_id=order_id,
        parcels=parcels,
        checked_at=checked_at,
        for_telegram=True,
    )
    keyboard = build_admin_order_keyboard(order_id)
    client = notification_dispatcher().telegram_client
    sent = await client.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=OPS_ORDER_TG_PARSE_MODE,
        reply_markup=keyboard,
    )
    tg_ok = bool(sent.ok and sent.message_id is not None)
    next_message_id = sent.message_id if tg_ok else None

    async with factory() as session:
        crud = CrudOrder(session=session, model=Order)
        locked = await crud.get_by_id_for_update(order_id)
        if locked is None:
            await session.commit()
            return False
        tracking = ensure_supplier_tracking_shape(
            dict(locked.supplier_tracking_json or {})
        )
        alert_state = _read_admin_completed_alert_state(tracking)
        stored_hash = str(alert_state.get("snapshot_hash") or "")
        stored_message_id = _coerce_int(alert_state.get("message_id"))
        if stored_message_id and stored_hash == snapshot_hash:
            await session.commit()
            return True
        if not tg_ok:
            logger.warning(
                "ТГ: оповещение о завершении заказа не отправлено (order_id=%s)",
                order_id,
            )
            await session.commit()
            return False
        tracking[ADMIN_COMPLETED_ALERT_KEY] = {
            "chat_id": chat_id,
            "message_id": next_message_id,
            "snapshot_hash": snapshot_hash,
        }
        locked.supplier_tracking_json = tracking
        await session.commit()
        return True
