from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from src.services.notifications.outbox_dispatcher import OutboxNotificationDispatcher


def _dispatch() -> NotificationDispatch:
    return NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 42},
        idempotency_key="order-42-status-created",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channels", "expected"),
    [
        (["email"], [NotificationChannel.EMAIL]),
        (["telegram"], [NotificationChannel.CUSTOMER]),
    ],
)
async def test_order_notification_channel_is_scheduled_independently(
    channels: list[str], expected: list[NotificationChannel]
) -> None:
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(notification_channels=channels)
    scheduled = AsyncMock(return_value=True)

    with patch(
        "src.services.notifications.outbox_dispatcher.schedule_notification",
        scheduled,
    ):
        result = await OutboxNotificationDispatcher().enqueue(session, _dispatch())

    assert result is True
    assert [call.args[1].channel for call in scheduled.await_args_list] == expected


@pytest.mark.asyncio
async def test_order_notification_both_channels_create_two_outbox_dispatches() -> None:
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(
        notification_channels=["email", "telegram"]
    )
    scheduled = AsyncMock(return_value=True)

    with patch(
        "src.services.notifications.outbox_dispatcher.schedule_notification",
        scheduled,
    ):
        result = await OutboxNotificationDispatcher().enqueue(session, _dispatch())

    assert result is True
    dispatches = [call.args[1] for call in scheduled.await_args_list]
    assert [dispatch.channel for dispatch in dispatches] == [
        NotificationChannel.EMAIL,
        NotificationChannel.CUSTOMER,
    ]
    assert [dispatch.idempotency_key for dispatch in dispatches] == [
        "order-42-status-created:email",
        "order-42-status-created:telegram",
    ]
