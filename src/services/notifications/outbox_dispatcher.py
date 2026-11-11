import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order
from src.services.notifications.customer_dispatch import (
    apply_forced_channel,
    expand_customer_dispatch,
    resolve_order_notification_channels,
)
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from src.services.notifications.inline_dispatcher import InlineNotificationDispatcher
from src.services.notifications.outbox_service import schedule_notification

logger = logging.getLogger(__name__)


class OutboxNotificationDispatcher(InlineNotificationDispatcher):
    # Ставит dispatch в Postgres outbox (без TG в request path).
    async def enqueue(
        self,
        session: AsyncSession,
        dispatch: NotificationDispatch,
    ) -> bool:
        if dispatch.channel != NotificationChannel.CUSTOMER:
            return await schedule_notification(session, dispatch)
        forced_channel = dispatch.payload.get("force_channel")
        if forced_channel in {"telegram", "email"}:
            forced = apply_forced_channel(dispatch, str(forced_channel))
            return await schedule_notification(session, forced)
        order_id = dispatch.payload.get("order_id")
        if not isinstance(order_id, int):
            return await schedule_notification(session, dispatch)
        order = await session.get(Order, order_id)
        channels = resolve_order_notification_channels(order)
        scheduled = False
        for channel_dispatch in expand_customer_dispatch(dispatch, channels):
            scheduled = (
                await schedule_notification(session, channel_dispatch) or scheduled
            )
        return scheduled
