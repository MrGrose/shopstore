from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.admin_notification_service import (
    ADMIN_DELIVERED_ALERT_KEY,
    delivered_alert_retry_is_due,
    schedule_delivered_alert_retry,
)
from src.utils.datetime_fmt import utc_now_naive


def _order_with_retry(*, pending: bool, next_retry_at: str | None) -> MagicMock:
    order = MagicMock()
    order.supplier_tracking_json = {
        ADMIN_DELIVERED_ALERT_KEY: {
            "pending_retry": pending,
            "next_retry_at": next_retry_at,
        }
    }
    return order


def test_delivered_alert_retry_is_due_when_time_passed() -> None:
    now = utc_now_naive()
    order = _order_with_retry(
        pending=True,
        next_retry_at=(now - timedelta(minutes=1)).isoformat(),
    )
    assert delivered_alert_retry_is_due(order, now=now) is True


def test_delivered_alert_retry_not_due_before_time() -> None:
    now = utc_now_naive()
    order = _order_with_retry(
        pending=True,
        next_retry_at=(now + timedelta(minutes=10)).isoformat(),
    )
    assert delivered_alert_retry_is_due(order, now=now) is False


def test_schedule_delivered_alert_retry_sets_next_retry_at() -> None:
    now = utc_now_naive()
    order = MagicMock()
    order.supplier_tracking_json = {}
    with patch("src.services.admin_notification_service.settings") as settings_mock:
        settings_mock.DELIVERED_ALERT_RETRY_MINUTES = 30
        schedule_delivered_alert_retry(order, now=now)
    alert = order.supplier_tracking_json[ADMIN_DELIVERED_ALERT_KEY]
    assert alert["pending_retry"] is True
    assert alert["next_retry_at"]


def test_enqueue_due_retries_only_immediate() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_delivered_alert_retry,
    )

    with patch(
        "src.jobs.orders.delivered_alert_retry_scheduler."
        "get_delivered_alert_retry_queue"
    ) as queue_mock:
        queue = MagicMock()
        queue.fetch_job.return_value = None
        queue_mock.return_value = queue
        assert enqueue_delivered_alert_retry(42, delay_minutes=15) is None
        queue.enqueue.assert_not_called()
        enqueue_delivered_alert_retry(42, delay_minutes=0)
        queue.enqueue.assert_called_once()


def test_reenqueue_after_finished_job_deletes_stale_entry() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_delivered_alert_retry,
    )

    finished_job = MagicMock()
    finished_job.get_status.return_value = "finished"
    with patch(
        "src.jobs.orders.delivered_alert_retry_scheduler."
        "get_delivered_alert_retry_queue"
    ) as queue_mock:
        queue = MagicMock()
        queue.fetch_job.return_value = finished_job
        queue_mock.return_value = queue
        enqueue_delivered_alert_retry(42, delay_minutes=0)
    finished_job.delete.assert_called_once()
    queue.enqueue.assert_called_once()


def _due_retry_row(order_id: int, *, due_at: str) -> tuple[int, dict]:
    return (
        order_id,
        {
            ADMIN_DELIVERED_ALERT_KEY: {
                "pending_retry": True,
                "next_retry_at": due_at,
            }
        },
    )


def _mock_session(rows: list) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=rows))
    )
    return session


def _crud_no_shipments() -> MagicMock:
    crud = MagicMock()
    crud.list_shipments_pending_delivered_alert_retry = AsyncMock(return_value=[])
    crud.list_shipments_for_order = AsyncMock(return_value=[])
    return crud


@pytest.mark.asyncio
async def test_enqueue_due_retries_counts_only_created_jobs() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_due_delivered_alert_retries,
    )

    now = utc_now_naive()
    due_at = (now - timedelta(minutes=1)).isoformat()
    rows = [_due_retry_row(101, due_at=due_at)]
    session = _mock_session(rows)
    job = MagicMock(id="delivered-alert-retry-101")

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.async_session_maker",
            return_value=session,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.CrudOrder",
            return_value=_crud_no_shipments(),
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "enqueue_delivered_alert_retry",
            return_value=job,
        ) as enqueue_mock,
    ):
        result = await enqueue_due_delivered_alert_retries(limit=50, now=now)

    assert result == {"selected": 1, "enqueued": 1}
    enqueue_mock.assert_called_once_with(101, delay_minutes=0)


@pytest.mark.asyncio
async def test_enqueue_due_retries_skips_when_enqueue_returns_none() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_due_delivered_alert_retries,
    )

    now = utc_now_naive()
    due_at = (now - timedelta(minutes=1)).isoformat()
    rows = [_due_retry_row(102, due_at=due_at)]
    session = _mock_session(rows)

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.async_session_maker",
            return_value=session,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.CrudOrder",
            return_value=_crud_no_shipments(),
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "enqueue_delivered_alert_retry",
            return_value=None,
        ) as enqueue_mock,
    ):
        result = await enqueue_due_delivered_alert_retries(limit=50, now=now)

    assert result == {"selected": 1, "enqueued": 0}
    enqueue_mock.assert_called_once_with(102, delay_minutes=0)


@pytest.mark.asyncio
async def test_enqueue_due_retries_continues_after_enqueue_exception() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_due_delivered_alert_retries,
    )

    now = utc_now_naive()
    due_at = (now - timedelta(minutes=1)).isoformat()
    rows = [
        _due_retry_row(201, due_at=due_at),
        _due_retry_row(202, due_at=due_at),
    ]
    session = _mock_session(rows)
    job = MagicMock(id="delivered-alert-retry-202")

    def enqueue_side_effect(order_id: int, *, delay_minutes: int) -> MagicMock | None:
        if order_id == 201:
            raise RuntimeError("queue unavailable")
        return job

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.async_session_maker",
            return_value=session,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.CrudOrder",
            return_value=_crud_no_shipments(),
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "enqueue_delivered_alert_retry",
            side_effect=enqueue_side_effect,
        ) as enqueue_mock,
    ):
        result = await enqueue_due_delivered_alert_retries(limit=50, now=now)

    assert result == {"selected": 2, "enqueued": 1}
    assert enqueue_mock.call_count == 2


@pytest.mark.asyncio
async def test_enqueue_due_retries_skips_legacy_when_order_has_shipments() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_due_delivered_alert_retries,
    )

    now = utc_now_naive()
    due_at = (now - timedelta(minutes=1)).isoformat()
    rows = [_due_retry_row(101, due_at=due_at)]
    session = _mock_session(rows)
    crud = _crud_no_shipments()
    crud.list_shipments_for_order = AsyncMock(return_value=[MagicMock()])

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.async_session_maker",
            return_value=session,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.CrudOrder",
            return_value=crud,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "enqueue_delivered_alert_retry",
        ) as enqueue_mock,
    ):
        result = await enqueue_due_delivered_alert_retries(limit=50, now=now)

    enqueue_mock.assert_not_called()
    assert result["enqueued"] == 0


@pytest.mark.asyncio
async def test_enqueue_due_retries_still_enqueues_shipment_jobs() -> None:
    from src.jobs.orders.delivered_alert_retry_scheduler import (
        enqueue_due_delivered_alert_retries,
    )

    now = utc_now_naive()
    session = _mock_session([])
    shipment = MagicMock()
    shipment.id = 160
    crud = _crud_no_shipments()
    crud.list_shipments_pending_delivered_alert_retry = AsyncMock(
        return_value=[shipment]
    )
    job = MagicMock(id="shipment-delivered-alert-retry-160")

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.async_session_maker",
            return_value=session,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler.CrudOrder",
            return_value=crud,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "shipment_delivered_alert_retry_is_due",
            return_value=True,
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_scheduler."
            "enqueue_shipment_delivered_alert_retry",
            return_value=job,
        ) as enqueue_mock,
    ):
        result = await enqueue_due_delivered_alert_retries(limit=50, now=now)

    enqueue_mock.assert_called_once_with(160, delay_minutes=0)
    assert result == {"selected": 1, "enqueued": 1}
