import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings
from src.core.redis.metrics import (
    CatalogCacheType,
    elapsed_ms,
    record_redis_hit,
    record_redis_latency_ms,
    record_redis_miss,
)

_client: Redis | None = None


# Async Redis для API/кэшей (decode_responses=True).
def async_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


# Пингует async Redis; False при ошибке соединения.
async def ping_async_redis() -> bool:
    try:
        return bool(await async_redis().ping())
    except RedisError:
        return False


# GET catalog read cache с hit/miss и latency метриками.
async def catalog_cache_get(cache_type: CatalogCacheType, key: str) -> str | None:
    started_at = time.perf_counter()
    try:
        raw = await async_redis().get(key)
    except Exception:
        record_redis_latency_ms("get", cache_type, elapsed_ms(started_at))
        raise
    record_redis_latency_ms("get", cache_type, elapsed_ms(started_at))
    if raw is None:
        record_redis_miss(cache_type)
    else:
        record_redis_hit(cache_type)
    return raw


# SETEX catalog read cache с latency метриками.
async def catalog_cache_setex(
    cache_type: CatalogCacheType,
    key: str,
    ttl: int,
    value: str,
) -> None:
    started_at = time.perf_counter()
    try:
        await async_redis().setex(key, ttl, value)
    except Exception:
        record_redis_latency_ms("setex", cache_type, elapsed_ms(started_at))
        raise
    record_redis_latency_ms("setex", cache_type, elapsed_ms(started_at))
