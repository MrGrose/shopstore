import time
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis  # type: ignore[import-untyped]
from redis.exceptions import RedisError

from src.core.config import settings
from src.core.redis.metrics import CatalogCacheType, elapsed_ms, record_redis_latency_ms

_client: Redis | None = None
_text_client: Redis | None = None


# Синхронный Redis (RQ, locks, snapshots); без decode_responses.
def sync_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.REDIS_URL)
    return _client


# Синхронный Redis с decode_responses (SCAN/ключи как str).
def sync_redis_text() -> Redis:
    global _text_client
    if _text_client is None:
        _text_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _text_client


# Пингует sync Redis; False при ошибке соединения.
def ping_sync_redis() -> bool:
    try:
        return bool(sync_redis().ping())
    except RedisError:
        return False


# Замерить время выполнения синхронного Redis вызова.
@contextmanager
def timed_sync_redis_call(
    operation: str,
    cache_type: CatalogCacheType,
) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    finally:
        record_redis_latency_ms(operation, cache_type, elapsed_ms(started_at))
