import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.core.redis import catalog_cache_get, catalog_cache_setex
from src.core.redis.async_ import async_redis
from src.core.redis.metrics import CatalogCacheType
from src.core.redis.sync import sync_redis_text

logger = logging.getLogger(__name__)

CATALOG_VERSION_KEY = "catalog:version"
REFERENCE_CACHE_TTL_SECONDS = 300

T = TypeVar("T")

_locks: dict[str, asyncio.Lock] = {}
_inflight: dict[str, asyncio.Task[Any]] = {}
_reference_cache: dict[str, tuple[float, Any]] = {}


# Собирает Redis-ключ catalog read cache с версией каталога.
def build_versioned_key(prefix: str, version: int, digest: str) -> str:
    return f"{prefix}v{version}:{digest}"


# Читает текущую версию catalog read cache из Redis.
async def get_catalog_version() -> int:
    try:
        raw = await async_redis().get(CATALOG_VERSION_KEY)
        if raw is None:
            return 0
        return int(raw)
    except Exception as exc:
        logger.warning("Чтение catalog:version: ошибка: %s", exc)
        return 0


# Читает значение из Redis или вызывает fetch_fn при промахе.
async def cached_get(
    cache_type: CatalogCacheType,
    key: str,
    ttl: int,
    fetch_fn: Callable[[], Awaitable[T]],
    encode: Callable[[T], str],
    decode: Callable[[str], T],
) -> T:
    try:
        raw = await catalog_cache_get(cache_type, key)
    except Exception as exc:
        logger.warning("Кэш %s: ошибка чтения key=%s: %s", cache_type, key, exc)
        raw = None
    if raw is not None:
        try:
            return decode(raw)
        except Exception as exc:
            logger.warning("Кэш %s: ошибка разбора key=%s: %s", cache_type, key, exc)
    value = await fetch_fn()
    if ttl > 0:
        try:
            await catalog_cache_setex(cache_type, key, ttl, encode(value))
        except Exception as exc:
            logger.warning("Кэш %s: ошибка записи key=%s: %s", cache_type, key, exc)
    return value


# Схлопывает параллельные запросы с одним ключом в один fetch_fn.
async def single_flight(
    key: str,
    fetch_fn: Callable[[], Awaitable[T]],
) -> T:
    async def _run() -> T:
        return await fetch_fn()

    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = _inflight.get(key)
        if existing is not None and not existing.done():
            task: asyncio.Task[T] = existing
        else:
            task = asyncio.create_task(_run())
            _inflight[key] = task
    try:
        return await task
    finally:
        async with lock:
            current = _inflight.get(key)
            if current is task:
                _inflight.pop(key, None)
                if not _inflight:
                    _locks.pop(key, None)


# Инкрементирует catalog:version для O(1) инвалидации read-кэшей.
def invalidate_catalog_version() -> int:
    try:
        client = sync_redis_text()
        return int(client.incr(CATALOG_VERSION_KEY))
    except Exception as exc:
        logger.warning("Инкремент catalog:version: ошибка: %s", exc)
        raise


# Читает значение из in-memory TTL cache для справочников каталога.
def get_reference_ttl_cache(key: str) -> Any | None:
    entry = _reference_cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _reference_cache.pop(key, None)
        return None
    return value


# Записывает значение в in-memory TTL cache для справочников каталога.
def set_reference_ttl_cache(
    key: str,
    value: Any,
    ttl: int = REFERENCE_CACHE_TTL_SECONDS,
) -> None:
    if ttl <= 0:
        return
    _reference_cache[key] = (time.monotonic() + ttl, value)


# Сбрасывает одну запись reference TTL cache (после мутаций справочника).
def invalidate_reference_ttl_cache(key: str) -> None:
    _reference_cache.pop(key, None)
