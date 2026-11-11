import logging

from redis.exceptions import RedisError

from src.core.redis import sync_redis

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "scraper:dom:enqueued:"
_COMPARE_AND_DEL_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""
_compare_and_del_script = None


# Регистрирует Lua compare-and-del для token-aware release.
def _token_release_script(redis):
    global _compare_and_del_script
    if _compare_and_del_script is None:
        _compare_and_del_script = redis.register_script(_COMPARE_AND_DEL_LUA)
    return _compare_and_del_script


# Ключ Redis для dedup: external_id или canonical product_url.
def product_enqueue_lock_key(product: dict) -> str | None:
    gtm = product.get("gtm") or {}
    external_id = product.get("item_id") or gtm.get("item_id")
    if external_id:
        return f"{_LOCK_PREFIX}{external_id}"
    product_url = str(product.get("product_url") or "").strip()
    if product_url:
        return f"{_LOCK_PREFIX}url:{product_url}"
    return None


# Захватывает lock перед enqueue; False если товар уже в очереди/обработке.
def try_acquire_dom_enqueue_lock(
    product: dict,
    ttl_seconds: int,
    owner_token: str | None = None,
) -> bool:
    key = product_enqueue_lock_key(product)
    if key is None:
        return True
    ttl = max(60, int(ttl_seconds))
    lock_value = owner_token if owner_token is not None else "1"
    try:
        acquired = bool(sync_redis().set(key, lock_value, nx=True, ex=ttl))
    except RedisError as exc:
        logger.warning(
            "DOM dedup lock недоступен, enqueue без lock: %s (%s)",
            key,
            exc,
        )
        return True
    if not acquired:
        logger.debug("DOM dedup: lock занят %s", key)
    return acquired


# Снимает lock после завершения DOM chunk; при token — только совпадающий владелец.
def release_dom_enqueue_lock(
    product: dict,
    owner_token: str | None = None,
) -> None:
    key = product_enqueue_lock_key(product)
    if key is None:
        return
    try:
        redis = sync_redis()
        if owner_token is None:
            redis.delete(key)
            return
        _token_release_script(redis)(keys=[key], args=[owner_token])
    except RedisError as exc:
        logger.warning(
            "DOM dedup release пропущен (Redis недоступен): %s (%s)",
            key,
            exc,
        )


# Снимает locks для всех товаров чанка.
def release_dom_enqueue_locks(
    products: list[dict],
    owner_token: str | None = None,
) -> None:
    if not products:
        return
    for product in products:
        release_dom_enqueue_lock(product, owner_token)


# D3: продлевает TTL Redis lock при совпадении owner_token.
def renew_dom_enqueue_locks(
    _products: list[dict],
    _owner_token: str,
    _ttl_seconds: int,
) -> None:
    return
