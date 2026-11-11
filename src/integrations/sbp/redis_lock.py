import logging
import uuid

from redis.exceptions import RedisError

from src.core.redis.async_ import async_redis

logger = logging.getLogger(__name__)

REDIS_LOCK_BYPASS = "__redis_unavailable__"

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


# Захватывает async Redis-lock с owner token; None если уже занят.
async def try_acquire_redis_lock(
    key: str, ttl_seconds: int, owner_token: str | None = None
) -> str | None:
    token = owner_token or uuid.uuid4().hex
    ttl = max(1, int(ttl_seconds))
    try:
        redis = async_redis()
        acquired = bool(await redis.set(key, token, nx=True, ex=ttl))
    except RedisError as exc:
        logger.warning(
            "Redis lock недоступен, продолжаем без распределённого lock: %s (%s)",
            key,
            exc,
        )
        return REDIS_LOCK_BYPASS
    if not acquired:
        logger.debug("Redis lock занят: %s", key)
        return None
    return token


# Снимает lock только если owner token совпадает.
async def release_redis_lock(key: str, owner_token: str) -> None:
    if owner_token == REDIS_LOCK_BYPASS:
        return
    try:
        redis = async_redis()
        script = _token_release_script(redis)
        await script(keys=[key], args=[owner_token])
    except RedisError as exc:
        logger.warning("Не удалось снять Redis lock %s: %s", key, exc)
