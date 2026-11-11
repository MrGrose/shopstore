import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.support import SupportMessage, SupportMessageAttachment, SupportTicket
from src.repositories.session import async_session_maker
from src.schemas.support import SupportTicketCreateSchema
from src.services.support import SupportService
from src.storage.local import LocalStorage
from tests.integration.helpers.order_admin import create_telegram_user

NOTIFY = "src.services.support.service.SupportNotificationService.notify_support_group"


# Миниатюрный JPEG для upload в support.
def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="JPEG")
    return buf.getvalue()


# Создаёт обращение, опционально с фото.
async def _create_ticket(
    session,
    user_id: int,
    body: str = "hello",
    uploads: list[tuple[bytes, str]] | None = None,
):
    payload = SupportTicketCreateSchema(topic="general", body=body)
    with patch(NOTIFY, new_callable=AsyncMock):
        return await SupportService(session).create_ticket(
            user_id, payload, uploads=uploads
        )


@pytest.mark.asyncio
async def test_admin_delete_tickets_requires_selection() -> None:
    async with async_session_maker() as session:
        service = SupportService(session)
        with pytest.raises(ValueError, match="Не выбраны обращения"):
            await service.admin_delete_tickets_by_ids([])


@pytest.mark.asyncio
async def test_admin_delete_ticket_cascades_messages_and_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    suffix = uuid.uuid4().int % 90_000_000 + 501_000
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        user_id = int(user.id)
        detail = await _create_ticket(
            session,
            user_id,
            body="",
            uploads=[(_jpeg_bytes(), "image/jpeg")],
        )
        ticket_id = int(detail.id)
        keys_before = storage.iter_keys("support/")
        assert keys_before
        assert all(key.startswith(f"support/{ticket_id}/") for key in keys_before)

        deleted = await SupportService(session).admin_delete_tickets_by_ids([ticket_id])
        assert deleted == 1

    async with async_session_maker() as session:
        assert await session.get(SupportTicket, ticket_id) is None
        messages = list(
            await session.scalars(
                select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
            )
        )
        assert messages == []
        attachments = list(await session.scalars(select(SupportMessageAttachment)))
        assert all(
            not att.storage_key.startswith(f"support/{ticket_id}/")
            for att in attachments
        )
    assert storage.iter_keys(f"support/{ticket_id}/") == []


@pytest.mark.asyncio
async def test_admin_delete_ticket_a_leaves_ticket_b(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    suffix = uuid.uuid4().int % 90_000_000 + 502_000
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        user_id = int(user.id)
        first = await _create_ticket(
            session, user_id, uploads=[(_jpeg_bytes(), "image/jpeg")]
        )
        second = await _create_ticket(
            session, user_id, body="keep me", uploads=[(_jpeg_bytes(), "image/jpeg")]
        )
        first_id, second_id = int(first.id), int(second.id)
        deleted = await SupportService(session).admin_delete_tickets_by_ids([first_id])
        assert deleted == 1

    async with async_session_maker() as session:
        assert await session.get(SupportTicket, first_id) is None
        kept = await session.get(SupportTicket, second_id)
        assert kept is not None
        messages = list(
            await session.scalars(
                select(SupportMessage).where(SupportMessage.ticket_id == second_id)
            )
        )
        assert messages
    leftover = storage.iter_keys("support/")
    assert leftover
    assert all(key.startswith(f"support/{second_id}/") for key in leftover)


@pytest.mark.asyncio
async def test_admin_delete_ticket_removes_prefix_orphan(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    suffix = uuid.uuid4().int % 90_000_000 + 503_000
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        detail = await _create_ticket(session, int(user.id), body="orphan-check")
        ticket_id = int(detail.id)
        orphan_key = f"support/{ticket_id}/orphan.jpg"
        storage.put(orphan_key, b"not-a-db-row", "image/jpeg")
        deleted = await SupportService(session).admin_delete_tickets_by_ids([ticket_id])
        assert deleted == 1
    assert orphan_key not in storage.iter_keys("support/")
    assert storage.iter_keys(f"support/{ticket_id}/") == []


@pytest.mark.asyncio
async def test_admin_delete_tickets_integrity_error_is_value_error() -> None:
    async with async_session_maker() as session:
        service = SupportService(session)
        with patch.object(
            service.repo,
            "delete_tickets_by_ids",
            side_effect=IntegrityError("", {}, Exception()),
        ):
            with pytest.raises(ValueError, match="Не удалось удалить обращения"):
                await service.admin_delete_tickets_by_ids([1])
