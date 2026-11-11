import hashlib
import json
import logging
from typing import Any

from src.core.cache import build_versioned_key, get_catalog_version
from src.core.redis import catalog_cache_get, catalog_cache_setex, sync_redis_text
from src.core.redis.sync import timed_sync_redis_call
from src.schemas.catalog_labels import CatalogSubCategorySchema

logger = logging.getLogger(__name__)

SUBCATEGORIES_KEY_PREFIX = "catalog:subcategories:"


# Собирает ключ Redis для подкатегорий каталога.
async def build_subcategories_cache_key(
    top_category: str,
    sub_slug: str,
    include_out_of_stock: bool,
    zero_stock_only: bool,
    inactive_only: bool,
    locale: str = "ru",
    exclude_hidden_brands: bool = False,
    max_goods_eur: str = "",
    require_complete: bool = False,
    mapping_release_id: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "top_category": (top_category or "").strip(),
        "sub": (sub_slug or "").strip(),
        "include_out_of_stock": include_out_of_stock,
        "zero_stock_only": zero_stock_only,
        "inactive_only": inactive_only,
        "exclude_hidden_brands": exclude_hidden_brands,
        "max_goods_eur": (max_goods_eur or "").strip(),
        "require_complete": bool(require_complete),
        "locale": (locale or "ru").strip().lower() or "ru",
        "mapping_release_id": mapping_release_id,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    version = await get_catalog_version()
    return build_versioned_key(SUBCATEGORIES_KEY_PREFIX, version, digest)


# Читает подкатегории из Redis.
async def get_cached_subcategories(key: str) -> CatalogSubCategorySchema | None:
    try:
        raw = await catalog_cache_get("subcategories", key)
    except Exception as exc:
        logger.warning("Кэш подкатегорий: ошибка чтения: %s", exc)
        return None
    if not raw:
        return None
    try:
        return CatalogSubCategorySchema.model_validate_json(raw)
    except Exception as exc:
        logger.warning("Кэш подкатегорий: ошибка разбора JSON: %s", exc)
        return None


# Записывает подкатегорию в Redis с TTL.
async def set_cached_subcategories(
    key: str, schema: CatalogSubCategorySchema, ttl: int
) -> None:
    if ttl <= 0:
        return
    try:
        await catalog_cache_setex("subcategories", key, ttl, schema.model_dump_json())
    except Exception as exc:
        logger.warning("Кэш подкатегорий: ошибка записи: %s", exc)


# Сбрасывает все ключи catalog:subcategories:*.
def invalidate_catalog_subcategories_cache() -> int:
    try:
        client = sync_redis_text()
        deleted = 0
        cursor = 0
        with timed_sync_redis_call("invalidate_scan", "subcategories"):
            while True:
                cursor, keys = client.scan(
                    cursor, match=f"{SUBCATEGORIES_KEY_PREFIX}*", count=100
                )
                if keys:
                    deleted += int(client.delete(*keys))
                if cursor == 0:
                    break
        logger.info("Кэш подкатегорий: сброшено ключей: %s", deleted)
        return deleted
    except Exception as exc:
        logger.warning("Кэш подкатегорий: ошибка сброса: %s", exc)
        return 0
