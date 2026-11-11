import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification_outbox import NotificationOutbox, NotificationOutboxStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


# Секунды backoff перед повторной попыткой доставки.
def _backoff_seconds(attempts: int) -> int:
    base = 30
    return min(base * (2 ** max(attempts - 1, 0)), 3600)


class NotificationOutboxRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Вставляет dispatch в outbox; False при конфликте idempotency_key.
    async def enqueue_dispatch(
        self,
        idempotency_key: str,
        dispatch_json: dict,
    ) -> bool:
        stmt = (
            insert(NotificationOutbox)
            .values(
                idempotency_key=idempotency_key,
                dispatch_json=dispatch_json,
                status=NotificationOutboxStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        result = await self.session.execute(stmt)
        return bool(result.rowcount)

    # True, если строка outbox с таким idempotency_key уже есть.
    async def exists_idempotency_key(self, idempotency_key: str) -> bool:
        stmt = (
            select(NotificationOutbox.id)
            .where(NotificationOutbox.idempotency_key == idempotency_key)
            .limit(1)
        )
        row = await self.session.scalar(stmt)
        return row is not None

    # Захватывает пачку pending-строк для worker (SKIP LOCKED).
    async def claim_pending_batch(self, limit: int) -> list[NotificationOutbox]:
        now = datetime.now(UTC)
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationOutboxStatus.PENDING,
                or_(
                    NotificationOutbox.locked_at.is_(None),
                    NotificationOutbox.locked_at <= now,
                ),
            )
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self.session.scalars(stmt)).all())
        for row in rows:
            row.status = NotificationOutboxStatus.PROCESSING
            row.locked_at = now
        if rows:
            await self.session.flush()
        return rows

    # Помечает строку outbox как успешно доставленную.
    async def mark_sent(self, row_id: int) -> None:
        now = datetime.now(UTC)
        await self.session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == row_id)
            .values(
                status=NotificationOutboxStatus.SENT,
                processed_at=now,
                locked_at=None,
            )
        )

    # Помечает ошибку доставки; requeue — вернуть в pending с backoff.
    async def mark_failed(
        self,
        row_id: int,
        error: str,
        requeue: bool = False,
    ) -> bool:
        now = datetime.now(UTC)
        row = await self.session.get(NotificationOutbox, row_id)
        if row is None:
            return False
        attempts = row.attempts + 1
        truncated = error[:4000] if error else None
        if requeue and attempts < MAX_ATTEMPTS:
            backoff = timedelta(seconds=_backoff_seconds(attempts))
            await self.session.execute(
                update(NotificationOutbox)
                .where(NotificationOutbox.id == row_id)
                .values(
                    status=NotificationOutboxStatus.PENDING,
                    attempts=attempts,
                    last_error=truncated,
                    locked_at=now + backoff,
                )
            )
            return True
        await self.session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == row_id)
            .values(
                status=NotificationOutboxStatus.FAILED,
                attempts=attempts,
                last_error=truncated,
                processed_at=now,
                locked_at=None,
            )
        )
        return False

    # Сбрасывает зависшие processing-строки обратно в pending.
    async def reset_stuck_processing(self, older_than_minutes: int = 5) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        result = await self.session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationOutboxStatus.PROCESSING,
                NotificationOutbox.locked_at.is_not(None),
                NotificationOutbox.locked_at < cutoff,
            )
            .values(
                status=NotificationOutboxStatus.PENDING,
                locked_at=None,
            )
        )
        return int(result.rowcount or 0)

    # Возвращает status outbox-строк по списку idempotency keys.
    async def status_by_keys(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        stmt = select(
            NotificationOutbox.idempotency_key,
            NotificationOutbox.status,
        ).where(NotificationOutbox.idempotency_key.in_(keys))
        rows = (await self.session.execute(stmt)).all()
        return {str(key): str(status) for key, status in rows}
