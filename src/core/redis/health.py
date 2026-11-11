import asyncio
import logging
import time
from typing import Any

from src.core.config import settings
from src.core.redis.async_ import ping_async_redis
from src.core.redis.sync import ping_sync_redis

logger = logging.getLogger(__name__)

_last_ok_monotonic: float | None = None
_outage_alerted = False


# Пингует sync и async Redis; логирует alert при длительном outage.
def evaluate_redis_health() -> dict[str, Any]:
    global _last_ok_monotonic, _outage_alerted

    sync_ok = ping_sync_redis()
    async_ok = asyncio.run(ping_async_redis())
    ok = sync_ok and async_ok
    now = time.monotonic()
    threshold = settings.REDIS_HEALTH_ALERT_SECONDS

    if ok:
        if _outage_alerted:
            logger.warning("Redis восстановлен после недоступности")
        _last_ok_monotonic = now
        _outage_alerted = False
        return {
            "ok": True,
            "sync_ok": sync_ok,
            "async_ok": async_ok,
            "outage_seconds": 0,
            "alerted": False,
        }

    outage_seconds = 0
    if _last_ok_monotonic is not None:
        outage_seconds = int(now - _last_ok_monotonic)

    if (
        _last_ok_monotonic is not None
        and outage_seconds >= threshold
        and not _outage_alerted
    ):
        logger.error(
            "ALERT: Redis недоступен более %s сек (sync_ok=%s async_ok=%s)",
            outage_seconds,
            sync_ok,
            async_ok,
        )
        _outage_alerted = True

    return {
        "ok": False,
        "sync_ok": sync_ok,
        "async_ok": async_ok,
        "outage_seconds": outage_seconds,
        "alerted": _outage_alerted,
    }


# Сбрасывает in-process tracker (для тестов).
def reset_redis_health_tracker() -> None:
    global _last_ok_monotonic, _outage_alerted
    _last_ok_monotonic = None
    _outage_alerted = False
