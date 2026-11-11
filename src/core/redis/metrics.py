import logging
import time
from typing import Literal

logger = logging.getLogger(__name__)

CatalogCacheType = Literal["count", "facets", "subcategories"]

_hits: dict[CatalogCacheType, int] = {
    "count": 0,
    "facets": 0,
    "subcategories": 0,
}
_misses: dict[CatalogCacheType, int] = {
    "count": 0,
    "facets": 0,
    "subcategories": 0,
}


# Сбросить счётчики метрик кэша.
def reset_cache_metrics() -> None:
    for cache_type in _hits:
        _hits[cache_type] = 0
        _misses[cache_type] = 0


# Рассчитать hit ratio для конкретного типа кэша.
def cache_hit_ratio(cache_type: CatalogCacheType) -> float:
    hits = _hits[cache_type]
    misses = _misses[cache_type]
    total = hits + misses
    if total == 0:
        return 0.0
    return round(hits / total, 4)


# Записать метрику hit для конкретного типа кэша.
def record_redis_hit(cache_type: CatalogCacheType) -> None:
    _hits[cache_type] += 1
    logger.info(
        "redis_hit cache_type=%s hit_ratio=%s",
        cache_type,
        cache_hit_ratio(cache_type),
    )


# Записать метрику miss для конкретного типа кэша.
def record_redis_miss(cache_type: CatalogCacheType) -> None:
    _misses[cache_type] += 1
    logger.info(
        "redis_miss cache_type=%s hit_ratio=%s",
        cache_type,
        cache_hit_ratio(cache_type),
    )


# Записать метрику latency для конкретного типа кэша.
def record_redis_latency_ms(
    operation: str,
    cache_type: CatalogCacheType,
    duration_ms: float,
) -> None:
    logger.info(
        "redis_latency_ms operation=%s cache_type=%s duration_ms=%s",
        operation,
        cache_type,
        round(duration_ms, 2),
    )


# Рассчитать время выполнения в миллисекундах.
def elapsed_ms(started_at: float) -> float:
    return (time.perf_counter() - started_at) * 1000
