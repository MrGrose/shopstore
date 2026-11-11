from unittest.mock import AsyncMock, MagicMock

import pytest

from src.content.client_texts import (
    customer_status_message,
    format_customer_manual_message,
)
from src.services.notifications.composer import (
    _admin_orders_template_text,
    _customer_template_text,
)
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)


def test_customer_status_message_plain_has_no_html_tags() -> None:
    text = customer_status_message(42, "created", fmt="plain")

    assert "<b>" not in text
    assert "<a " not in text
    assert "Заказ #42" in text
    assert "Ожидает оплаты" in text


@pytest.mark.asyncio
async def test_customer_template_text_plain_order_status() -> None:
    order = MagicMock()
    order.id = 296
    order.status = "processing"
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={"order_id": 296, "order_status": "processing"},
    )

    text = _customer_template_text(dispatch, order, None, fmt="plain")

    assert text is not None
    assert "<" not in text
    assert "Заказ #296" in text


def test_customer_template_text_plain_order_status_ignores_html_custom_message() -> (
    None
):
    order = MagicMock()
    order.id = 4055
    order.status = "completed"
    html_custom = customer_status_message(4055, "completed")
    dispatch = NotificationDispatch(
        channel=NotificationChannel.EMAIL,
        template="order_status",
        payload={
            "order_id": 4055,
            "order_status": "completed",
            "custom_message": html_custom,
        },
    )

    text = _customer_template_text(dispatch, order, None, fmt="plain")

    assert text is not None
    assert "<" not in text
    assert "Заказ #4055 · Доставлен" in text
    assert "Заказ успешно выполнен." in text


def test_shipment_delivered_custom_message_is_not_in_transit() -> None:
    order = MagicMock()
    order.id = 230
    order.status = "delivery"
    dispatch = NotificationDispatch(
        channel=NotificationChannel.CUSTOMER,
        template="order_status",
        payload={
            "order_id": 230,
            "order_status": "shipment_delivered",
            "custom_message": "Посылка1 доставлена Бро",
        },
    )

    text = _customer_template_text(dispatch, order, None)

    assert text is not None
    assert "В пути" not in text
    assert "Посылка доставлена" in text
    assert "Посылка1 доставлена Бро" in text


def test_customer_manual_message_telegram_has_order_without_status() -> None:
    text = format_customer_manual_message(4057, "тест тг")

    assert text == "<b>Заказ #4057</b>\n\n<blockquote>тест тг</blockquote>"
    assert "В пути" not in text
    assert "·" not in text


def test_customer_manual_message_email_uses_same_header_as_telegram() -> None:
    order = MagicMock()
    order.id = 4057
    order.status = "delivery"
    dispatch = NotificationDispatch(
        channel=NotificationChannel.EMAIL,
        template="customer.manual",
        payload={"order_id": 4057, "message": "тест email"},
    )

    text = _customer_template_text(dispatch, order, None, fmt="plain")

    assert text == "Заказ #4057\n\nтест email"
    assert "В пути" not in text


@pytest.mark.asyncio
async def test_admin_payment_accepted_template_uses_customer_and_attempt_provider() -> (
    None
):
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    order = MagicMock()
    order.id = 42
    order.user_id = 7
    order.first_name = "Ivan"
    order.last_name = "Ivanov"
    order.total_amount = 3000
    order.payment_paid_at = None
    order.payment_provider = None
    attempt = MagicMock(provider="sbp")
    order_service = MagicMock()
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=attempt)
    dispatch = NotificationDispatch(
        channel=NotificationChannel.ADMIN_ORDERS,
        template="payment.accepted",
        payload={"order_id": 42, "attempt_id": 9},
    )

    text = await _admin_orders_template_text(session, order_service, dispatch)

    assert text is not None
    assert "🟢 Клиент оплатил заказ" in text
    assert "Заказ #42" in text
    assert "Клиент: Ivan Ivanov" in text
    assert "Оплата: СБП" in text
    assert "Попытка #" not in text
