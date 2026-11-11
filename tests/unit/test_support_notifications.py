from contextlib import ExitStack, contextmanager
from decimal import Decimal
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.content.admin_texts import (
    format_order_delivery_started_message,
    format_payment_accepted_message,
)
from src.content.client_texts import (
    customer_status_message,
    format_customer_availability_check_message,
    format_customer_availability_unavailable_message,
    format_customer_payment_late_received_message,
)
from src.content.support_texts import list_support_reply_templates
from src.integrations.telegram_client import TelegramSendResult
from src.models.user import User
from src.services.admin_notification_service import AdminNotificationService
from src.services.customer_notification_service import CustomerNotificationService
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from src.services.notifications.inline_dispatcher import InlineNotificationDispatcher
from src.services.support import SupportNotificationService, SupportService

SUPPORT_GROUP_NOTIFY = (
    "src.services.support.service.SupportNotificationService.notify_support_group"
)
SUPPORT_CUSTOMER_NOTIFY = (
    "src.services.support.service.SupportNotificationService"
    ".notify_customer_staff_reply"
)
IDENTITY_TG_ID = (
    "src.services.notifications.composer.IdentityService.get_telegram_id_for_user"
)
ORDER_CRUD_GET = "src.services.notifications.composer.CrudOrder.get_by_id"
ORDER_CRUD_EVENT = (
    "src.services.notifications.inline_dispatcher.CrudOrder.create_order_event"
)
ORDER_CRUD_COMMIT = (
    "src.services.notifications.inline_dispatcher.CrudOrder.commit_order"
)
COMPOSER_ORDER_SERVICE = "src.services.orders.order_service.OrderService"
COMPOSER_IDENTITY_SERVICE = "src.services.notifications.composer.IdentityService"
SETTINGS_PATCH_TARGETS = (
    "src.core.config.settings",
    "src.services.support.notification_service.settings",
    "src.services.admin_notification_service.settings",
    "src.services.notifications.inline_dispatcher.settings",
)


@pytest.fixture(autouse=True)
def _notification_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATION_INLINE", "1")


@contextmanager
def patch_notification_settings(**values: object) -> Iterator[MagicMock]:
    defaults: dict[str, object] = {
        "TG_BOT_SHOP": "token",
        "TG_ORDERS_CHAT_ID": -100111,
        "TG_SUPPORT_CHAT_ID": -100222,
        "PUBLIC_SITE_URL": "https://shop.test",
    }
    defaults.update(values)
    patches = [patch(target) for target in SETTINGS_PATCH_TARGETS]
    with ExitStack() as stack:
        cfgs = [stack.enter_context(item) for item in patches]
        for cfg in cfgs:
            for key, val in defaults.items():
                setattr(cfg, key, val)
        yield cfgs[0]


def _mock_tg_client(service: object) -> MagicMock:
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=1),
    )
    service.dispatcher.telegram_client = mock_client
    return mock_client


def _mock_composer_identity() -> MagicMock:
    identity = MagicMock()
    identity.get_telegram_id_for_user = AsyncMock(return_value=None)
    identity.get_telegram_username_for_user = AsyncMock(return_value=None)
    return identity


@pytest.mark.asyncio
async def test_notify_support_group_uses_support_chat_id() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=User(id=1, name="Client"))
    service = SupportNotificationService(session)
    mock_client = _mock_tg_client(service)

    with (
        patch_notification_settings(TG_SUPPORT_CHAT_ID=-100222),
        patch(COMPOSER_IDENTITY_SERVICE, return_value=_mock_composer_identity()),
    ):
        await service.notify_support_group(
            ticket_id=5,
            topic="general",
            user=User(id=1, name="Client"),
            order_id=None,
            body="Hello",
            is_new_ticket=True,
        )

    mock_client.send_message.assert_awaited_once()
    chat_id = mock_client.send_message.await_args.kwargs["chat_id"]
    assert chat_id == -100222


@pytest.mark.asyncio
async def test_inline_deliver_marks_support_reply_undelivered_on_tg_fail() -> None:
    session = AsyncMock()
    dispatch = NotificationDispatch(
        channel=NotificationChannel.SUPPORT_CUSTOMER,
        template="support.customer_reply",
        payload={"ticket_id": 1, "user_id": 2, "body": "Hi", "support_message_id": 99},
        idempotency_key="support:customer:ticket:1:msg:99",
    )
    dispatcher = InlineNotificationDispatcher()
    dispatcher.telegram_client = MagicMock()
    dispatcher.telegram_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=False),
    )

    with (
        patch_notification_settings(),
        patch(
            "src.services.notifications.composer.compose_notification",
            new_callable=AsyncMock,
            return_value=MagicMock(
                chat_id=1, text="Hi", parse_mode="HTML", order_id=None
            ),
        ),
        patch(
            "src.services.notifications.inline_dispatcher.CrudSupport"
            ".set_message_telegram_delivered",
            new_callable=AsyncMock,
        ) as set_delivered,
        patch(
            "src.services.notifications.inline_dispatcher.notification_uses_outbox",
            return_value=False,
        ),
    ):
        success = await dispatcher.deliver(session, dispatch)

    assert success is False
    set_delivered.assert_awaited_once_with(99, False)


@pytest.mark.asyncio
async def test_staff_reply_does_not_notify_support_group() -> None:
    session = AsyncMock()
    service = SupportService(session)
    ticket = MagicMock()
    ticket.id = 3
    ticket.user_id = 10
    ticket.status = "waiting_staff"
    ticket.topic = "general"
    ticket.order_id = None
    service.repo = AsyncMock()
    service.repo.get_ticket_by_id = AsyncMock(return_value=ticket)
    service.repo.add_message = AsyncMock(return_value=MagicMock(id=77))
    service.repo.update_ticket_status = AsyncMock()
    service.session = session
    service.session.get = AsyncMock(return_value=User(id=10, name="Buyer"))
    service.session.commit = AsyncMock()
    service.get_ticket_admin = AsyncMock(return_value=MagicMock())

    staff = User(id=99, name="Staff")
    notify_group = AsyncMock()
    notify_customer = AsyncMock(return_value=True)

    with (
        patch(SUPPORT_GROUP_NOTIFY, notify_group),
        patch(SUPPORT_CUSTOMER_NOTIFY, notify_customer),
    ):
        detail, tg_ok = await service.add_staff_reply(3, staff, "Ответ")

    notify_group.assert_not_called()
    notify_customer.assert_awaited_once()
    assert tg_ok is True


@pytest.mark.asyncio
async def test_support_group_telegram_exception_is_swallowed() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=User(id=1, name="Client"))
    service = SupportNotificationService(session)
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(side_effect=RuntimeError("network"))
    service.dispatcher.telegram_client = mock_client

    with (
        patch_notification_settings(TG_SUPPORT_CHAT_ID=-100333),
        patch(COMPOSER_IDENTITY_SERVICE, return_value=_mock_composer_identity()),
    ):
        await service.notify_support_group(
            ticket_id=1,
            topic="general",
            user=User(id=1, name="Client"),
            order_id=None,
            body="Hi",
            is_new_ticket=True,
        )


def test_customer_status_message_human_text() -> None:
    with patch("src.content.client_texts.settings") as cfg:
        cfg.PUBLIC_SITE_URL = "https://shop.test"
        cfg.TG_MINI_APP_URL = "https://t.me/bot/app"
        text = customer_status_message(
            order_id=12,
            status="created",
            customer_name="Алексей",
        )
    assert "<b>Заказ #12 · Ожидает оплаты</b>" in text
    assert "<blockquote>" in text
    assert "Мы получили ваш заказ" in text
    assert "личном кабинете на сайте" in text
    assert "в приложении" in text
    assert "Telegram" not in text
    assert "https://shop.test/account?tab=orders" in text
    assert "https://t.me/bot/app/account?tab=orders" in text

    created_tg = customer_status_message(
        order_id=12,
        status="created",
        for_telegram=True,
    )
    assert "личном кабинете" not in created_tg

    processing = customer_status_message(order_id=12, status="processing")
    assert "начали обработку вашего заказа" in processing
    assert "проверяем наличие товаров" in processing
    assert "О любых изменениях сообщим вам" in processing

    assembling = customer_status_message(order_id=12, status="assembling")
    assert "оформлен у поставщика" in assembling
    assert "Следить за заказом можно" in assembling
    assert "сразу сообщим" not in assembling

    unavailable = format_customer_availability_unavailable_message(order_id=12)
    assert "подтвердить наличие всех товаров не удалось" in unavailable
    assert "обновили состав" not in unavailable


def test_format_customer_telegram_delivery_text_plain_preview_not_duplicated() -> None:
    from src.content.client_texts import format_customer_telegram_delivery_text

    plain_preview = customer_status_message(
        order_id=4058,
        status="completed",
        fmt="plain",
    )
    text = format_customer_telegram_delivery_text(
        custom_message=plain_preview,
        order_id=4058,
        order_status="completed",
    )
    assert text.count("Заказ #4058 · Доставлен") == 1
    assert "Заказ успешно выполнен." in text


def test_cancelled_order_message_not_composition_update() -> None:
    cancelled = customer_status_message(order_id=1502, status="cancelled")
    partial = format_customer_availability_check_message(
        order_id=1502,
        removed_items=[
            {
                "title": "Velocity Nitro 3",
                "variant_label": "blue, black · 39",
                "quantity": 1,
            }
        ],
        new_total=Decimal("4830.00"),
    )

    assert "отменён" in cancelled.lower()
    assert "обновили состав" not in cancelled
    assert "Новая сумма" not in cancelled
    assert "обновили состав" in partial
    assert "Новая сумма" in partial


def test_format_order_delivery_started_message_no_customer_claim() -> None:
    text = format_order_delivery_started_message(
        order_id=15,
        admin_url="https://shop.test/internal/admin/orders?id=15",
    )
    assert "Заказ #15 · Передан в доставку" in text
    assert "Трек-номер появится в админке" in text
    assert "Клиенту" not in text
    assert "https://shop.test" not in text


def test_format_payment_accepted_message_in_orders_notify() -> None:
    text = format_payment_accepted_message(
        order_id=42,
        order_total=Decimal("3000.00"),
        admin_url="https://shop.test/internal/admin/orders?id=42",
        customer_name="Ivan Ivanov",
        payment_method_label="СБП",
    )
    assert "🟢 Клиент оплатил заказ" in text
    assert "Заказ #42" in text
    assert "Клиент: Ivan Ivanov" in text
    assert "3 000 ₽" in text.replace(" ", " ")
    assert "Оплата: СБП" in text
    assert "Попытка #" not in text
    assert "https://shop.test" not in text


@pytest.mark.asyncio
async def test_send_order_payment_accepted_uses_orders_group_chat() -> None:
    session = AsyncMock()
    service = AdminNotificationService(session)
    order = MagicMock(total_amount=Decimal("100"))
    attempt = MagicMock(attempt_number=1)
    mock_os = MagicMock()
    mock_os.order_crud.get_by_id = AsyncMock(return_value=order)
    mock_os.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=attempt)
    mock_client = _mock_tg_client(service)

    with (
        patch_notification_settings(TG_ORDERS_CHAT_ID=-100111),
        patch(COMPOSER_ORDER_SERVICE, return_value=mock_os),
    ):
        await service.send_order_payment_accepted(5, 9)

    mock_client.send_message.assert_awaited_once()
    chat_id = mock_client.send_message.await_args.kwargs["chat_id"]
    assert chat_id == -100111


@pytest.mark.asyncio
async def test_late_payment_sends_distinct_message_to_orders_group() -> None:
    session = AsyncMock()
    service = AdminNotificationService(session)
    order = MagicMock(total_amount=Decimal("2500.00"))
    attempt = MagicMock(attempt_number=3, provider_order_id="sbp-99")
    mock_os = MagicMock()
    mock_os.order_crud.get_by_id = AsyncMock(return_value=order)
    mock_os.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=attempt)
    mock_client = _mock_tg_client(service)

    with (
        patch_notification_settings(TG_ORDERS_CHAT_ID=-100111),
        patch(COMPOSER_ORDER_SERVICE, return_value=mock_os),
    ):
        await service.send_late_payment_after_auto_cancel(1, 2)

    mock_client.send_message.assert_awaited_once()
    chat_id = mock_client.send_message.await_args.kwargs["chat_id"]
    text = mock_client.send_message.await_args.kwargs["text"]
    assert chat_id == -100111
    assert "Поздняя оплата" in text
    assert "sbp-99" in text


def test_customer_payment_late_received_message_is_neutral() -> None:
    text = format_customer_payment_late_received_message(99, fmt="plain")
    assert "уже был отменён" in text
    assert "проверим оплату" in text
    for forbidden in (
        "приступили к обработке",
        "восстановим",
        "вернём",
    ):
        assert forbidden not in text.lower()


@pytest.mark.asyncio
async def test_custom_staff_message_sent_to_customer() -> None:
    user = User(id=10, name="Buyer")
    session = AsyncMock()
    session.get = AsyncMock(return_value=user)
    service = CustomerNotificationService(session)
    order = MagicMock()
    order.id = 4
    order.status = "processing"
    order.user_id = 10
    service.order_crud.get_by_id = AsyncMock(return_value=order)
    mock_client = _mock_tg_client(service)

    with (
        patch(IDENTITY_TG_ID, new_callable=AsyncMock, return_value=123456),
        patch(ORDER_CRUD_GET, new_callable=AsyncMock, return_value=order),
        patch(ORDER_CRUD_EVENT, new_callable=AsyncMock),
        patch(ORDER_CRUD_COMMIT, new_callable=AsyncMock),
        patch_notification_settings(),
    ):
        ok = await service.notify_order_status(
            order_id=4,
            custom_message="Индивидуальный текст от staff",
            created_by="admin",
        )

    assert ok is True
    mock_client.send_message.assert_awaited_once()
    call_kwargs = mock_client.send_message.await_args.kwargs
    assert call_kwargs["chat_id"] == 123456
    assert call_kwargs["parse_mode"] == "HTML"
    assert "Индивидуальный текст от staff" in call_kwargs["text"]
    assert "Заказ #4 · Проверяем наличие" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_notify_order_status_includes_status_snapshot_in_payload() -> None:
    order = MagicMock()
    order.id = 4
    order.status = "processing"
    order.user_id = 10
    session = AsyncMock()
    service = CustomerNotificationService(session)
    service.order_crud.get_by_id = AsyncMock(return_value=order)
    captured: list[NotificationDispatch] = []

    async def capture_enqueue(_session, dispatch: NotificationDispatch) -> bool:
        captured.append(dispatch)
        return True

    service.dispatcher.enqueue = capture_enqueue

    ok = await service.notify_order_status(order_id=4, created_by="admin")

    assert ok is True
    assert len(captured) == 1
    assert captured[0].payload["order_status"] == "processing"


@pytest.mark.asyncio
async def test_compose_order_status_uses_payload_snapshot_not_live_status() -> None:
    from src.services.notifications.composer import compose_notification

    order = MagicMock()
    order.id = 4
    order.status = "assembling"
    order.user_id = 10
    user = User(id=10, name="Buyer")
    session = AsyncMock()
    session.get = AsyncMock(return_value=user)

    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 4, "order_status": "processing"},
        idempotency_key="customer:order_status:order:4:event:test",
    )

    with (
        patch(ORDER_CRUD_GET, new_callable=AsyncMock, return_value=order),
        patch(IDENTITY_TG_ID, new_callable=AsyncMock, return_value=123456),
        patch_notification_settings(),
    ):
        composed = await compose_notification(session, dispatch)

    assert composed is not None
    assert "начали обработку" in composed.text.lower()
    assert "готов к отправке" not in composed.text.lower()


@pytest.mark.asyncio
async def test_staff_reply_outbox_mode_returns_tg_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.delenv("NOTIFICATION_INLINE", raising=False)
    session = AsyncMock()
    service = SupportService(session)
    ticket = MagicMock()
    ticket.id = 3
    ticket.user_id = 10
    ticket.status = "waiting_staff"
    service.repo = AsyncMock()
    service.repo.get_ticket_by_id = AsyncMock(return_value=ticket)
    service.repo.add_message = AsyncMock(return_value=MagicMock(id=77))
    service.repo.update_ticket_status = AsyncMock()
    service.session = session
    service.session.get = AsyncMock(return_value=User(id=10, name="Buyer"))
    service.session.commit = AsyncMock()
    service.get_ticket_admin = AsyncMock(return_value=MagicMock())

    staff = User(id=99, name="Staff")
    notify_customer = AsyncMock(return_value=True)

    with patch(SUPPORT_CUSTOMER_NOTIFY, notify_customer):
        _detail, tg_ok = await service.add_staff_reply(3, staff, "Ответ")

    assert tg_ok is None
    notify_customer.assert_awaited_once()


def test_list_support_reply_templates_prioritizes_matching_topic() -> None:
    templates = list_support_reply_templates("order_question")
    assert templates
    ids = [row["id"] for row in templates]
    assert ids.index("checking_order") < ids.index("delivery_update")


def test_list_support_reply_templates_all_have_body() -> None:
    for row in list_support_reply_templates(None):
        assert row["id"]
        assert row["label"]
        assert row["body"].strip()
