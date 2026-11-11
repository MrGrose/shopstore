from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.notifications.customer_dispatch import expand_customer_dispatch
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
    NotificationOrderEvent,
)
from src.services.notifications.inline_dispatcher import InlineNotificationDispatcher


def test_expand_customer_dispatch_adds_channel_suffix_to_idempotency_key() -> None:
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 296},
        idempotency_key="notify-296",
    )

    expanded = expand_customer_dispatch(dispatch, ["telegram", "email"])

    assert len(expanded) == 2
    assert expanded[0].channel == NotificationChannel.CUSTOMER
    assert expanded[0].idempotency_key == "notify-296:telegram"
    assert expanded[1].channel == NotificationChannel.EMAIL
    assert expanded[1].idempotency_key == "notify-296:email"


@pytest.mark.asyncio
async def test_inline_dispatcher_respects_forced_email_channel() -> None:
    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 296, "force_channel": "email"},
        idempotency_key="manual-email-296",
    )

    with patch(
        "src.services.notifications.inline_dispatcher.send_plain_email",
        new=AsyncMock(),
    ) as send_email:
        result = await InlineNotificationDispatcher().enqueue(session, dispatch)

    assert result is True
    send_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_inline_dispatcher_fan_out_dual_channel_order() -> None:
    session = AsyncMock()
    order = MagicMock()
    order.notification_channels = ["telegram", "email"]
    session.get = AsyncMock(return_value=order)
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 296},
        idempotency_key="notify-296",
    )
    dispatcher = InlineNotificationDispatcher()
    deliver_mock = AsyncMock(side_effect=[True, True])

    with patch.object(dispatcher, "deliver", deliver_mock):
        result = await dispatcher.enqueue(session, dispatch)

    assert result is True
    assert deliver_mock.await_count == 2
    first_dispatch = deliver_mock.await_args_list[0].args[1]
    second_dispatch = deliver_mock.await_args_list[1].args[1]
    assert first_dispatch.idempotency_key == "notify-296:telegram"
    assert second_dispatch.idempotency_key == "notify-296:email"


@pytest.mark.asyncio
async def test_inline_dispatcher_records_telegram_channel_for_customer_dispatch() -> (
    None
):
    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="payment.received",
        payload={"order_id": 40},
        idempotency_key="customer:payment.received:order:40:telegram",
        record_order_event=NotificationOrderEvent(
            event_type="customer_notified",
            event_message="Клиент уведомлён об оплате",
        ),
    )
    dispatcher = InlineNotificationDispatcher()

    with patch(
        "src.services.notifications.inline_dispatcher.CrudOrder"
    ) as order_crud_cls:
        order_crud = order_crud_cls.return_value
        order_crud.create_order_event = AsyncMock()
        order_crud.get_by_id = AsyncMock(return_value=MagicMock())
        order_crud.commit_order = AsyncMock()
        await dispatcher._record_order_event(
            session,
            40,
            dispatch,
            "Оплата получена",
        )

    payload = order_crud.create_order_event.await_args.kwargs["payload_json"]
    assert payload["channel"] == "telegram"
    assert payload["template"] == "payment.received"
    assert payload["idempotency_key"] == "customer:payment.received:order:40:telegram"


@pytest.mark.asyncio
async def test_inline_dispatcher_records_email_channel_unchanged() -> None:
    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.EMAIL,
        template="payment.received",
        payload={"order_id": 40},
        idempotency_key="customer:payment.received:order:40:email",
        record_order_event=NotificationOrderEvent(
            event_type="customer_notified",
            event_message="Клиент уведомлён об оплате",
        ),
    )
    dispatcher = InlineNotificationDispatcher()

    with patch(
        "src.services.notifications.inline_dispatcher.CrudOrder"
    ) as order_crud_cls:
        order_crud = order_crud_cls.return_value
        order_crud.create_order_event = AsyncMock()
        order_crud.get_by_id = AsyncMock(return_value=MagicMock())
        order_crud.commit_order = AsyncMock()
        await dispatcher._record_order_event(
            session,
            40,
            dispatch,
            "Оплата получена",
        )

    payload = order_crud.create_order_event.await_args.kwargs["payload_json"]
    assert payload["channel"] == "email"


@pytest.mark.asyncio
async def test_inline_dispatcher_merges_manual_payload_for_customer_dispatch() -> None:
    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="customer.manual",
        payload={"order_id": 40, "message": "Привет"},
        idempotency_key="admin:manual:40:telegram:abc",
        record_order_event=NotificationOrderEvent(
            event_type="customer_notified",
            event_message="Ручное сообщение клиенту",
            payload_json={"manual": True, "channel": "telegram"},
        ),
    )
    dispatcher = InlineNotificationDispatcher()

    with patch(
        "src.services.notifications.inline_dispatcher.CrudOrder"
    ) as order_crud_cls:
        order_crud = order_crud_cls.return_value
        order_crud.create_order_event = AsyncMock()
        order_crud.get_by_id = AsyncMock(return_value=MagicMock())
        order_crud.commit_order = AsyncMock()
        await dispatcher._record_order_event(
            session,
            40,
            dispatch,
            "Заказ #40\n\nПривет",
        )

    payload = order_crud.create_order_event.await_args.kwargs["payload_json"]
    assert payload["manual"] is True
    assert payload["channel"] == "telegram"
    assert payload["template"] == "customer.manual"
    assert payload["message"] == "Заказ #40\n\nПривет"
