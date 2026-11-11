import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.notification_outbox_repo import NotificationOutboxRepo
from src.repositories.support_repo import CrudSupport
from src.services.notifications.dispatch import (
    NotificationDispatch,
    notification_dispatch_from_dict,
    notification_dispatch_to_dict,
)
from src.services.notifications.inline_dispatcher import InlineNotificationDispatcher

logger = logging.getLogger(__name__)


# Помечает staff-ответ поддержки как недоставленный после исчерпания retry.
async def _mark_support_reply_undelivered(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> None:
    if dispatch.template != "support.customer_reply":
        return
    message_id = dispatch.payload.get("support_message_id")
    if not isinstance(message_id, int):
        return
    await CrudSupport(session).set_message_telegram_delivered(message_id, False)


# Ставит уведомление в outbox в текущей транзакции.
async def schedule_notification(
    session: AsyncSession,
    dispatch: NotificationDispatch,
) -> bool:
    if not dispatch.idempotency_key:
        raise ValueError(
            "idempotency_key обязателен для outbox "
            f"({dispatch.channel}:{dispatch.template})"
        )
    dispatch_json = notification_dispatch_to_dict(dispatch)
    repo = NotificationOutboxRepo(session)
    return await repo.enqueue_dispatch(dispatch.idempotency_key, dispatch_json)


# Обрабатывает пачку outbox: claim → deliver → mark sent/failed.
async def process_outbox_batch(
    session: AsyncSession,
    limit: int = 50,
    dispatcher: InlineNotificationDispatcher | None = None,
) -> dict[str, int]:
    repo = NotificationOutboxRepo(session)
    stuck = await repo.reset_stuck_processing()
    deliverer = dispatcher or InlineNotificationDispatcher()
    rows = await repo.claim_pending_batch(limit)
    stats = {
        "stuck_reset": stuck,
        "claimed": len(rows),
        "sent": 0,
        "failed": 0,
        "requeued": 0,
    }
    for row in rows:
        dispatch = notification_dispatch_from_dict(row.dispatch_json)
        try:
            success = await deliverer.deliver(session, dispatch)
            if success:
                await repo.mark_sent(row.id)
                stats["sent"] += 1
            else:
                requeued = await repo.mark_failed(
                    row.id,
                    "TG уведомление не доставлено",
                    requeue=True,
                )
                if requeued:
                    stats["requeued"] += 1
                else:
                    await _mark_support_reply_undelivered(session, dispatch)
                    stats["failed"] += 1
        except Exception as exc:
            logger.exception(
                "Outbox worker: сбой доставки id=%s key=%s",
                row.id,
                row.idempotency_key,
            )
            requeued = await repo.mark_failed(row.id, str(exc), requeue=True)
            if requeued:
                stats["requeued"] += 1
            else:
                await _mark_support_reply_undelivered(session, dispatch)
                stats["failed"] += 1
    await session.commit()
    return stats
