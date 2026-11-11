import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, update

from src.models.notification_outbox import NotificationOutbox, NotificationOutboxStatus
from src.models.order import Order, OrderPaymentAttempt
from src.repositories.notification_outbox_repo import (
    MAX_ATTEMPTS,
    NotificationOutboxRepo,
)
from src.repositories.session import async_session_maker
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
    notification_dispatch_from_dict,
    notification_dispatch_to_dict,
)
from src.services.notifications.outbox_service import schedule_notification
from src.services.payment_service import PaymentAcceptedNotify, PaymentService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import PAYMENT_ACCEPTED_STATUS
from tests.fixtures.sbp_callback import (
    build_sbp_accepted_payload,
    ensure_sbp_payment_attempt,
)
from tests.integration.helpers.order_admin import create_telegram_user
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order

pytestmark = pytest.mark.integration


def _payment_awaiting_dispatch(key: str, order_id: int = 42) -> NotificationDispatch:
    return NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="payment.awaiting",
        payload={"order_id": order_id},
        idempotency_key=key,
    )


# Готовит неоплаченный заказ с SBP-попыткой для callback IPS_ACCEPTED.
async def _create_order_with_sbp_attempt(
    suffix: int,
) -> tuple[Order, OrderPaymentAttempt, str]:
    provider_order_id = f"test-sbp-prov-{suffix}"
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        order = await _create_unpaid_order(
            session,
            user.id,
            suffix,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        attempt, provider_order_id = await ensure_sbp_payment_attempt(
            session,
            order,
            provider_order_id=provider_order_id,
        )
        await session.commit()
        await session.refresh(order)
        await session.refresh(attempt)
        return order, attempt, provider_order_id


def _sbp_accepted_payload(
    provider_order_id: str,
    attempt: OrderPaymentAttempt,
) -> dict:
    return build_sbp_accepted_payload(provider_order_id, attempt)


async def _outbox_rows_for_keys(keys: set[str]) -> list[NotificationOutbox]:
    async with async_session_maker() as session:
        return list(
            (
                await session.scalars(
                    select(NotificationOutbox).where(
                        NotificationOutbox.idempotency_key.in_(keys)
                    )
                )
            ).all()
        )


# Сдвигает locked_at в прошлое, чтобы worker снова взял строку после backoff.
async def _clear_outbox_backoff(session, row_id: int) -> None:
    await session.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.id == row_id)
        .values(locked_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()


# Worker только для указанных idempotency_key (не трогает чужие pending в БД).
async def _process_outbox_for_keys(
    keys: set[str],
    dispatcher,
) -> dict[str, int]:
    stats = {"sent": 0, "failed": 0, "requeued": 0}
    async with async_session_maker() as session:
        repo = NotificationOutboxRepo(session)
        now = datetime.now(UTC)
        for key in keys:
            row = await session.scalar(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.idempotency_key == key,
                    NotificationOutbox.status == NotificationOutboxStatus.PENDING,
                )
                .with_for_update()
            )
            if row is None:
                continue
            if row.locked_at is not None and row.locked_at > now:
                continue
            row.status = NotificationOutboxStatus.PROCESSING
            row.locked_at = now
            await session.flush()
            dispatch = notification_dispatch_from_dict(row.dispatch_json)
            success = await dispatcher.deliver(session, dispatch)
            if success:
                await repo.mark_sent(row.id)
                stats["sent"] += 1
                continue
            requeued = await repo.mark_failed(
                row.id,
                "TG уведомление не доставлено",
                requeue=True,
            )
            if requeued:
                stats["requeued"] += 1
            else:
                stats["failed"] += 1
        await session.commit()
    return stats


async def _get_outbox_row(key: str) -> NotificationOutbox:
    async with async_session_maker() as session:
        row = await session.scalar(
            select(NotificationOutbox).where(NotificationOutbox.idempotency_key == key)
        )
        assert row is not None
        return row


@pytest.mark.asyncio
async def test_enqueue_duplicate_key_inserts_once() -> None:
    key = f"test:outbox:duplicate:{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as session:
        dispatch = _payment_awaiting_dispatch(key)
        first = await schedule_notification(session, dispatch)
        second = await schedule_notification(session, dispatch)
        await session.commit()
        assert first is True
        assert second is False

    async with async_session_maker() as session:
        rows = list(
            (
                await session.scalars(
                    select(NotificationOutbox).where(
                        NotificationOutbox.idempotency_key == key
                    )
                )
            ).all()
        )
        assert len(rows) == 1
        restored = notification_dispatch_from_dict(rows[0].dispatch_json)
        assert restored.template == "payment.awaiting"


@pytest.mark.asyncio
async def test_claim_pending_batch_skips_concurrently_locked_row() -> None:
    suffix = uuid.uuid4().hex[:8]
    key_a = f"test:outbox:claim:a:{suffix}"
    key_b = f"test:outbox:claim:b:{suffix}"
    async with async_session_maker() as session:
        repo = NotificationOutboxRepo(session)
        await repo.enqueue_dispatch(
            key_a,
            notification_dispatch_to_dict(_payment_awaiting_dispatch(key_a)),
        )
        await repo.enqueue_dispatch(
            key_b,
            notification_dispatch_to_dict(_payment_awaiting_dispatch(key_b)),
        )
        await session.commit()

    async with async_session_maker() as session:
        row_a = await session.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == key_a
            )
        )
        row_b = await session.scalar(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == key_b
            )
        )
        assert row_a is not None
        assert row_b is not None
        row_a_id = row_a.id
        row_b_id = row_b.id

    lock_held = asyncio.Event()
    claim_done = asyncio.Event()
    claimed_ids: list[int] = []

    async def hold_row_a_lock() -> None:
        async with async_session_maker() as session:
            row = await session.scalar(
                select(NotificationOutbox)
                .where(NotificationOutbox.id == row_a_id)
                .with_for_update()
            )
            assert row is not None
            lock_held.set()
            await claim_done.wait()
            await session.commit()

    async def claim_while_a_locked() -> None:
        await lock_held.wait()
        async with async_session_maker() as session:
            claimed = await NotificationOutboxRepo(session).claim_pending_batch(
                limit=50
            )
            claimed_ids.extend(row.id for row in claimed)
            await session.commit()
        claim_done.set()

    await asyncio.gather(hold_row_a_lock(), claim_while_a_locked())

    assert row_a_id not in claimed_ids
    assert row_b_id in claimed_ids


@pytest.mark.asyncio
async def test_schedule_commit_worker_delivers_marks_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    order_id = 900_000 + int(uuid.uuid4().hex[:4], 16) % 10_000
    key = f"customer:payment.awaiting:order:{order_id}"

    async with async_session_maker() as session:
        scheduled = await schedule_notification(
            session,
            _payment_awaiting_dispatch(key, order_id=order_id),
        )
        await session.commit()
        assert scheduled is True

    deliver_mock = AsyncMock(return_value=True)
    dispatcher = MagicMock(deliver=deliver_mock)

    stats = await _process_outbox_for_keys({key}, dispatcher)
    assert stats["sent"] == 1
    deliver_mock.assert_awaited_once()

    row = await _get_outbox_row(key)
    assert row.status == NotificationOutboxStatus.SENT
    assert row.processed_at is not None


@pytest.mark.asyncio
async def test_schedule_payment_notifications_enqueues_two_pending_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    order_id = 910_000 + int(uuid.uuid4().hex[:4], 16) % 10_000
    attempt_id = 77
    admin_key = f"admin:payment.accepted:order:{order_id}:attempt:{attempt_id}"
    customer_key = f"customer:payment.received:order:{order_id}:telegram"

    async with async_session_maker() as session:
        payment_service = PaymentService(session)
        await payment_service._schedule_payment_notifications(
            PaymentAcceptedNotify(order_id=order_id, attempt_id=attempt_id)
        )
        await session.commit()

    rows = await _outbox_rows_for_keys({admin_key, customer_key})
    assert len(rows) == 2
    assert {row.status for row in rows} == {NotificationOutboxStatus.PENDING}

    deliver_mock = AsyncMock(return_value=True)
    dispatcher = MagicMock()
    dispatcher.deliver = deliver_mock

    stats = await _process_outbox_for_keys({admin_key, customer_key}, dispatcher)
    assert stats["sent"] == 2
    assert deliver_mock.await_count == 2

    rows = await _outbox_rows_for_keys({admin_key, customer_key})
    assert all(row.status == NotificationOutboxStatus.SENT for row in rows)


@pytest.mark.asyncio
async def test_handle_sbp_callback_accepted_commits_payment_and_outbox(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix + 80_000
    order, attempt, provider_order_id = await _create_order_with_sbp_attempt(suffix)
    admin_key = f"admin:payment.accepted:order:{order.id}:attempt:{attempt.id}"
    customer_key = f"customer:payment.received:order:{order.id}:telegram"

    async with async_session_maker() as session:
        payment_service = PaymentService(session)
        await payment_service.handle_sbp_callback(
            _sbp_accepted_payload(provider_order_id, attempt)
        )

    async with async_session_maker() as session:
        fresh_order = await session.get(Order, order.id)
        fresh_attempt = await session.get(OrderPaymentAttempt, attempt.id)
        assert fresh_order is not None
        assert fresh_attempt is not None
        assert fresh_order.payment_paid_at is not None
        assert fresh_order.payment_status == PAYMENT_ACCEPTED_STATUS
        assert fresh_attempt.paid_at is not None
        assert fresh_attempt.provider_status == PAYMENT_ACCEPTED_STATUS

    rows = await _outbox_rows_for_keys({admin_key, customer_key})
    assert len(rows) == 2
    assert {row.status for row in rows} == {NotificationOutboxStatus.PENDING}
    templates = {
        notification_dispatch_from_dict(row.dispatch_json).template for row in rows
    }
    assert templates == {"payment.accepted", "payment.received"}


@pytest.mark.asyncio
async def test_handle_sbp_callback_rolls_back_payment_when_outbox_fails(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix + 81_000
    order, attempt, provider_order_id = await _create_order_with_sbp_attempt(suffix)
    admin_key = f"admin:payment.accepted:order:{order.id}:attempt:{attempt.id}"
    customer_key = f"customer:payment.received:order:{order.id}:telegram"
    original_enqueue = NotificationOutboxRepo.enqueue_dispatch
    insert_calls = 0

    async def enqueue_fail_on_second(
        self,
        idempotency_key: str,
        dispatch_json: dict,
    ) -> bool:
        nonlocal insert_calls
        insert_calls += 1
        if insert_calls >= 2:
            raise RuntimeError("outbox insert failed")
        return await original_enqueue(self, idempotency_key, dispatch_json)

    monkeypatch.setattr(
        NotificationOutboxRepo, "enqueue_dispatch", enqueue_fail_on_second
    )

    async with async_session_maker() as session:
        payment_service = PaymentService(session)
        with pytest.raises(RuntimeError, match="outbox insert failed"):
            await payment_service.handle_sbp_callback(
                _sbp_accepted_payload(provider_order_id, attempt)
            )

    async with async_session_maker() as session:
        fresh_order = await session.get(Order, order.id)
        fresh_attempt = await session.get(OrderPaymentAttempt, attempt.id)
        assert fresh_order is not None
        assert fresh_attempt is not None
        assert fresh_order.payment_paid_at is None
        assert fresh_order.payment_status == "QRCDATA_CREATED"
        assert fresh_attempt.paid_at is None
        assert fresh_attempt.provider_status == "QRCDATA_CREATED"

    rows = await _outbox_rows_for_keys({admin_key, customer_key})
    assert rows == []


@pytest.mark.asyncio
async def test_worker_tg_fail_requeues_five_times_then_failed() -> None:
    key = f"test:outbox:worker-retry:{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as session:
        await NotificationOutboxRepo(session).enqueue_dispatch(
            key,
            notification_dispatch_to_dict(_payment_awaiting_dispatch(key)),
        )
        await session.commit()

    fail_dispatcher = MagicMock()
    fail_dispatcher.deliver = AsyncMock(return_value=False)
    row_id: int | None = None

    for expected_attempt in range(1, MAX_ATTEMPTS):
        stats = await _process_outbox_for_keys({key}, fail_dispatcher)
        assert stats["requeued"] == 1
        row = await _get_outbox_row(key)
        row_id = row.id
        assert row.status == NotificationOutboxStatus.PENDING
        assert row.attempts == expected_attempt

        if expected_attempt < MAX_ATTEMPTS - 1:
            async with async_session_maker() as session:
                await _clear_outbox_backoff(session, row_id)

    async with async_session_maker() as session:
        await _clear_outbox_backoff(session, row_id)
    stats = await _process_outbox_for_keys({key}, fail_dispatcher)
    assert stats["failed"] == 1

    row = await _get_outbox_row(key)
    assert row.status == NotificationOutboxStatus.FAILED
    assert row.attempts == MAX_ATTEMPTS
    assert row.last_error is not None


@pytest.mark.asyncio
async def test_reset_stuck_processing_recovers_row() -> None:
    key = f"test:outbox:stuck:{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as session:
        repo = NotificationOutboxRepo(session)
        await repo.enqueue_dispatch(
            key,
            notification_dispatch_to_dict(_payment_awaiting_dispatch(key)),
        )
        await session.commit()

    async with async_session_maker() as session:
        repo = NotificationOutboxRepo(session)
        claimed = await repo.claim_pending_batch(limit=1)
        row_id = claimed[0].id
        await session.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id == row_id)
            .values(
                locked_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        await session.commit()

    async with async_session_maker() as session:
        reset_count = await NotificationOutboxRepo(session).reset_stuck_processing(
            older_than_minutes=5
        )
        await session.commit()
        assert reset_count >= 1
        row = await session.get(NotificationOutbox, row_id)
        assert row is not None
        assert row.status == NotificationOutboxStatus.PENDING
        assert row.locked_at is None

    deliver_mock = AsyncMock(return_value=True)
    dispatcher = MagicMock()
    dispatcher.deliver = deliver_mock

    stats = await _process_outbox_for_keys({key}, dispatcher)
    assert stats["sent"] == 1


@pytest.mark.asyncio
async def test_notification_outbox_job_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.jobs.notification_outbox_job import run_notification_outbox

    key = f"test:outbox:job:{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as session:
        await NotificationOutboxRepo(session).enqueue_dispatch(
            key,
            notification_dispatch_to_dict(_payment_awaiting_dispatch(key)),
        )
        await session.commit()

    deliver_mock = AsyncMock(return_value=True)

    async def _claim_only_test_key(self, limit: int):
        row = await self.session.scalar(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.idempotency_key == key,
                NotificationOutbox.status == NotificationOutboxStatus.PENDING,
            )
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return []
        row.status = NotificationOutboxStatus.PROCESSING
        row.locked_at = datetime.now(UTC)
        await self.session.flush()
        return [row]

    monkeypatch.setattr(
        NotificationOutboxRepo,
        "claim_pending_batch",
        _claim_only_test_key,
    )
    inline_deliver = (
        "src.services.notifications.outbox_service.InlineNotificationDispatcher.deliver"
    )
    monkeypatch.setattr(inline_deliver, deliver_mock)

    stats = await run_notification_outbox(limit=10)
    assert stats["sent"] == 1

    row = await _get_outbox_row(key)
    assert row.status == NotificationOutboxStatus.SENT
