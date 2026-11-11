import json
from datetime import UTC, datetime

import pytest

from src.services.verification.phone.session_store import PhoneSessionStore


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, 60)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_session_store_save_and_load_without_code():
    redis = _FakeRedis()
    store = PhoneSessionStore(redis)
    await store.save("+79991234567", "login", "req-123")
    session = await store.load("+79991234567", "login")
    assert session is not None
    assert session.request_id == "req-123"
    assert session.attempts == 0
    raw = redis.store["phone_verify:+79991234567"]
    record = json.loads(raw)
    assert "code" not in record


@pytest.mark.asyncio
async def test_session_store_increment_attempts():
    redis = _FakeRedis()
    store = PhoneSessionStore(redis)
    await store.save("+79991234567", "login", "req-123")
    session = await store.load("+79991234567", "login")
    assert session is not None
    session.sent_at = datetime.now(tz=UTC)
    await store.increment_attempts("+79991234567", "login", session)
    updated = await store.load("+79991234567", "login")
    assert updated is not None
    assert updated.attempts == 1


@pytest.mark.asyncio
async def test_session_store_link_key_isolated_by_user_id():
    redis = _FakeRedis()
    store = PhoneSessionStore(redis)
    await store.save("+79991234567", "link", "req-link-1", user_id=10)
    await store.save("+79991234567", "link", "req-link-2", user_id=20)

    session_10 = await store.load("+79991234567", "link", user_id=10)
    session_20 = await store.load("+79991234567", "link", user_id=20)

    assert session_10 is not None
    assert session_10.request_id == "req-link-1"
    assert session_20 is not None
    assert session_20.request_id == "req-link-2"
    assert "phone_verify:link:10:+79991234567" in redis.store
    assert "phone_verify:link:20:+79991234567" in redis.store


@pytest.mark.asyncio
async def test_session_store_login_key_differs_from_link():
    redis = _FakeRedis()
    store = PhoneSessionStore(redis)
    await store.save("+79991234567", "login", "req-login")
    await store.save("+79991234567", "link", "req-link", user_id=5)

    login_session = await store.load("+79991234567", "login")
    link_session = await store.load("+79991234567", "link", user_id=5)

    assert login_session is not None
    assert login_session.request_id == "req-login"
    assert link_session is not None
    assert link_session.request_id == "req-link"
