from io import BytesIO
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from src.core.security import create_access_token
from src.main import app
from src.models.support import SupportMessage, SupportTicket
from src.repositories.session import async_session_maker
from src.schemas.support import SupportTicketCreateSchema
from src.services.support import SupportService
from src.storage.local import LocalStorage
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)

pytestmark = pytest.mark.integration

NOTIFY = "src.services.support.service.SupportNotificationService.notify_support_group"


# Миниатюрный JPEG для upload в support.
def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_admin_support_bulk_delete_selected(
    tmp_path, monkeypatch: pytest.MonkeyPatch, merge_unique_suffix: int
) -> None:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix + 510)
        user = await create_telegram_user(session, merge_unique_suffix + 511)
        payload = SupportTicketCreateSchema(topic="general", body="")
        with patch(NOTIFY, new_callable=AsyncMock):
            detail = await SupportService(session).create_ticket(
                int(user.id),
                payload,
                uploads=[(_jpeg_bytes(), "image/jpeg")],
            )
        ticket_id = int(detail.id)

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        listing = await client.get("/internal/admin/support", headers=headers)
        assert listing.status_code == 200
        assert "data-support-delete-checkbox" in listing.text
        assert f'value="{ticket_id}"' in listing.text
        assert 'id="admin-support-delete-btn"' in listing.text

        delete = await client.post(
            "/internal/admin/support/delete-selected",
            headers=headers,
            data={"ticket_ids": str(ticket_id)},
        )
        assert delete.status_code == 200, delete.text
        payload = delete.json()
        assert payload["deleted"] == 1

    async with async_session_maker() as session:
        assert await session.get(SupportTicket, ticket_id) is None
        messages = list(
            await session.scalars(
                select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
            )
        )
        assert messages == []
    assert storage.iter_keys(f"support/{ticket_id}/") == []


@pytest.mark.asyncio
async def test_admin_support_delete_requires_admin(
    tmp_path, monkeypatch: pytest.MonkeyPatch, merge_unique_suffix: int
) -> None:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 512)
        payload = SupportTicketCreateSchema(topic="general", body="stay")
        with patch(NOTIFY, new_callable=AsyncMock):
            detail = await SupportService(session).create_ticket(int(user.id), payload)
        ticket_id = int(detail.id)
        customer_token = create_access_token(int(user.id))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await client.post(
            "/internal/admin/support/delete-selected",
            headers={"Authorization": f"Bearer {customer_token}"},
            data={"ticket_ids": str(ticket_id)},
        )
        assert response.status_code in (302, 303, 401, 403)

    async with async_session_maker() as session:
        assert await session.get(SupportTicket, ticket_id) is not None
