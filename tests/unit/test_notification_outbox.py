import pytest

from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from src.services.notifications.outbox_service import schedule_notification


@pytest.mark.asyncio
async def test_schedule_requires_idempotency_key() -> None:
    from unittest.mock import AsyncMock

    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 1},
    )
    with pytest.raises(ValueError, match="idempotency_key"):
        await schedule_notification(session, dispatch)
