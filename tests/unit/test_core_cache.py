import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.cache import (
    CATALOG_VERSION_KEY,
    build_versioned_key,
    cached_get,
    get_catalog_version,
    invalidate_catalog_version,
    single_flight,
)


def test_build_versioned_key_returns_expected_key() -> None:
    key = build_versioned_key("catalog:count:", 42, "abc123def456")
    assert key == "catalog:count:v42:abc123def456"


def test_invalidate_catalog_version_increments_key() -> None:
    client = MagicMock()
    client.incr.return_value = 7

    with patch("src.core.cache.sync_redis_text", return_value=client):
        version = invalidate_catalog_version()

    client.incr.assert_called_once_with(CATALOG_VERSION_KEY)
    assert version == 7


@pytest.mark.asyncio
async def test_get_catalog_version_returns_zero_when_missing() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)

    with patch("src.core.cache.async_redis", return_value=redis):
        version = await get_catalog_version()

    assert version == 0
    redis.get.assert_awaited_once_with(CATALOG_VERSION_KEY)


@pytest.mark.asyncio
async def test_get_catalog_version_parses_stored_value() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="12")

    with patch("src.core.cache.async_redis", return_value=redis):
        version = await get_catalog_version()

    assert version == 12


@pytest.mark.asyncio
async def test_cached_get_returns_cached_value_on_hit() -> None:
    fetch_fn = AsyncMock(return_value=99)

    with patch(
        "src.core.cache.catalog_cache_get",
        new=AsyncMock(return_value="15"),
    ):
        result = await cached_get(
            "count",
            "catalog:count:v1:abc",
            120,
            fetch_fn,
            str,
            int,
        )

    assert result == 15
    fetch_fn.assert_not_called()


@pytest.mark.asyncio
async def test_cached_get_fetches_and_sets_on_miss() -> None:
    fetch_fn = AsyncMock(return_value=42)
    setex = AsyncMock()

    with (
        patch(
            "src.core.cache.catalog_cache_get",
            new=AsyncMock(return_value=None),
        ),
        patch("src.core.cache.catalog_cache_setex", new=setex),
    ):
        result = await cached_get(
            "facets",
            "catalog:facets:v2:xyz",
            60,
            fetch_fn,
            str,
            int,
        )

    assert result == 42
    fetch_fn.assert_called_once_with()
    setex.assert_awaited_once_with("facets", "catalog:facets:v2:xyz", 60, "42")


@pytest.mark.asyncio
async def test_reference_ttl_cache_expires() -> None:
    from src.core.cache import get_reference_ttl_cache, set_reference_ttl_cache

    set_reference_ttl_cache("ttl-test", "value", ttl=1)
    assert get_reference_ttl_cache("ttl-test") == "value"
    await asyncio.sleep(1.05)
    assert get_reference_ttl_cache("ttl-test") is None


@pytest.mark.asyncio
async def test_single_flight_calls_fetch_fn_once_for_parallel_requests() -> None:
    calls = 0

    async def fetch_fn() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return calls

    results = await asyncio.gather(
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
        single_flight("flight-key", fetch_fn),
    )

    assert calls == 1
    assert results == [1] * 10
