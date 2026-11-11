import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.integrations.smtp_client import send_plain_email
from src.integrations.telegram_client import TelegramClient
from src.models.order import Order
from src.repositories.order_repo import CrudOrder
from src.repositories.support_repo import CrudSupport
from src.services.notifications.composer import (
    compose_email_notification,
    compose_notification,
)
from src.services.notifications.customer_dispatch import (
    apply_forced_channel,
    expand_customer_dispatch,
    resolve_order_notification_channels,
)
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)

logger = logging.getLogger(__name__)


class InlineNotificationDispatcher:
    def __init__(self, telegram_client: TelegramClient | None = None) -> None:
        self.telegram_client = telegram_client or TelegramClient(settings.TG_BOT_SHOP)

    # Кладёт уведомление в очередь; inline — сразу deliver.
    async def enqueue(
        self,
        session: AsyncSession,
        dispatch: NotificationDispatch,
    ) -> bool:
        forced_channel = dispatch.payload.get("force_channel")
        if dispatch.channel == NotificationChannel.CUSTOMER and forced_channel in {
            "email",
            "telegram",
        }:
            dispatch = apply_forced_channel(dispatch, str(forced_channel))
        if dispatch.channel == NotificationChannel.CUSTOMER and not forced_channel:
            order_id = dispatch.payload.get("order_id")
            if isinstance(order_id, int):
                order = await session.get(Order, order_id)
                channels = resolve_order_notification_channels(order)
                delivered = False
                for channel_dispatch in expand_customer_dispatch(dispatch, channels):
                    delivered = (
                        await self.deliver(session, channel_dispatch) or delivered
                    )
                return delivered
        return await self.deliver(session, dispatch)

    # Собирает текст и отправляет TG (worker вызывает этот метод).
    async def deliver(
        self,
        session: AsyncSession,
        dispatch: NotificationDispatch,
    ) -> bool:
        if dispatch.channel == NotificationChannel.EMAIL:
            return await self._deliver_email(session, dispatch)
        if not settings.TG_BOT_SHOP:
            return False
        context = f"{dispatch.channel.value}:{dispatch.template}"
        order_id = dispatch.payload.get("order_id")
        order_id_int = order_id if isinstance(order_id, int) else None
        composed_order_id: int | None = order_id_int
        try:
            composed = await compose_notification(session, dispatch)
            if composed is None:
                return False
            composed_order_id = composed.order_id
            send_result = await self.telegram_client.send_message(
                chat_id=composed.chat_id,
                text=composed.text,
                parse_mode=composed.parse_mode,
                reply_markup=composed.reply_markup,
            )
            if not send_result.ok:
                logger.warning(
                    "TG уведомление не доставлено (%s order_id=%s)",
                    context,
                    composed.order_id,
                )
                if not notification_uses_outbox():
                    await self._apply_support_staff_reply_delivery(
                        session, dispatch, False
                    )
                return False
            if dispatch.record_order_event and composed.order_id is not None:
                await self._record_order_event(
                    session,
                    composed.order_id,
                    dispatch,
                    composed.text,
                )
            await self._apply_support_staff_reply_delivery(
                session, dispatch, send_result.ok
            )
            return True
        except Exception:
            logger.exception(
                "TG уведомление: сбой отправки (%s order_id=%s)",
                context,
                composed_order_id,
            )
            if not notification_uses_outbox():
                await self._apply_support_staff_reply_delivery(session, dispatch, False)
            return False

    async def _deliver_email(
        self,
        session: AsyncSession,
        dispatch: NotificationDispatch,
    ) -> bool:
        composed = await compose_email_notification(session, dispatch)
        if composed is None:
            return False
        await send_plain_email(composed.email, composed.subject, composed.text)
        if dispatch.record_order_event:
            await self._record_order_event(
                session,
                composed.order_id,
                dispatch,
                composed.text,
            )
        return True

    # Обновляет telegram_delivered для staff-ответа поддержки.
    async def _apply_support_staff_reply_delivery(
        self,
        session: AsyncSession,
        dispatch: NotificationDispatch,
        delivered: bool,
    ) -> None:
        if dispatch.template != "support.customer_reply":
            return
        message_id = dispatch.payload.get("support_message_id")
        if not isinstance(message_id, int):
            return
        await CrudSupport(session).set_message_telegram_delivered(message_id, delivered)

    # Пишет order_event после успешной TG-доставки клиенту.
    async def _record_order_event(
        self,
        session: AsyncSession,
        order_id: int,
        dispatch: NotificationDispatch,
        text: str,
    ) -> None:
        record = dispatch.record_order_event
        if record is None:
            return
        order_crud = CrudOrder(session=session, model=Order)
        channel_value = (
            "telegram"
            if dispatch.channel == NotificationChannel.CUSTOMER
            else dispatch.channel.value
        )
        payload: dict[str, object] = {
            "message": text,
            "channel": channel_value,
            "template": dispatch.template,
        }
        if dispatch.idempotency_key:
            payload["idempotency_key"] = dispatch.idempotency_key
        if record.payload_json:
            payload.update(record.payload_json)
        await order_crud.create_order_event(
            order_id=order_id,
            event_type=record.event_type,
            event_message=record.event_message,
            created_by=dispatch.created_by,
            payload_json=payload,
        )
        order = await order_crud.get_by_id(order_id)
        if order is not None:
            await order_crud.commit_order(order)


# True, если уведомления идут через outbox (не inline deliver в request path).
def notification_uses_outbox() -> bool:
    mode = os.getenv("NOTIFICATION_MODE", settings.NOTIFICATION_MODE).strip().lower()
    if os.getenv("NOTIFICATION_INLINE", "").strip() in {"1", "true", "yes"}:
        return False
    return mode != "inline"


# Возвращает dispatcher: outbox (default) или inline (dev).
def notification_dispatcher() -> InlineNotificationDispatcher:
    mode = os.getenv("NOTIFICATION_MODE", settings.NOTIFICATION_MODE).strip().lower()
    if os.getenv("NOTIFICATION_INLINE", "").strip() in {"1", "true", "yes"}:
        mode = "inline"
    if mode == "inline":
        return InlineNotificationDispatcher()
    from src.services.notifications.outbox_dispatcher import (
        OutboxNotificationDispatcher,
    )

    return OutboxNotificationDispatcher()
