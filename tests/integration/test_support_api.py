from datetime import timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.core.security import create_access_token
from src.main import app
from src.models.order import OrderStatus
from src.models.user import User
from src.repositories.session import async_session_maker
from src.schemas.support import SupportTicketCreateSchema
from src.services.support import SupportService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)
from tests.integration.helpers.support_orders import seed_support_order

pytestmark = pytest.mark.integration

SUPPORT_GROUP_NOTIFY = (
    "src.services.support.service.SupportNotificationService.notify_support_group"
)
SUPPORT_CUSTOMER_NOTIFY = (
    "src.services.support.service.SupportNotificationService"
    ".notify_customer_staff_reply"
)


def _auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.fixture(autouse=True)
def _mute_support_customer_telegram():
    with patch(SUPPORT_CUSTOMER_NOTIFY, new_callable=AsyncMock, return_value=True):
        yield


@pytest.mark.asyncio
async def test_create_ticket_without_order(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 1)
        user_id = user.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/support/tickets",
            headers=_auth_headers(user_id),
            json={"topic": "general", "body": "Вопрос без заказа", "order_id": None},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "waiting_staff"
    assert data["order_id"] is None
    assert data["messages"][0]["body"] == "Вопрос без заказа"


@pytest.mark.asyncio
async def test_list_tickets_returns_pagination(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 50)
        user_id = user.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/tickets?page=1&page_size=10",
            headers=_auth_headers(user_id),
        )

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert "total_pages" in data


@pytest.mark.asyncio
async def test_create_ticket_with_linkable_order(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 2)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 2,
            payment_due_at=utc_now_naive() + timedelta(hours=3),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/support/tickets",
            headers=_auth_headers(user.id),
            json={
                "topic": "order_question",
                "body": "Вопрос по заказу",
                "order_id": order.id,
            },
        )

    assert response.status_code == 201
    assert response.json()["order_id"] == order.id


@pytest.mark.asyncio
async def test_create_ticket_rejects_foreign_order(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        owner = await create_telegram_user(session, merge_unique_suffix + 3)
        other = await create_telegram_user(session, merge_unique_suffix + 4)
        order = await seed_support_order(session, owner.id, merge_unique_suffix + 3)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/support/tickets",
            headers=_auth_headers(other.id),
            json={
                "topic": "order_question",
                "body": "Чужой заказ",
                "order_id": order.id,
            },
        )

    assert response.status_code == 400
    assert "недоступен" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_ticket_rejects_unlinkable_completed_order(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 5)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 5,
            status=OrderStatus.COMPLETED,
            payment_paid_at=utc_now_naive() - timedelta(days=1),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/support/tickets",
            headers=_auth_headers(user.id),
            json={
                "topic": "order_question",
                "body": "Завершённый заказ",
                "order_id": order.id,
            },
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_linkable_orders_includes_unpaid_younger_24h(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 6)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 6,
            payment_due_at=utc_now_naive() + timedelta(hours=2),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/linkable-orders",
            headers=_auth_headers(user.id),
        )

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert order.id in ids


@pytest.mark.asyncio
async def test_linkable_orders_excludes_unpaid_older_24h(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 7)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 7,
            payment_due_at=utc_now_naive() - timedelta(hours=1),
            created_at=utc_now_naive() - timedelta(hours=25),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/linkable-orders",
            headers=_auth_headers(user.id),
        )

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert order.id not in ids


@pytest.mark.asyncio
async def test_linkable_orders_includes_paid_not_completed(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 8)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 8,
            status=OrderStatus.PROCESSING,
            payment_paid_at=utc_now_naive() - timedelta(hours=1),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/linkable-orders",
            headers=_auth_headers(user.id),
        )

    assert response.status_code == 200
    assert order.id in {row["id"] for row in response.json()}


@pytest.mark.asyncio
async def test_linkable_orders_excludes_completed_order(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 9)
        order = await seed_support_order(
            session,
            user.id,
            merge_unique_suffix + 9,
            status=OrderStatus.COMPLETED,
            payment_paid_at=utc_now_naive() - timedelta(days=2),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/linkable-orders",
            headers=_auth_headers(user.id),
        )

    assert response.status_code == 200
    assert order.id not in {row["id"] for row in response.json()}


@pytest.mark.asyncio
async def test_user_sees_only_own_tickets(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user_a = await create_telegram_user(session, merge_unique_suffix + 10)
        user_b = await create_telegram_user(session, merge_unique_suffix + 11)
        service = SupportService(session)
        ticket_a = await service.create_ticket(
            user_a.id,
            SupportTicketCreateSchema(topic="general", body="A", order_id=None),
        )
        await service.create_ticket(
            user_b.id,
            SupportTicketCreateSchema(topic="general", body="B", order_id=None),
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/support/tickets",
            headers=_auth_headers(user_a.id),
        )

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["items"]}
    assert ticket_a.id in ids
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_new_ticket_has_waiting_staff_status(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 12)
        detail = await SupportService(session).create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Новое", order_id=None),
        )
    assert detail.status == "waiting_staff"


@pytest.mark.asyncio
async def test_staff_reply_sets_waiting_customer(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 13)
        admin_id, _token = await create_admin_access_token(
            session, merge_unique_suffix + 13
        )
        admin = await session.get(User, admin_id)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Help", order_id=None),
        )
        detail, _tg_ok = await service.add_staff_reply(ticket.id, admin, "Ответ staff")
    assert detail.status == "waiting_customer"
    assert detail.messages[-1].author_type == "staff"


@pytest.mark.asyncio
async def test_customer_message_sets_waiting_staff(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 14)
        admin_id, _token = await create_admin_access_token(
            session, merge_unique_suffix + 14
        )
        admin = await session.get(User, admin_id)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Help", order_id=None),
        )
        await service.add_staff_reply(ticket.id, admin, "Ответ")
        detail = await service.add_customer_message(user.id, ticket.id, "Уточнение")
    assert detail.status == "waiting_staff"


@pytest.mark.asyncio
async def test_customer_can_close_ticket(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 15)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Close me", order_id=None),
        )
        detail = await service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
    assert detail.status == "closed"
    assert detail.closed_at is not None


@pytest.mark.asyncio
async def test_staff_can_close_ticket(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 16)
        admin_id, _token = await create_admin_access_token(
            session, merge_unique_suffix + 16
        )
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(
                topic="general", body="Staff close", order_id=None
            ),
        )
        detail = await service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=admin_id,
            closed_by="staff",
            is_staff=True,
        )
    assert detail.status == "closed"


@pytest.mark.asyncio
async def test_closed_ticket_cannot_reopen(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 17)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Closed", order_id=None),
        )
        await service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
        with pytest.raises(ValueError, match="закрыто"):
            await service.close_ticket(
                ticket_id=ticket.id,
                actor_user_id=user.id,
                closed_by="customer",
                is_staff=False,
            )


@pytest.mark.asyncio
async def test_cannot_write_to_closed_ticket(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 18)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Done", order_id=None),
        )
        await service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
        with pytest.raises(ValueError, match="закрыто"):
            await service.add_customer_message(user.id, ticket.id, "Ещё вопрос")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/support/tickets/{ticket.id}/messages",
            headers=_auth_headers(user.id),
            json={"body": "Ещё вопрос"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_telegram_failure_does_not_delete_saved_ticket(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_INLINE", "1")
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 19)
        user_id = user.id

    with patch(
        "src.integrations.telegram_client.TelegramClient.send_message",
        new_callable=AsyncMock,
        side_effect=RuntimeError("TG down"),
    ):
        async with async_session_maker() as session:
            detail = await SupportService(session).create_ticket(
                user_id,
                SupportTicketCreateSchema(
                    topic="general", body="Persist me", order_id=None
                ),
            )

    assert detail.status == "waiting_staff"
    async with async_session_maker() as session:
        tickets = (await SupportService(session).list_tickets_for_user(user_id)).items
    assert len(tickets) == 1
    assert tickets[0].last_message_preview == "Persist me"


@pytest.mark.asyncio
async def test_open_support_ticket_counts_for_order_and_nav(
    merge_unique_suffix: int,
) -> None:
    from src.web.admin_nav import fetch_admin_nav_badges

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 20)
        order = await seed_support_order(session, user.id, merge_unique_suffix + 20)
        service = SupportService(session)
        await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="One", order_id=order.id),
        )
        await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Two", order_id=order.id),
        )
        closed = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Closed", order_id=None),
        )
        await service.close_ticket(
            ticket_id=closed.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
        counts = await service.count_open_tickets_by_order_ids([order.id])
        badges = await fetch_admin_nav_badges(session)

    assert counts[order.id] == 2
    assert badges["open_support_tickets"] >= 2


@pytest.mark.asyncio
async def test_staff_reply_records_telegram_delivery_failure(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_INLINE", "1")
    monkeypatch.setenv("NOTIFICATION_MODE", "inline")
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 21)
        admin_id, _token = await create_admin_access_token(
            session, merge_unique_suffix + 21
        )
        admin = await session.get(User, admin_id)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Help", order_id=None),
        )

    with patch(SUPPORT_CUSTOMER_NOTIFY, new_callable=AsyncMock, return_value=False):
        async with async_session_maker() as session:
            detail, tg_ok = await SupportService(session).add_staff_reply(
                ticket.id,
                admin,
                "Ответ без TG",
            )

    assert tg_ok is False
    staff_messages = [m for m in detail.messages if m.author_type == "staff"]
    assert staff_messages[-1].telegram_delivered is None


@pytest.mark.asyncio
async def test_client_api_hides_telegram_delivered(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 22)
        admin_id, _token = await create_admin_access_token(
            session, merge_unique_suffix + 22
        )
        admin = await session.get(User, admin_id)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="Help", order_id=None),
        )
        ticket_id = ticket.id
        user_id = user.id

    with patch(SUPPORT_CUSTOMER_NOTIFY, new_callable=AsyncMock, return_value=False):
        async with async_session_maker() as session:
            await SupportService(session).add_staff_reply(
                ticket_id,
                admin,
                "Ответ staff",
            )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            f"/support/tickets/{ticket_id}",
            headers=_auth_headers(user_id),
        )

    assert response.status_code == 200
    data = response.json()
    for msg in data["messages"]:
        assert "telegram_delivered" not in msg
