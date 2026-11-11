import httpx
import pytest
from sqlalchemy import select

from src.main import app
from src.models.order import OrderEvent
from src.repositories.session import async_session_maker
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)
from tests.integration.test_order_availability_sync import _create_processing_order

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_admin_order_comment_post(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/internal/admin/orders/{order_id}/comment",
            data={"event_message": "Позвонил поставщику", "return_page": "1"},
            headers={"Authorization": f"Bearer {admin_token}"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "success=" in response.headers.get("location", "")

    async with async_session_maker() as session:
        event = await session.scalar(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == "admin_comment",
            )
            .order_by(OrderEvent.id.desc())
        )

    assert event is not None
    assert event.event_message == "Позвонил поставщику"
