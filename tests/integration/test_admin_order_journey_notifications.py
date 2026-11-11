from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.telegram_client import TelegramSendResult
from src.models.order import Order
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.notifications.composer import (
    ComposedEmailNotification,
    ComposedNotification,
)
from src.services.notifications.customer_dispatch import expand_customer_dispatch
from src.services.notifications.customer_notification_keys import payment_received_key
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
    NotificationOrderEvent,
)
from src.services.notifications.inline_dispatcher import InlineNotificationDispatcher
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from src.web.admin_order_events import build_order_journey, format_order_event_rows
from tests.integration.helpers.order_admin import create_telegram_user
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_dual_channel_payment_journey_reads_customer_notified_from_db(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 4079
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        order = await _create_unpaid_order(
            session,
            user.id,
            suffix,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.get_by_id(order.id)
        assert order is not None
        order.notification_channels = ["telegram", "email"]
        order.payment_status = "paid"
        order.payment_paid_at = utc_now_naive()
        await session.commit()
        await session.refresh(order)

        base_dispatch = NotificationDispatch(
            channel=NotificationChannel.CUSTOMER,
            template="payment.received",
            payload={"order_id": order.id},
            idempotency_key=payment_received_key(order.id),
            record_order_event=NotificationOrderEvent(
                event_type="customer_notified",
                event_message="Клиент уведомлён об оплате",
            ),
        )
        dispatcher = InlineNotificationDispatcher()
        dispatcher.telegram_client = MagicMock()
        dispatcher.telegram_client.send_message = AsyncMock(
            return_value=TelegramSendResult(ok=True, message_id=1),
        )

        for channel_dispatch in expand_customer_dispatch(
            base_dispatch,
            ["telegram", "email"],
        ):
            if channel_dispatch.channel == NotificationChannel.EMAIL:
                with (
                    patch(
                        "src.services.notifications.inline_dispatcher."
                        "compose_email_notification",
                        new=AsyncMock(
                            return_value=ComposedEmailNotification(
                                order_id=order.id,
                                email="client@example.com",
                                subject="Оплата",
                                text="Оплата получена",
                            ),
                        ),
                    ),
                    patch(
                        "src.services.notifications.inline_dispatcher.send_plain_email",
                        new=AsyncMock(),
                    ),
                ):
                    assert await dispatcher.deliver(session, channel_dispatch)
            else:
                with patch(
                    "src.services.notifications.inline_dispatcher.compose_notification",
                    new=AsyncMock(
                        return_value=ComposedNotification(
                            order_id=order.id,
                            chat_id=1,
                            text="Оплата получена",
                            parse_mode="HTML",
                            reply_markup=None,
                        ),
                    ),
                ):
                    assert await dispatcher.deliver(session, channel_dispatch)

        await session.commit()
        events = await OrderService(session).get_order_events(order.id)
        rows = format_order_event_rows(events, {}, {})
        customer_events = [
            row["payload_json"]
            for row in rows
            if row["event_type"] == "customer_notified"
        ]
        channels = {payload["channel"] for payload in customer_events}
        assert channels == {"telegram", "email"}

        journey = build_order_journey(order, rows)
        payment = journey["stages"][2]
        assert {"channel": "TG", "state": "sent"} in payment["notify_badges"]
        assert {"channel": "EM", "state": "sent"} in payment["notify_badges"]


@pytest.mark.asyncio
async def test_manual_customer_message_records_event_in_db(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 5011
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        order = await _create_unpaid_order(
            session,
            user.id,
            suffix,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        inline = InlineNotificationDispatcher()
        inline.telegram_client = MagicMock()
        inline.telegram_client.send_message = AsyncMock(
            return_value=TelegramSendResult(ok=True, message_id=1),
        )

        with (
            patch(
                "src.services.orders.order_service.notification_dispatcher",
                return_value=inline,
            ),
            patch(
                "src.services.notifications.inline_dispatcher.compose_notification",
                new=AsyncMock(
                    return_value=ComposedNotification(
                        order_id=order.id,
                        chat_id=1,
                        text="Проверьте размер",
                        parse_mode="HTML",
                        reply_markup=None,
                    ),
                ),
            ),
        ):
            await OrderService(session).send_customer_telegram_message(
                order.id,
                "Проверьте размер",
            )

        await session.commit()
        events = await OrderService(session).get_order_events(order.id)
        rows = format_order_event_rows(events, {}, {})
        manual_events = [
            row
            for row in rows
            if row["event_type"] == "customer_notified"
            and row["message"] == "Ручное сообщение клиенту"
        ]
        assert len(manual_events) == 1
        payload = manual_events[0]["payload_json"]
        assert payload["manual"] is True
        assert payload["channel"] == "telegram"
        assert payload["template"] == "customer.manual"
        assert payload["message"] == "Проверьте размер"
        assert manual_events[0]["changes"] == [
            {"label": "Канал", "before": "—", "after": "Telegram"},
            {"label": "Сообщение", "before": "—", "after": "Проверьте размер"},
        ]
