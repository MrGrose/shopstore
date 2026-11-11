import hashlib
import json
import logging
from typing import Any

from src.core.cache import build_versioned_key, get_catalog_version
from src.core.redis import catalog_cache_get, catalog_cache_setex, sync_redis_text
from src.core.redis.sync import timed_sync_redis_call
from src.schemas.catalog import CatalogFacetsSchema
from src.services.catalog.read.scope import (
    encode_placement_chip_ids_for_cache,
    normalize_facet_list_for_cache,
)

logger = logging.getLogger(__name__)

FACETS_KEY_PREFIX = "catalog:facets:"


# Собирает ключ Redis для среза фасетов каталога.
async def build_facets_cache_key(
    top_category: str | None,
    category: str | None,
    categories: list[str] | None,
    category_l3: str | None,
    brands: list[str] | None,
    genders: list[str] | None,
    colors: list[str] | None,
    sizes: list[str] | None,
    include_out_of_stock: bool,
    zero_stock_only: bool,
    inactive_only: bool,
    include: str = "all",
    exclude_hidden_brands: bool = False,
    max_goods_eur: str = "",
    require_complete: bool = False,
    mapping_release_id: int | None = None,
    chip_node_ids: tuple[int, ...] | None = None,
    price_min: str | None = None,
    price_max: str | None = None,
    q: str | None = None,
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
        "include": (include or "all").strip().lower() or "all",
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
    return build_versioned_key(FACETS_KEY_PREFIX, version, digest)


# Читает фасеты из Redis; при ошибке или промахе возвращает None.
async def get_cached_facets(key: str) -> CatalogFacetsSchema | None:
    try:
        raw = await catalog_cache_get("facets", key)
    except Exception as exc:
        logger.warning("Кэш фасетов: ошибка чтения из Redis: %s", exc)
        return None
    if not raw:
        logger.debug("Кэш фасетов: промах key=%s", key)
        return None
    try:
        result = CatalogFacetsSchema.model_validate_json(raw)
    except Exception as exc:
        logger.warning("Кэш фасетов: ошибка разбора JSON key=%s: %s", key, exc)
        return None
    logger.debug("Кэш фасетов: попадание key=%s", key)
    return result


# Записывает фасеты в Redis с TTL.
async def set_cached_facets(key: str, schema: CatalogFacetsSchema, ttl: int) -> None:
    if ttl <= 0:
        return
    try:
        await catalog_cache_setex("facets", key, ttl, schema.model_dump_json())
    except Exception as exc:
        logger.warning("Кэш фасетов: ошибка записи key=%s: %s", key, exc)


# Сбрасывает все ключи catalog:facets:* (после finalize каталога).
def invalidate_catalog_facets_cache() -> int:
    try:
        client = sync_redis_text()
        deleted = 0
        cursor = 0
        with timed_sync_redis_call("invalidate_scan", "facets"):
            while True:
                cursor, keys = client.scan(
                    cursor, match=f"{FACETS_KEY_PREFIX}*", count=100
                )
                if keys:
                    deleted += int(client.delete(*keys))
                if cursor == 0:
                    break
        logger.info("Кэш фасетов: сброшено ключей: %s", deleted)
        return deleted
    except Exception as exc:
        logger.warning("Кэш фасетов: ошибка сброса: %s", exc)
        return 0
