import json
from datetime import UTC, datetime
from typing import Any

from src.core.redis import sync_redis

_SNAPSHOT_TTL_SECONDS = 60 * 60 * 24 * 90
_KEY_PREFIX = "shopstore:admin:snapshot:"

ROLLING_REFRESH_SNAPSHOT = "rolling_refresh"
DOM_WATCHDOG_SNAPSHOT = "dom_watchdog"
DOM_DOCTOR_SNAPSHOT = "dom_doctor"
PARSER_NIGHTLY_SNAPSHOT = "parser_nightly"
REDIS_HEALTH_SNAPSHOT = "redis_health"


# Redis-ключ snapshot по имени cron/job.
def _snapshot_key(name: str) -> str:
    return f"{_KEY_PREFIX}{name}"


# Сохраняет результат cron/job для админки парсинга.
def save_admin_job_snapshot(name: str, payload: dict[str, Any]) -> None:
    body = {
        **payload,
        "finished_at": datetime.now(UTC)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds"),
    }
    sync_redis().set(
        _snapshot_key(name),
        json.dumps(body, ensure_ascii=False, default=str),
        ex=_SNAPSHOT_TTL_SECONDS,
    )


# Читает последний snapshot cron/job.
def load_admin_job_snapshot(name: str) -> dict[str, Any] | None:
    raw = sync_redis().get(_snapshot_key(name))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
