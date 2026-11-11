import json
import time
from datetime import datetime
from typing import Any

from src.jobs.admin_job_snapshots import DOM_WATCHDOG_SNAPSHOT, load_admin_job_snapshot
from src.scraper.infrastructure.session_paths import build_dashboard_sessions
from src.utils.datetime_fmt import format_datetime_msk, utc_now_naive
from src.web.parsing_health import format_relative_age

_SESSION_HEALTH_KEYS = (
    "exists",
    "status",
    "status_label",
    "age_hours",
    "updated_at",
    "updated_at_msk",
    "refresh_hint",
    "session_dir",
    "filename",
    "size_bytes",
    "warn_after_days",
)


# File-age health only: existence + mtime thresholds. Not login/auth proof.
def session_health_from_row(row: dict[str, Any]) -> dict[str, Any]:
    health = {key: row.get(key) for key in _SESSION_HEALTH_KEYS}
    if not health.get("session_dir") and row.get("kind") == "availability":
        health["session_dir"] = "session/"
    return health


# Собирает lane rows: DOM session file age + Redis throttle (не login proof).
def build_parsing_lanes_overview(now: datetime | None = None) -> dict[str, Any]:
    if now is None:
        now = utc_now_naive()
    sessions = build_dashboard_sessions()
    availability_row = sessions["availability"]
    if availability_row.get("updated_at"):
        availability_row["updated_at_msk"] = (
            format_datetime_msk(availability_row["updated_at"], with_tz_label=False)
            or None
        )
    else:
        availability_row["updated_at_msk"] = None
    availability = session_health_from_row(availability_row)
    availability["kind"] = availability_row.get("kind")
    availability["label"] = availability_row.get("label")

    lanes: list[dict[str, Any]] = []
    for row in sessions["lanes"]:
        throttle = read_lane_throttle_dashboard(str(row["lane_id"]))
        session_row = dict(row)
        session_row["updated_at_msk"] = (
            format_datetime_msk(row["updated_at"], with_tz_label=False)
            if row.get("updated_at")
            else None
        )
        session = session_health_from_row(session_row)
        lane_row = {
            "lane_id": row["lane_id"],
            "worker": row["worker"],
            "label": row.get("label"),
            "kind": row.get("kind"),
            "session": session,
            "throttle": throttle,
        }
        lanes.append(lane_row)

    watchdog = load_admin_job_snapshot(DOM_WATCHDOG_SNAPSHOT) or {}
    watchdog_finished = watchdog.get("finished_at")
    watchdog_age = None
    if watchdog_finished and now is not None:
        try:
            finished_at = datetime.fromisoformat(str(watchdog_finished))
            watchdog_age = format_relative_age(finished_at, now)
        except ValueError:
            watchdog_age = None

    return {
        "availability": availability,
        "lanes": lanes,
        "watchdog": {
            "snapshot": watchdog,
            "last_run_age": watchdog_age,
            "last_run_msk": (
                format_datetime_msk(
                    datetime.fromisoformat(str(watchdog_finished)),
                    with_tz_label=False,
                )
                if watchdog_finished
                else None
            ),
        },
    }


# Читает lane throttle state из Redis для админки.
def read_lane_throttle_dashboard(lane_id: str) -> dict[str, Any]:
    from src.core.redis import sync_redis

    key = f"shopstore:dom:lane:{lane_id}:throttle"
    raw = sync_redis().get(key)
    if not raw:
        return _empty_lane_throttle(lane_id)
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    now = time.time()
    cooldown_until = max(
        float(state.get("cooldown_until") or 0.0),
        float(state.get("unhealthy_until") or 0.0),
    )
    remaining = max(0, int(cooldown_until - now))
    consecutive = int(state.get("consecutive_429") or 0)
    if remaining > 0:
        status, status_label = "cooldown", "Пауза"
    elif consecutive > 0:
        status, status_label = "throttled", "Торможение"
    else:
        status, status_label = "healthy", "Здоров"
    return {
        "lane_id": lane_id,
        "healthy": status == "healthy",
        "cooldown_seconds": remaining,
        "consecutive_429": consecutive,
        "status": status,
        "status_label": status_label,
    }


def _empty_lane_throttle(lane_id: str) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "healthy": True,
        "cooldown_seconds": 0,
        "consecutive_429": 0,
        "status": "healthy",
        "status_label": "Здоров",
    }
