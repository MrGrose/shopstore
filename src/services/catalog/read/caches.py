import inspect
import logging
import time

from src.core.cache import invalidate_catalog_version
from src.services.catalog.read.count_cache import (
    build_count_cache_key,
    get_cached_count,
    invalidate_catalog_count_cache,
    set_cached_count,
)
from src.services.catalog.read.facets_cache import (
    build_facets_cache_key,
    get_cached_facets,
    invalidate_catalog_facets_cache,
    set_cached_facets,
)
from src.services.catalog.read.subcategories_cache import (
    build_subcategories_cache_key,
    get_cached_subcategories,
    invalidate_catalog_subcategories_cache,
    set_cached_subcategories,
)

logger = logging.getLogger(__name__)

__all__ = [
    "build_count_cache_key",
    "get_cached_count",
    "set_cached_count",
    "invalidate_catalog_count_cache",
    "build_facets_cache_key",
    "get_cached_facets",
    "set_cached_facets",
    "invalidate_catalog_facets_cache",
    "build_subcategories_cache_key",
    "get_cached_subcategories",
    "set_cached_subcategories",
    "invalidate_catalog_subcategories_cache",
    "invalidate_catalog_read_caches",
    "invalidate_if_catalog_boundary_changed",
]


# Получить имя вызывающего модуля и функции.
def _invalidation_caller() -> str:
    frame = inspect.stack()[1]
    module = frame.frame.f_globals.get("__name__", "unknown")
    return f"{module}.{frame.function}"


# Сбрасывает Redis-кэши count/facets/subcategories каталога (после успешного commit).
def invalidate_catalog_read_caches(
    facets: bool = True,
    count: bool = True,
    subcategories: bool = True,
    reason: str | None = None,
) -> dict[str, int]:
    started_at = time.perf_counter()
    caller = _invalidation_caller()
    result = {
        "catalog_version": 0,
        "facets": 0,
        "count": 0,
        "subcategories": 0,
    }
    if not facets and not count and not subcategories:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            (
                "catalog_cache_invalidate caller=%s catalog_version=0 duration_ms=%s "
                "reason=%s skipped=all"
            ),
            caller,
            duration_ms,
            reason or "unspecified",
        )
        return result
    new_version = invalidate_catalog_version()
    result["catalog_version"] = new_version
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        (
            "catalog_cache_invalidate caller=%s catalog_version=%s duration_ms=%s "
            "reason=%s facets=0 count=0 subcategories=0"
        ),
        caller,
        new_version,
        duration_ms,
        reason or "unspecified",
    )
    return result


# Сбрасывает read-кэши при смене storefront visibility (stock boundary).
def invalidate_if_catalog_boundary_changed(
    boundary_flipped_ids: list[int] | set[int],
    reason: str,
) -> bool:
    if not boundary_flipped_ids:
        return False
    invalidate_catalog_read_caches(reason=reason)
    return True
