import hashlib
import json
import logging
from typing import Any

from src.core.cache import build_versioned_key, get_catalog_version
from src.core.redis import catalog_cache_get, catalog_cache_setex, sync_redis_text
from src.core.redis.sync import timed_sync_redis_call
from src.services.catalog.read.scope import (
    encode_placement_chip_ids_for_cache,
    normalize_facet_list_for_cache,
)

logger = logging.getLogger(__name__)

COUNT_KEY_PREFIX = "catalog:count:"


# Собирает ключ Redis для count среза каталога.
async def build_count_cache_key(
    top_category: str | None,
    category: str | None,
    categories: list[str] | None,
    category_l3: str | None,
    brands: list[str] | None,
    genders: list[str] | None,
    colors: list[str] | None,
    sizes: list[str] | None,
    price_min: str | None,
    price_max: str | None,
    q: str | None,
    include_out_of_stock: bool,
    zero_stock_only: bool,
    inactive_only: bool,
    exclude_hidden_brands: bool = False,
    max_goods_eur: str = "",
    require_complete: bool = False,
    mapping_release_id: int | None = None,
    chip_node_ids: tuple[int, ...] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "top_category": (top_category or "").strip(),
        "category": (category or "").strip(),
        "categories": sorted(c.strip() for c in (categories or []) if c and c.strip()),
        "category_l3": (category_l3 or "").strip(),
        "brands": normalize_facet_list_for_cache(brands),
        "genders": normalize_facet_list_for_cache(genders),
        "colors": normalize_facet_list_for_cache(colors),
        "sizes": normalize_facet_list_for_cache(sizes),
        "price_min": (price_min or "").strip(),
        "price_max": (price_max or "").strip(),
        "q": (q or "").strip(),
        "include_out_of_stock": include_out_of_stock,
        "zero_stock_only": zero_stock_only,
        "inactive_only": inactive_only,
        "exclude_hidden_brands": exclude_hidden_brands,
        "max_goods_eur": (max_goods_eur or "").strip(),
        "require_complete": bool(require_complete),
        "mapping_release_id": mapping_release_id,
        "chip_node_ids": encode_placement_chip_ids_for_cache(chip_node_ids),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    version = await get_catalog_version()
    return build_versioned_key(COUNT_KEY_PREFIX, version, digest)


# Читает count из Redis.
async def get_cached_count(key: str) -> int | None:
    try:
        raw = await catalog_cache_get("count", key)
    except Exception as exc:
        logger.warning("Кэш count: ошибка чтения: %s", exc)
        return None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Кэш count: ошибка разбора key=%s: %s", key, exc)
        return None


# Записывает count в Redis с TTL.
async def set_cached_count(key: str, total: int, ttl: int) -> None:
    if ttl <= 0:
        return
    try:
        await catalog_cache_setex("count", key, ttl, str(int(total)))
    except Exception as exc:
        logger.warning("Кэш count: ошибка записи: %s", exc)


# Сбрасывает все ключи catalog:count:*.
def invalidate_catalog_count_cache() -> int:
    try:
        client = sync_redis_text()
        deleted = 0
        cursor = 0
        with timed_sync_redis_call("invalidate_scan", "count"):
            while True:
                cursor, keys = client.scan(
                    cursor, match=f"{COUNT_KEY_PREFIX}*", count=100
                )
                if keys:
                    deleted += int(client.delete(*keys))
                if cursor == 0:
                    break
        logger.info("Кэш count: сброшено ключей: %s", deleted)
        return deleted
    except Exception as exc:
        logger.warning("Кэш count: ошибка сброса: %s", exc)
        return 0
