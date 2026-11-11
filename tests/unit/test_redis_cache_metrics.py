import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.redis import reset_cache_metrics
from src.core.redis.async_ import catalog_cache_get, catalog_cache_setex
from src.core.redis.metrics import cache_hit_ratio
from src.services.catalog.read.count_cache import get_cached_count, set_cached_count


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    reset_cache_metrics()


@pytest.mark.asyncio
async def test_catalog_cache_get_logs_hit_and_latency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="42")
    caplog.set_level(logging.INFO)

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        result = await catalog_cache_get("count", "catalog:count:abc")

    assert result == "42"
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "redis_latency_ms operation=get cache_type=count" in msg for msg in messages
    )
    assert any("redis_hit cache_type=count hit_ratio=1.0" in msg for msg in messages)
    assert cache_hit_ratio("count") == 1.0


@pytest.mark.asyncio
async def test_catalog_cache_get_logs_miss_and_latency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    caplog.set_level(logging.INFO)

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        result = await catalog_cache_get("facets", "catalog:facets:abc")

    assert result is None
    messages = [record.getMessage() for record in caplog.records]
    assert any("redis_miss cache_type=facets hit_ratio=0.0" in msg for msg in messages)
    assert any(
        "redis_latency_ms operation=get cache_type=facets" in msg for msg in messages
    )


@pytest.mark.asyncio
async def test_catalog_cache_setex_logs_latency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    caplog.set_level(logging.INFO)

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        await catalog_cache_setex(
            "subcategories", "catalog:subcategories:abc", 60, "{}"
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "redis_latency_ms operation=setex cache_type=subcategories" in msg
        for msg in messages
    )


@pytest.mark.asyncio
async def test_cache_hit_ratio_tracks_per_cache_type() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=["1", None, "2"])

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        await catalog_cache_get("count", "k1")
        await catalog_cache_get("count", "k2")
        await catalog_cache_get("count", "k3")

    assert cache_hit_ratio("count") == pytest.approx(2 / 3, rel=1e-4)
    assert cache_hit_ratio("facets") == 0.0


@pytest.mark.asyncio
async def test_get_cached_count_uses_redis_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="15")
    caplog.set_level(logging.INFO)

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        result = await get_cached_count("catalog:count:test")

    assert result == 15
    messages = [record.getMessage() for record in caplog.records]
    assert any("redis_hit cache_type=count" in msg for msg in messages)


@pytest.mark.asyncio
async def test_set_cached_count_uses_redis_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    redis = AsyncMock()
    redis.setex = AsyncMock(return_value=True)
    caplog.set_level(logging.INFO)

    with patch("src.core.redis.async_.async_redis", return_value=redis):
        await set_cached_count("catalog:count:test", 9, 120)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "redis_latency_ms operation=setex cache_type=count" in msg for msg in messages
    )


def test_invalidate_count_cache_logs_sync_latency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.services.catalog.read.count_cache import invalidate_catalog_count_cache

    client = MagicMock()
    client.scan.return_value = (0, ["catalog:count:1"])
    client.delete.return_value = 1
    caplog.set_level(logging.INFO)

    with patch(
        "src.services.catalog.read.count_cache.sync_redis_text", return_value=client
    ):
        deleted = invalidate_catalog_count_cache()

    assert deleted == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "redis_latency_ms operation=invalidate_scan cache_type=count" in msg
        for msg in messages
    )
