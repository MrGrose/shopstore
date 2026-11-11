import os
import time
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from src.core.config import settings
from src.core.security import create_access_token
from src.main import app
from src.models.support import SupportMessage, SupportMessageAttachment, SupportTicket
from src.repositories.session import async_session_maker
from src.schemas.support import SupportTicketCreateSchema
from src.services.support import SupportService
from src.storage.dual import DualStorage
from src.storage.local import LocalStorage
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)

pytestmark = pytest.mark.integration

SUPPORT_GROUP_NOTIFY = (
    "src.services.support.service.SupportNotificationService.notify_support_group"
)


def _auth_headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _jpeg_bytes(size: int = 8) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (size, size), "red").save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, format="PNG")
    return buf.getvalue()


def _large_jpeg_bytes(min_bytes: int = 2 * 1024 * 1024 + 1) -> bytes:
    width, height = 2200, 1600
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=95)
    data = buf.getvalue()
    assert len(data) >= min_bytes
    return data


@pytest.fixture
def support_fs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    storage = LocalStorage(root=tmp_path)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: storage)
    return storage


# Сдвигает mtime файла, чтобы orphan sweep считал его старше age-window.
def _age_local_object(storage: LocalStorage, key: str, age: timedelta) -> None:
    path = storage._path_for_key(key)
    stamp = time.time() - age.total_seconds()
    os.utime(path, (stamp, stamp))


@pytest.mark.asyncio
async def test_multipart_photo_only_ticket(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 401)
        user_id = user.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        with patch(SUPPORT_GROUP_NOTIFY, new_callable=AsyncMock):
            response = await client.post(
                "/support/tickets",
                headers=_auth_headers(user_id),
                data={"topic": "general", "body": ""},
                files=[("files", ("shot.jpg", _jpeg_bytes(), "image/jpeg"))],
            )

    assert response.status_code == 201
    data = response.json()
    assert data["messages"][0]["body"] == ""
    attachments = data["messages"][0]["attachments"]
    assert len(attachments) == 1
    assert "storage_key" not in attachments[0]
    assert "url" not in attachments[0]
    keys = support_fs.iter_keys("support/")
    assert len(keys) == 1
    assert keys[0].startswith(f"support/{data['id']}/")
    assert keys[0].endswith(".jpg")


@pytest.mark.asyncio
async def test_download_owner_ok_stranger_404(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        owner = await create_telegram_user(session, merge_unique_suffix + 402)
        stranger = await create_telegram_user(session, merge_unique_suffix + 403)
        owner_id, stranger_id = owner.id, stranger.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        with patch(SUPPORT_GROUP_NOTIFY, new_callable=AsyncMock):
            created = await client.post(
                "/support/tickets",
                headers=_auth_headers(owner_id),
                data={"topic": "general", "body": "с фото"},
                files=[("files", ("a.jpg", _jpeg_bytes(), "image/jpeg"))],
            )
        ticket_id = created.json()["id"]
        att_id = created.json()["messages"][0]["attachments"][0]["id"]
        ok = await client.get(
            f"/support/tickets/{ticket_id}/attachments/{att_id}/file",
            headers=_auth_headers(owner_id),
        )
        denied = await client.get(
            f"/support/tickets/{ticket_id}/attachments/{att_id}/file",
            headers=_auth_headers(stranger_id),
        )
        media = await client.get(f"/media/products/{att_id}.jpg")

    assert ok.status_code == 200
    assert ok.headers.get("cache-control") == "private, no-store"
    assert ok.headers.get("content-disposition") == "inline"
    assert ok.content[:2] == b"\xff\xd8"
    assert denied.status_code == 404
    assert media.status_code == 404


@pytest.mark.asyncio
async def test_admin_can_download_attachment(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        owner = await create_telegram_user(session, merge_unique_suffix + 404)
        _admin_id, admin_token = await create_admin_access_token(
            session, merge_unique_suffix + 404
        )
        owner_id = owner.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        with patch(SUPPORT_GROUP_NOTIFY, new_callable=AsyncMock):
            created = await client.post(
                "/support/tickets",
                headers=_auth_headers(owner_id),
                data={"topic": "general", "body": "admin see"},
                files=[("files", ("a.png", _png_bytes(), "image/png"))],
            )
        ticket_id = created.json()["id"]
        att_id = created.json()["messages"][0]["attachments"][0]["id"]
        response = await client.get(
            f"/support/tickets/{ticket_id}/attachments/{att_id}/file",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")


@pytest.mark.asyncio
async def test_reject_too_many_files_and_gif(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 405)
        user_id = user.id

    jpeg = _jpeg_bytes()
    gif = b"GIF89a" + b"\x00" * 20
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        with patch(SUPPORT_GROUP_NOTIFY, new_callable=AsyncMock):
            too_many = await client.post(
                "/support/tickets",
                headers=_auth_headers(user_id),
                data={"topic": "general", "body": "x"},
                files=[("files", (f"{i}.jpg", jpeg, "image/jpeg")) for i in range(11)],
            )
            bad = await client.post(
                "/support/tickets",
                headers=_auth_headers(user_id),
                data={"topic": "general", "body": "x"},
                files=[("files", ("x.gif", gif, "image/gif"))],
            )
    assert too_many.status_code == 400, too_many.text
    assert bad.status_code == 400, bad.text
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_iphone_sized_photo_is_compressed(
    merge_unique_suffix: int, support_fs: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "SUPPORT_ATTACHMENT_MAX_UPLOAD_BYTES", 20 * 1024 * 1024
    )
    original = _large_jpeg_bytes()
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 411)
        token_user_id = user.id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        created = await client.post(
            "/support/tickets",
            headers=_auth_headers(token_user_id),
            data={"topic": "general", "body": ""},
            files=[("files", ("IMG_1234.JPG", original, "image/jpeg"))],
        )
    assert created.status_code == 201, created.text
    data = created.json()
    attachments = data["messages"][0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["content_type"] == "image/jpeg"
    assert attachments[0]["byte_size"] < len(original)
    keys = support_fs.iter_keys("support/")
    assert len(keys) == 1
    assert keys[0].endswith(".jpg")


@pytest.mark.asyncio
async def test_reject_raw_upload_over_limit(
    merge_unique_suffix: int, support_fs: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SUPPORT_ATTACHMENT_MAX_UPLOAD_BYTES", 1024 * 1024)
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 412)
        token_user_id = user.id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/support/tickets",
            headers=_auth_headers(token_user_id),
            data={"topic": "general", "body": "x"},
            files=[
                (
                    "files",
                    (
                        "big.jpg",
                        b"\xff\xd8\xff" + b"\x00" * (1024 * 1024),
                        "image/jpeg",
                    ),
                )
            ],
        )
    assert response.status_code == 400, response.text
    assert "слишком большое" in response.text.lower()
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_multipart_message_body_over_limit_rejected(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 413)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="ok", order_id=None),
        )
        user_id = user.id
        ticket_id = ticket.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/support/tickets/{ticket_id}/messages",
            headers=_auth_headers(user_id),
            data={"body": "x" * 4001},
            files=[("files", ("a.jpg", _jpeg_bytes(), "image/jpeg"))],
        )
    assert response.status_code == 400, response.text
    assert "слишком длинный" in response.text.lower()
    async with async_session_maker() as session:
        _ticket, rows = await SupportService(session).repo.get_ticket_with_messages(
            ticket_id
        )
    assert len(rows) == 1
    assert rows[0].body == "ok"
    assert support_fs.iter_keys("support/") == []


async def test_closed_ticket_cannot_add_photo(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 406)
        service = SupportService(session)
        ticket = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="close", order_id=None),
        )
        await service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
        user_id = user.id
        ticket_id = ticket.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/support/tickets/{ticket_id}/messages",
            headers=_auth_headers(user_id),
            data={"body": ""},
            files=[("files", ("a.jpg", _jpeg_bytes(), "image/jpeg"))],
        )
    assert response.status_code == 400
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_retention_deletes_files_keeps_messages(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 407)
        service = SupportService(session)
        detail = await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="old", order_id=None),
            uploads=[(_jpeg_bytes(), "image/jpeg")],
        )
        await service.close_ticket(
            ticket_id=detail.id,
            actor_user_id=user.id,
            closed_by="customer",
            is_staff=False,
        )
        ticket = await session.get(SupportTicket, detail.id)
        assert ticket is not None
        ticket.closed_at = utc_now_naive() - timedelta(days=181)
        await session.commit()
        ticket_id = detail.id
        att_id = detail.messages[0].attachments[0].id

    assert support_fs.iter_keys("support/")
    async with async_session_maker() as session:
        first = await SupportService(session).purge_expired_attachments(limit=50)
        second = await SupportService(session).purge_expired_attachments(limit=50)
        ticket = await session.get(SupportTicket, ticket_id)
        rows = list(
            (
                await session.scalars(
                    select(SupportMessage).where(SupportMessage.ticket_id == ticket_id)
                )
            ).all()
        )
        atts = list(
            (
                await session.scalars(
                    select(SupportMessageAttachment).where(
                        SupportMessageAttachment.id == att_id
                    )
                )
            ).all()
        )

    assert first["purged"] >= 1
    assert second["purged"] == 0
    assert ticket is not None
    assert ticket.status == "closed"
    assert len(rows) == 1
    assert rows[0].body == "old"
    assert atts == []
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_orphan_support_object_removed(support_fs: LocalStorage) -> None:
    support_fs.put("support/999/orphan.jpg", _jpeg_bytes(), "image/jpeg")
    _age_local_object(support_fs, "support/999/orphan.jpg", timedelta(hours=2))
    async with async_session_maker() as session:
        result = await SupportService(session).purge_expired_attachments(limit=10)
    assert result["orphans"] >= 1
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_fresh_orphan_survives_in_flight_window(
    support_fs: LocalStorage,
) -> None:
    support_fs.put("support/1/in-flight.jpg", _jpeg_bytes(), "image/jpeg")
    async with async_session_maker() as session:
        result = await SupportService(session).purge_expired_attachments(limit=10)
    assert result["orphans"] == 0
    assert support_fs.iter_keys("support/") == ["support/1/in-flight.jpg"]


@pytest.mark.asyncio
async def test_orphan_sweep_skips_fresh_deletes_old(
    support_fs: LocalStorage,
) -> None:
    support_fs.put("support/1/fresh.jpg", _jpeg_bytes(), "image/jpeg")
    support_fs.put("support/1/old.jpg", _jpeg_bytes(), "image/jpeg")
    _age_local_object(support_fs, "support/1/old.jpg", timedelta(hours=2))
    async with async_session_maker() as session:
        result = await SupportService(session).purge_expired_attachments(limit=10)
    assert result["orphans"] == 1
    assert support_fs.iter_keys("support/") == ["support/1/fresh.jpg"]


@pytest.mark.asyncio
async def test_delete_for_user_removes_storage(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 408)
        service = SupportService(session)
        await service.create_ticket(
            user.id,
            SupportTicketCreateSchema(topic="general", body="bye", order_id=None),
            uploads=[(_jpeg_bytes(), "image/jpeg")],
        )
        user_id = user.id
    assert support_fs.iter_keys("support/")
    async with async_session_maker() as session:
        await SupportService(session).delete_for_user(user_id)
        await session.commit()
        tickets = list(
            (
                await session.scalars(
                    select(SupportTicket).where(SupportTicket.user_id == user_id)
                )
            ).all()
        )
    assert tickets == []
    assert support_fs.iter_keys("support/") == []


@pytest.mark.asyncio
async def test_db_failure_after_put_deletes_object(
    merge_unique_suffix: int, support_fs: LocalStorage
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 409)
        service = SupportService(session)
        with patch.object(
            service.repo, "add_attachment", side_effect=RuntimeError("db down")
        ):
            with pytest.raises(RuntimeError, match="db down"):
                await service.create_ticket(
                    user.id,
                    SupportTicketCreateSchema(
                        topic="general", body="fail", order_id=None
                    ),
                    uploads=[(_jpeg_bytes(), "image/jpeg")],
                )
    assert support_fs.iter_keys("support/") == []


# S3-нога Dual: put падает, объекта нет, delete — no-op.
class _FailingS3PutStorage:
    # Имитирует падение S3 put после успешного local put.
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        raise RuntimeError("s3 put failed")

    # Ключа на S3 нет — delete ничего не делает.
    def delete(self, key: str) -> None:
        return None

    # Объекта на S3 нет.
    def exists(self, key: str) -> bool:
        return False

    # Чтение с пустого S3.
    def read(self, key: str) -> bytes:
        raise FileNotFoundError(key)

    # Не используется в F4 rollback.
    def public_url(self, key: str) -> str:
        return f"/media/products/{key}"

    # Пустой список ключей.
    def iter_keys(self, prefix: str = "") -> list[str]:
        return []

    # Пустые mtime.
    def iter_key_mtimes(self, prefix: str = "") -> list[tuple[str, object]]:
        return []


@pytest.mark.asyncio
async def test_dual_s3_put_failure_deletes_local_object(
    merge_unique_suffix: int, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalStorage(root=tmp_path)
    dual = DualStorage(_FailingS3PutStorage(), local)
    monkeypatch.setattr("src.services.support.service.get_storage", lambda: dual)
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 414)
        service = SupportService(session)
        with pytest.raises(RuntimeError, match="s3 put failed"):
            await service.create_ticket(
                user.id,
                SupportTicketCreateSchema(topic="general", body="dual", order_id=None),
                uploads=[(_jpeg_bytes(), "image/jpeg")],
            )
    assert local.iter_keys("support/") == []
    assert local.iter_keys() == []
