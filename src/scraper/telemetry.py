import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CHALLENGE_ERROR_CLASSES = frozenset(
    {"cloudflare", "captcha", "challenge", "blocked", "rate_limit"}
)


# Маппит reject reason / classify_dom_error в dom_error_class для telemetry.
def map_dom_error_class(reason: str) -> str:
    low = reason.lower()
    if low.startswith("status=429") or "429" in low or "rate_limit" in low:
        return "rate_limit"
    if "captcha" in low or "turnstile" in low:
        return "captcha"
    if "challenge" in low or "cloudflare" in low:
        return "cloudflare"
    if "blocked" in low or "access denied" in low:
        return "blocked"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "no_member_price" in low:
        return "member_price_missing"
    if "no_final_price" in low or "no_product_data" in low:
        return "price_not_found"
    return "parse_error"


@dataclass(slots=True)
class DomFetchMeta:
    path: str
    latency_ms: int
    source: str
    http_reject_reason: str | None = None
    error_class: str | None = None
    success: bool = False


class PathTelemetry:
    # Скользящее окно fetch-метрик и pacing одного DOM-чанка.
    def __init__(self, window_size: int = 50) -> None:
        self.window_size = max(1, window_size)
        self._window: deque[dict[str, Any]] = deque(maxlen=self.window_size)
        self.chunk_started_at = time.monotonic()
        self.pacing_sleep_total_s = 0.0
        self._latencies_ms: list[int] = []
        self._recovery_latencies_ms: list[int] = []

    # Записывает один HTTP/browser fetch в окно telemetry.
    def record_fetch(self, meta: DomFetchMeta) -> None:
        is_challenge = bool(
            meta.error_class in CHALLENGE_ERROR_CLASSES
            or (
                meta.http_reject_reason
                and map_dom_error_class(meta.http_reject_reason)
                in CHALLENGE_ERROR_CLASSES
            )
        )
        self._window.append(
            {
                "source": meta.source,
                "path": meta.path,
                "success": meta.success,
                "challenge": is_challenge,
                "latency_ms": meta.latency_ms,
            }
        )
        self._latencies_ms.append(meta.latency_ms)
        if meta.source == "recovery_path":
            self._recovery_latencies_ms.append(meta.latency_ms)

    # Накапливает время sleep для pacing_overhead_pct.
    def record_pacing_sleep(self, seconds: float) -> None:
        self.pacing_sleep_total_s += max(0.0, seconds)

    # Доля challenge в последнем окне fetch.
    def challenge_ratio_last_window(self) -> float:
        if not self._window:
            return 0.0
        challenges = sum(1 for row in self._window if row["challenge"])
        return challenges / len(self._window)

    # blocked/success pct по source (http_path, browser_path, …).
    def _path_stats(self, source: str) -> dict[str, float]:
        rows = [row for row in self._window if row["source"] == source]
        if not rows:
            return {"attempts": 0, "blocked_pct": 0.0, "success_pct": 0.0}
        attempts = len(rows)
        blocked = sum(1 for row in rows if row["challenge"])
        success = sum(1 for row in rows if row["success"])
        return {
            "attempts": float(attempts),
            "blocked_pct": round(blocked / attempts, 4),
            "success_pct": round(success / attempts, 4),
        }

    # Агрегаты чанка для dom_chunk JSON в логах.
    def summary(self) -> dict[str, Any]:
        total = len(self._window)
        if total == 0:
            return {
                "http_success_ratio": 0.0,
                "recovery_ratio": 0.0,
                "challenge_ratio_last_window": 0.0,
                "http_first_blocked_pct": 0.0,
                "browser_blocked_pct": 0.0,
                "recovery_success_pct": 0.0,
                "avg_dom_latency_ms": 0,
                "dom_recovery_latency_ms_p50": 0,
                "pacing_overhead_pct": 0.0,
            }

        http_ok = sum(
            1 for row in self._window if row["source"] == "http_path" and row["success"]
        )
        recovery_attempts = sum(
            1 for row in self._window if row["source"] == "recovery_path"
        )
        chunk_elapsed = max(0.001, time.monotonic() - self.chunk_started_at)
        pacing_overhead_pct = min(
            100.0, round(self.pacing_sleep_total_s / chunk_elapsed * 100, 2)
        )

        http_stats = self._path_stats("http_path")
        browser_stats = self._path_stats("browser_path")
        recovery_stats = self._path_stats("recovery_path")

        recovery_latencies = sorted(self._recovery_latencies_ms)
        if recovery_latencies:
            p50_recovery = recovery_latencies[len(recovery_latencies) // 2]
        else:
            p50_recovery = 0
        latencies = sorted(self._latencies_ms)
        avg_latency = sum(latencies) // len(latencies) if latencies else 0

        return {
            "http_success_ratio": round(http_ok / total, 4),
            "recovery_ratio": round(recovery_attempts / total, 4),
            "challenge_ratio_last_window": round(self.challenge_ratio_last_window(), 4),
            "http_first_blocked_pct": http_stats["blocked_pct"],
            "browser_blocked_pct": browser_stats["blocked_pct"],
            "recovery_success_pct": recovery_stats["success_pct"],
            "avg_dom_latency_ms": avg_latency,
            "dom_recovery_latency_ms_p50": p50_recovery,
            "pacing_overhead_pct": pacing_overhead_pct,
        }

    # Пишет dom_chunk event в лог DOM-lane и Redis для админки.
    def log_dom_chunk(self, extra: dict[str, Any] | None = None) -> None:
        payload = {"event": "dom_chunk", **self.summary()}
        if extra:
            payload.update(extra)
        if payload.get("pacing_overhead_pct", 0) > 20:
            logger.warning(
                "dom_chunk pacing_overhead_pct=%s превышает 20%%",
                payload["pacing_overhead_pct"],
            )
        logger.info("dom_chunk %s", json.dumps(payload, ensure_ascii=False))
        try:
            from src.jobs.dom_telemetry_store import record_dom_chunk_event

            record_dom_chunk_event(payload)
        except Exception:
            logger.exception("dom_chunk telemetry: не удалось сохранить в Redis")
