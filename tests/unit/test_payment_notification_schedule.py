from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import OrderEvent
from src.repositories.notification_outbox_repo import (
    MAX_ATTEMPTS,
    NotificationOutboxRepo,
)
from src.services.payment_service import (
    PAYMENT_ACCEPTED_STATUS,
    PAYMENT_EVENT_TYPE,
    PaymentAcceptedNotify,
    PaymentService,
    _InitBootstrap,
)
from src.utils.datetime_fmt import utc_now_naive
from tests.unit.test_payment_attempts import _attempt, _order


@pytest.fixture
def payment_service() -> PaymentService:
    session = AsyncMock()
    session.add = MagicMock()
    sbp = AsyncMock()
    service = PaymentService(session, sbp_client=sbp)
    service.order_crud = AsyncMock()
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    return service


@pytest.mark.asyncio
async def test_init_continue_refresh_schedules_notifications_before_commit(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(
        provider_order_id="prov-1",
        provider_status=PAYMENT_ACCEPTED_STATUS,
        paid_at=utc_now_naive(),
    )
    notify = PaymentAcceptedNotify(order_id=1, attempt_id=attempt.id)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service._refresh_attempt_from_provider = AsyncMock(return_value=notify)
    payment_service._schedule_payment_notifications = AsyncMock()
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service._commit_init_return = AsyncMock(
        return_value=MagicMock(payment_state="paid")
    )

    await payment_service._init_continue_without_order_lock(
        1,
        10,
        _InitBootstrap("continue", attempt.id),
    )

    payment_service._schedule_payment_notifications.assert_awaited_once_with(notify)
    payment_service.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_init_continue_refresh_no_side_effect_skips_schedule(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(
        provider_order_id="prov-1",
        provider_status=PAYMENT_ACCEPTED_STATUS,
        paid_at=utc_now_naive(),
    )
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service._refresh_attempt_from_provider = AsyncMock(return_value=None)
    payment_service._schedule_payment_notifications = AsyncMock()
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service._commit_init_return = AsyncMock(
        return_value=MagicMock(payment_state="paid")
    )

    await payment_service._init_continue_without_order_lock(
        1,
        10,
        _InitBootstrap("continue", attempt.id),
    )

    payment_service._schedule_payment_notifications.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_second_accept_does_not_schedule(
    payment_service: PaymentService,
) -> None:
    attempt = _attempt(paid_at=utc_now_naive())
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=attempt
    )
    payment_service._callback_payload_matches_attempt = MagicMock(return_value=True)
    payment_service._apply_provider_status_to_attempt = AsyncMock(return_value=None)
    payment_service._schedule_payment_notifications = AsyncMock()

    await payment_service.handle_sbp_callback(
        {"order": {"id": "prov-1", "status": "IPS_ACCEPTED", "paymentAmount": 10000}}
    )

    payment_service._schedule_payment_notifications.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_enqueues_missing_admin_outbox(
    payment_service: PaymentService,
) -> None:
    event = MagicMock(spec=OrderEvent)
    event.order_id = 56
    event.payload_json = {"payment_attempt_id": 36}
    payment_service.session.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[event]))
    )
    outbox = AsyncMock(spec=NotificationOutboxRepo)
    outbox.exists_idempotency_key = AsyncMock(return_value=False)
    payment_service._schedule_payment_notifications = AsyncMock()

    with patch(
        "src.services.payment_service.NotificationOutboxRepo",
        return_value=outbox,
    ):
        stats = await payment_service.recover_missing_payment_notifications(limit=10)

    assert stats["recovered"] == 1
    payment_service._schedule_payment_notifications.assert_awaited_once()
    payment_service.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_recovery_skips_when_outbox_exists(
    payment_service: PaymentService,
) -> None:
    event = MagicMock(spec=OrderEvent)
    event.order_id = 58
    event.payload_json = {"payment_attempt_id": 38}
    payment_service.session.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[event]))
    )
    outbox = AsyncMock(spec=NotificationOutboxRepo)
    outbox.exists_idempotency_key = AsyncMock(return_value=True)
    payment_service._schedule_payment_notifications = AsyncMock()

    with patch(
        "src.services.payment_service.NotificationOutboxRepo",
        return_value=outbox,
    ):
        stats = await payment_service.recover_missing_payment_notifications(limit=10)

    assert stats["recovered"] == 0
    assert stats["skipped"] == 1
    payment_service._schedule_payment_notifications.assert_not_awaited()


def test_outbox_max_attempts_unchanged() -> None:
    assert MAX_ATTEMPTS == 5


def test_payment_event_type_constant() -> None:
    assert PAYMENT_EVENT_TYPE == "payment_accepted"
