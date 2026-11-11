from unittest.mock import patch

import pytest

from src.core.config import settings
from src.models.order import Order
from src.services.notifications.composer import compose_notification
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)
from tests.integration.helpers.order_admin import create_telegram_user
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_admin_notification_payment_accepted_message_from_db(
    merge_unique_suffix: int,
) -> None:
    from datetime import timedelta

    from src.repositories.order_repo import CrudOrder
    from src.repositories.session import async_session_maker
    from src.utils.datetime_fmt import utc_now_naive

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 700)
        order = await _create_unpaid_order(
            session,
            user.id,
            merge_unique_suffix + 700,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        order_crud = CrudOrder(session=session, model=Order)
        attempt = await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=int(order.total_amount * 100),
            payment_currency="RUB",
            init_state="ready",
        )
        await session.commit()

        dispatch = NotificationDispatch(
            channel=NotificationChannel.ADMIN_ORDERS,
            template="payment.accepted",
            payload={"order_id": order.id, "attempt_id": attempt.id},
            idempotency_key=(
                f"admin:payment.accepted:order:{order.id}:attempt:{attempt.id}"
            ),
        )
        with patch.object(settings, "TG_ORDERS_CHAT_ID", -100111):
            composed = await compose_notification(session, dispatch)
        assert composed is not None
        text = composed.text
        assert "🟢 Клиент оплатил заказ" in text
        assert f"Заказ #{order.id}" in text
        assert "Оплата: СБП" in text
        assert "Попытка #" not in text
