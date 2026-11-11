import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.user import User
from src.services.notifications import (
    NotificationChannel,
    NotificationDispatch,
    notification_dispatcher,
)

logger = logging.getLogger(__name__)


class SupportNotificationService:
    # Инициализирует TG-уведомления поддержки.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.dispatcher = notification_dispatcher()

    @property
    def telegram_client(self):
        return self.dispatcher.telegram_client

    # Отправляет уведомление в группу поддержки.
    async def notify_support_group(
        self,
        ticket_id: int,
        topic: str,
        user: User | None,
        order_id: int | None,
        body: str,
        is_new_ticket: bool,
        message_id: int | None = None,
    ) -> None:
        if settings.TG_SUPPORT_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
            logger.warning(
                "TG группа поддержки пропущена: нет TG_SUPPORT_CHAT_ID/TG_BOT_SHOP "
                "(ticket_id=%s)",
                ticket_id,
            )
            return
        msg_key = message_id if message_id is not None else ticket_id
        dispatch = NotificationDispatch(
            channel=NotificationChannel.SUPPORT_GROUP,
            template="support.group_ticket",
            payload={
                "ticket_id": ticket_id,
                "topic": topic,
                "user_id": user.id if user is not None else None,
                "order_id": order_id,
                "body": body,
                "is_new_ticket": is_new_ticket,
            },
            created_by="system",
            idempotency_key=f"support:group:ticket:{ticket_id}:msg:{msg_key}",
        )
        success = await self.dispatcher.enqueue(self.session, dispatch)
        if not success:
            logger.warning(
                "TG группа поддержки: дубликат outbox (ticket_id=%s)",
                ticket_id,
            )

    # Отправляет ответ staff клиенту в Telegram.
    async def notify_customer_staff_reply(
        self,
        user: User | None,
        ticket_id: int,
        body: str,
        message_id: int | None = None,
    ) -> bool:
        if not settings.TG_BOT_SHOP or user is None:
            return False
        msg_key = message_id if message_id is not None else ticket_id
        dispatch = NotificationDispatch(
            channel=NotificationChannel.SUPPORT_CUSTOMER,
            template="support.customer_reply",
            payload={
                "ticket_id": ticket_id,
                "user_id": user.id,
                "body": body,
                "support_message_id": message_id,
            },
            created_by="system",
            idempotency_key=f"support:customer:ticket:{ticket_id}:msg:{msg_key}",
        )
        return await self.dispatcher.enqueue(self.session, dispatch)
