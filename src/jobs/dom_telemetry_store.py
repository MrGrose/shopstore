import json
import time
from typing import Any

from src.core.redis import sync_redis

_EVENTS_KEY = "shopstore:admin:dom_telemetry:events"
_RETENTION_SECONDS = 60 * 60 * 24  # 24 часа


# Сохраняет dom_chunk telemetry из DOM-lane для админки.
def record_dom_chunk_event(payload: dict[str, Any]) -> None:
    redis = sync_redis()
    now = time.time()
    body = {**payload, "ts": now}
    redis.zadd(_EVENTS_KEY, {json.dumps(body, ensure_ascii=False, default=str): now})
    redis.zremrangebyscore(_EVENTS_KEY, 0, now - _RETENTION_SECONDS)


# Пустые агрегаты telemetry для окна без событий.
def _empty_window() -> dict[str, Any]:
    return {
        "chunks": 0,
        "challenge_ratio_pct": 0,
        "avg_latency_ms": 0,
        "throttle_cooldowns": 0,
        "pacing_overhead_pct": 0,
        "http_blocked_pct": 0,
        "recovery_ratio_pct": 0,
    }


# Агрегирует telemetry events за окно (секунды).
def _aggregate_window(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return _empty_window()
    chunks = len(events)
    challenge_avg = (
        sum(float(event.get("challenge_ratio_last_window") or 0) for event in events)
        / chunks
    )
    latency_avg = round(
        sum(int(event.get("avg_dom_latency_ms") or 0) for event in events) / chunks
    )
    pacing_avg = round(
        sum(float(event.get("pacing_overhead_pct") or 0) for event in events) / chunks,
        1,
    )
    http_blocked_avg = round(
        sum(float(event.get("http_first_blocked_pct") or 0) for event in events)
        / chunks
        * 100,
        1,
    )
    recovery_avg = round(
        sum(float(event.get("recovery_ratio") or 0) for event in events) / chunks * 100,
        1,
    )
    throttle_total = sum(int(event.get("throttle_cooldowns") or 0) for event in events)
    return {
        "chunks": chunks,
        "challenge_ratio_pct": round(challenge_avg * 100, 1),
        "avg_latency_ms": latency_avg,
        "throttle_cooldowns": throttle_total,
        "pacing_overhead_pct": pacing_avg,
        "http_blocked_pct": http_blocked_avg,
        "recovery_ratio_pct": recovery_avg,
    }


# Агрегирует telemetry по lane_id за окно.
def _aggregate_by_lane(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        lane_id = str(event.get("lane_id") or "").strip() or "unknown"
        buckets.setdefault(lane_id, []).append(event)
    return {lane_id: _aggregate_window(rows) for lane_id, rows in buckets.items()}


# Пустой dashboard telemetry для шаблона и fallback.
def empty_telemetry_dashboard() -> dict[str, Any]:
    return {
        "window_1h": _empty_window(),
        "window_24h": _empty_window(),
        "lanes_1h": {},
        "last": None,
        "last_at_msk": None,
        "has_data": False,
    }


# Читает агрегаты telemetry за 1ч/24ч и последний chunk.
def load_dom_telemetry_dashboard() -> dict[str, Any]:
    redis = sync_redis()
    now = time.time()
    raw_rows = redis.zrangebyscore(_EVENTS_KEY, now - _RETENTION_SECONDS, now)
    events: list[dict[str, Any]] = []
    for raw in raw_rows:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            events.append(row)
    events.sort(key=lambda row: float(row.get("ts") or 0))

    events_1h = [row for row in events if float(row.get("ts") or 0) >= now - 3600]
    last_event = events[-1] if events else None
    last_msk = None
    if last_event and last_event.get("ts"):
        from datetime import datetime

        from src.utils.datetime_fmt import format_datetime_msk

        last_msk = (
            format_datetime_msk(
                datetime.fromtimestamp(float(last_event["ts"])),
                with_tz_label=False,
            )
            or None
        )

    return {
        "window_1h": _aggregate_window(events_1h),
        "window_24h": _aggregate_window(events),
        "lanes_1h": _aggregate_by_lane(events_1h),
        "last": last_event,
        "last_at_msk": last_msk,
        "has_data": bool(events),
    }
