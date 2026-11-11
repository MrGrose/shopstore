from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

from src.jobs import dom_enqueue_lock
from src.services.verification.phone.rate_limit import PhoneRateLimiter
from src.services.verification.phone.session_store import PhoneSessionStore


class _BrokenRedis:
    async def setex(self, *_args, **_kwargs):
        raise RedisError("down")

    async def get(self, *_args, **_kwargs):
        raise RedisError("down")

    async def ttl(self, *_args, **_kwargs):
        raise RedisError("down")

    async def delete(self, *_args, **_kwargs):
        raise RedisError("down")

    async def ping(self):
        raise RedisError("down")

    async def exists(self, *_args, **_kwargs):
        raise RedisError("down")


_PRODUCT = {"item_id": "sku-1", "product_url": "https://example.com/p/1"}


@pytest.mark.asyncio
async def test_session_store_save_falls_back_to_db_on_redis_error():
    store = PhoneSessionStore(_BrokenRedis())
    with patch.object(
        store,
        "_save_db",
        new=AsyncMock(),
    ) as save_db:
        await store.save("+79991234567", "login", "req-db-1")
    save_db.assert_awaited_once()
    assert save_db.await_args.args[1] == "req-db-1"


@pytest.mark.asyncio
async def test_session_store_load_falls_back_to_db_on_redis_error():
    store = PhoneSessionStore(_BrokenRedis())
    expected = MagicMock()
    with patch.object(
        store,
        "_load_db",
        new=AsyncMock(return_value=expected),
    ) as load_db:
        session = await store.load("+79991234567", "login")
    load_db.assert_awaited_once()
    assert session is expected


@pytest.mark.asyncio
async def test_session_store_load_skips_db_when_redis_miss():
    class _EmptyRedis:
        async def get(self, _key: str) -> None:
            return None

    store = PhoneSessionStore(_EmptyRedis())
    with patch.object(
        store,
        "_load_db",
        new=AsyncMock(),
    ) as load_db:
        session = await store.load("+79991234567", "login")
    load_db.assert_not_awaited()
    assert session is None


@pytest.mark.asyncio
async def test_rate_limiter_skips_send_check_when_redis_down():
    limiter = PhoneRateLimiter(_BrokenRedis())
    await limiter.assert_send_allowed("+79991234567", "1.2.3.4")


@pytest.mark.asyncio
async def test_rate_limiter_skips_record_send_when_redis_down():
    limiter = PhoneRateLimiter(_BrokenRedis())
    await limiter.record_send("+79991234567", "1.2.3.4")


def test_dom_enqueue_lock_acquire_bypasses_when_redis_down(monkeypatch):
    redis = MagicMock()
    redis.set.side_effect = RedisError("down")
    monkeypatch.setattr(dom_enqueue_lock, "sync_redis", lambda: redis)
    assert dom_enqueue_lock.try_acquire_dom_enqueue_lock(_PRODUCT, 600, "owner-a")


def test_dom_enqueue_lock_release_ignores_redis_down(monkeypatch):
    redis = MagicMock()
    redis.register_script.return_value = MagicMock(side_effect=RedisError("down"))
    monkeypatch.setattr(dom_enqueue_lock, "sync_redis", lambda: redis)
    dom_enqueue_lock.release_dom_enqueue_lock(_PRODUCT, "owner-a")
