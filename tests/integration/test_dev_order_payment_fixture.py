import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.models.notification_outbox import NotificationOutbox
from src.models.order import (
    CANCELLATION_REASON_PAYMENT_TIMEOUT,
    ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
    Order,
    OrderPaymentAttempt,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.notifications.dispatch import notification_dispatch_from_dict
from src.services.orders.order_service import OrderService
from src.services.payment_service import PaymentService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import PAYMENT_ACCEPTED_STATUS
from tests.fixtures.sbp_callback import (
    build_sbp_accepted_payload,
    ensure_sbp_payment_attempt,
)
from tests.integration.helpers.order_admin import create_telegram_user
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order
from tests.manual.order_test_fixture import mark_order_paid, require_dev_environment

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _prepare_unpaid_order(suffix: int) -> Order:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        order = await _create_unpaid_order(
            session,
            user.id,
            suffix,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        await session.commit()
        await session.refresh(order)
        return order


async def _order_events(order_id: int) -> list[str]:
    async with async_session_maker() as session:
        rows = await OrderService(session).order_crud.get_order_events(order_id)
        return [str(row.event_type) for row in rows]


async def _outbox_templates(order_id: int, attempt_id: int) -> set[str]:
    keys = {
        f"admin:payment.accepted:order:{order_id}:attempt:{attempt_id}",
        f"customer:payment.received:order:{order_id}:telegram",
    }
    async with async_session_maker() as session:
        rows = await session.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key.in_(keys)
            )
        )
        return {
            notification_dispatch_from_dict(row.dispatch_json).template
            for row in rows.all()
        }


@pytest.mark.asyncio
async def test_synthetic_accepted_payment_marks_attempt_and_order_paid(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    order = await _prepare_unpaid_order(merge_unique_suffix + 90_000)

    await mark_order_paid(order.id, late=False)

    async with async_session_maker() as session:
        fresh_order = await session.get(Order, order.id)
        assert fresh_order is not None
        assert fresh_order.payment_paid_at is not None
        assert fresh_order.payment_status == PAYMENT_ACCEPTED_STATUS
        order_crud = CrudOrder(session=session, model=Order)
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        assert attempt.paid_at is not None
        assert attempt.provider_status == PAYMENT_ACCEPTED_STATUS
        attempt_id = attempt.id

    assert "payment_accepted" in await _order_events(order.id)
    assert await _outbox_templates(order.id, attempt_id) == {
        "payment.accepted",
        "payment.received",
    }


@pytest.mark.asyncio
async def test_synthetic_late_payment_after_timeout_cancel(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    order = await _prepare_unpaid_order(merge_unique_suffix + 91_000)

    async with async_session_maker() as session:
        locked = await OrderService(session).order_crud.get_by_id_for_update(order.id)
        assert locked is not None
        await OrderService(session)._apply_order_cancellation(
            locked,
            cancellation_reason=CANCELLATION_REASON_PAYMENT_TIMEOUT,
            event_type=ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
            event_message="timeout",
            created_by="test",
        )
        await session.commit()

    await mark_order_paid(order.id, late=True)

    events = await _order_events(order.id)
    assert "late_payment_after_auto_cancel" in events
    async with async_session_maker() as session:
        order_crud = CrudOrder(session=session, model=Order)
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        assert attempt.paid_at is not None


@pytest.mark.asyncio
async def test_synthetic_payment_idempotent_on_repeat(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    order = await _prepare_unpaid_order(merge_unique_suffix + 92_000)

    await mark_order_paid(order.id, late=False)
    await mark_order_paid(order.id, late=False)

    events = await _order_events(order.id)
    assert events.count("payment_accepted") == 1


@pytest.mark.asyncio
async def test_handle_sbp_callback_via_fixture_payload_side_effects(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix + 93_000
    order = await _prepare_unpaid_order(suffix)

    async with async_session_maker() as session:
        attempt, provider_order_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await session.refresh(attempt)

        payment_service = PaymentService(session)
        await payment_service.handle_sbp_callback(
            build_sbp_accepted_payload(provider_order_id, attempt)
        )

    async with async_session_maker() as session:
        fresh_attempt = await session.get(OrderPaymentAttempt, attempt.id)
        assert fresh_attempt is not None
        assert fresh_attempt.paid_at is not None

    assert await _outbox_templates(order.id, attempt.id) == {
        "payment.accepted",
        "payment.received",
    }


def test_require_dev_environment_blocks_non_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    with pytest.raises(SystemExit, match="APP_ENV=dev"):
        require_dev_environment()


def test_accept_local_payment_removed_from_payment_service() -> None:
    assert not hasattr(PaymentService, "accept_local_payment")


def test_manual_fixture_does_not_call_private_payment_methods() -> None:
    script = (REPO_ROOT / "tests/manual/order_test_fixture.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "_apply_provider_status_to_attempt",
        "_mark_attempt_accepted",
        "_schedule_payment_notifications",
        "accept_local_payment",
        "mark_payment_accepted_if_unpaid",
    )
    for token in forbidden:
        assert token not in script


def test_manual_fixture_main_exits_outside_dev() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tests/manual/order_test_fixture.py"),
            "show",
            "--order-id",
            "1",
        ],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "APP_ENV": "prod"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "APP_ENV=dev" in result.stderr or "APP_ENV=dev" in result.stdout
