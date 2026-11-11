import asyncio
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.scraper.config.settings import Settings
    from src.scraper.infrastructure.http_client import ScraperHttpClient
    from src.scraper.telemetry import PathTelemetry

logger = logging.getLogger(__name__)

PAUSE_HARD_CAP_SECONDS = 90.0
COOLDOWN_HARD_CAP_SECONDS = 300.0
MAX_COOLDOWNS_PER_CHUNK = 3
MEDIUM_SLEEP_MULTIPLIER = 1.5
DEFAULT_LANE_429_COOLDOWNS = (15.0, 30.0, 45.0, 60.0)
LANE_THROTTLE_REDIS_TTL_SECONDS = 3600
LANE_EVENT_SUCCESS = "http_success"
LANE_EVENT_HTTP_429 = "http_429"
LANE_EVENT_CF_CHALLENGE = "cf_challenge"
LANE_EVENT_CAPTCHA = "captcha"
LANE_EVENT_SUPPLIER_500 = "supplier_500"
LANE_EVENT_TIMEOUT = "timeout"
LANE_EVENT_NETWORK = "network"


# Парсит CSV cooldowns из settings и режет по throttle_cooldown_max.
def lane_429_schedule(env: "Settings") -> list[float]:
    raw = getattr(env, "lane_429_cooldowns", None)
    cap = float(getattr(env, "throttle_cooldown_max", COOLDOWN_HARD_CAP_SECONDS))
    cap = min(COOLDOWN_HARD_CAP_SECONDS, max(1.0, cap))
    values: list[float] = []
    if isinstance(raw, (list, tuple)):
        values = [float(item) for item in raw]
    else:
        text = str(raw or "15,30,45,60")
        for part in text.split(","):
            piece = part.strip()
            if piece:
                values.append(float(piece))
    schedule = [min(cap, max(0.0, item)) for item in values]
    return schedule or [min(cap, DEFAULT_LANE_429_COOLDOWNS[0])]


# Cooldown в секундах для N-го подряд HTTP 429 (1-based).
def cooldown_for_consecutive_429(schedule: list[float], consecutive: int) -> float:
    if consecutive <= 0 or not schedule:
        return 0.0
    index = min(consecutive, len(schedule)) - 1
    return schedule[index]


# In-memory lane throttle: общий store на несколько ChallengeThrottle в процессе.
class MemoryLaneThrottleStore:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}

    # Читает JSON-совместимое состояние lane.
    def load(self, lane_id: str) -> dict[str, Any]:
        return dict(self._states.get(lane_id) or {})

    # Пишет состояние lane (workers одной identity делят этот store).
    def save(self, lane_id: str, state: dict[str, Any]) -> None:
        self._states[lane_id] = dict(state)


# Redis lane throttle: общий state workers одной lane.
class RedisLaneThrottleStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    # Подключает sync Redis; None если ping не прошёл.
    @classmethod
    def try_create(cls) -> "RedisLaneThrottleStore | None":
        try:
            from src.core.redis import sync_redis

            client = sync_redis()
            if not client.ping():
                return None
            return cls(client)
        except Exception:
            logger.warning(
                "lane_throttle: Redis недоступен, fallback на process memory",
            )
            return None

    # Ключ Redis для identity lane, не для worker replica.
    def _key(self, lane_id: str) -> str:
        return f"shopstore:dom:lane:{lane_id}:throttle"

    # Читает JSON state lane из Redis.
    def load(self, lane_id: str) -> dict[str, Any]:
        raw = self._redis.get(self._key(lane_id))
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # Пишет JSON state lane с TTL, чтобы stale cooldown не жил вечно.
    def save(self, lane_id: str, state: dict[str, Any]) -> None:
        self._redis.set(
            self._key(lane_id),
            json.dumps(state, ensure_ascii=False),
            ex=LANE_THROTTLE_REDIS_TTL_SECONDS,
        )


# Redis если жив, иначе новый memory store (один процесс / несколько tasks).
def resolve_lane_throttle_store(
    store: MemoryLaneThrottleStore | RedisLaneThrottleStore | None = None,
) -> MemoryLaneThrottleStore | RedisLaneThrottleStore:
    if store is not None:
        return store
    redis_store = RedisLaneThrottleStore.try_create()
    if redis_store is not None:
        return redis_store
    return MemoryLaneThrottleStore()


class BurstPacer:
    # Паузы пачками: N товаров быстро, потом отдых anti-429.
    def __init__(
        self,
        env: "Settings",
        telemetry: "PathTelemetry",
        throttle: "ChallengeThrottle | None" = None,
    ) -> None:
        self.env = env
        self.telemetry = telemetry
        self.throttle = throttle
        self._burst_count = 0
        self._burst_limit = random.randint(env.burst_min, env.burst_max)

    # Лимит burst при ramp-режиме challenge throttle.
    def _ramp_burst_cap(self) -> int:
        if self.throttle is None or self.throttle.mode != "ramp":
            return self._effective_burst_max()
        caps = [10, 18, 28, self.env.burst_max]
        idx = min(max(self.throttle.ramp_step, 1), len(caps)) - 1
        return min(self._effective_burst_max(), caps[idx])

    # Уменьшает burst при росте challenge ratio в окне telemetry.
    def _effective_burst_max(self) -> int:
        ratio = self.telemetry.challenge_ratio_last_window()
        burst_max = self.env.burst_max
        if ratio >= self.env.challenge_high_threshold:
            burst_max = min(burst_max, 18)
        elif ratio >= self.env.challenge_medium_threshold:
            burst_max = min(burst_max, 25)
        return max(self.env.burst_min, burst_max)

    # Удлиняет паузу между burst при elevated challenge ratio.
    def _effective_pause_bounds(self) -> tuple[float, float]:
        ratio = self.telemetry.challenge_ratio_last_window()
        pause_min = float(self.env.burst_pause_min)
        pause_max = min(float(self.env.burst_pause_max), PAUSE_HARD_CAP_SECONDS)
        if ratio >= self.env.challenge_medium_threshold:
            pause_min = min(PAUSE_HARD_CAP_SECONDS, pause_min + 10)
            pause_max = min(PAUSE_HARD_CAP_SECONDS, max(pause_max, 30.0))
        return pause_min, pause_max

    # Micro-sleep после SKU и burst-pause при достижении лимита пачки.
    async def after_product(self, fetch_path: str) -> None:
        if fetch_path == "http":
            low, high = 0.4, 0.9
        else:
            low, high = 1.5, 2.5
        sleep_s = random.uniform(low, high) * random.uniform(0.8, 1.2)
        ratio = self.telemetry.challenge_ratio_last_window()
        if ratio >= self.env.challenge_medium_threshold:
            sleep_s = min(PAUSE_HARD_CAP_SECONDS, sleep_s * MEDIUM_SLEEP_MULTIPLIER)
        await self._sleep(sleep_s)

        self._burst_count += 1
        if self._burst_count < self._burst_limit:
            return
        pause_min, pause_max = self._effective_pause_bounds()
        pause_s = min(PAUSE_HARD_CAP_SECONDS, random.uniform(pause_min, pause_max))
        logger.info(
            "burst_pacer: пауза %.1f с после пачки=%s (лимит=%s)",
            pause_s,
            self._burst_count,
            self._burst_limit,
        )
        await self._sleep(pause_s)
        self._burst_count = 0
        if self.throttle is not None:
            self.throttle.note_burst_completed()
        self._burst_limit = random.randint(
            self.env.burst_min,
            self._ramp_burst_cap(),
        )

    # Пауза enrich_sleep без burst-логики (fallback).
    async def legacy_sleep(self) -> None:
        sleep_s = random.uniform(self.env.enrich_sleep_min, self.env.enrich_sleep_max)
        await self._sleep(sleep_s)

    # Sleep с учётом в telemetry pacing_overhead_pct.
    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.telemetry.record_pacing_sleep(seconds)
        await asyncio.sleep(seconds)


class ChallengeThrottle:
    # Ratio-cooldown чанка + lane-level 429/challenge/CAPTCHA state.
    def __init__(
        self,
        env: "Settings",
        telemetry: "PathTelemetry",
        store: MemoryLaneThrottleStore | RedisLaneThrottleStore | None = None,
        *,
        now: Any = None,
        sleep: Any = None,
    ) -> None:
        self.env = env
        self.telemetry = telemetry
        self.mode = "normal"
        self._cooldowns_used = 0
        self._lane_cooldowns_used = 0
        self._ramp_step = 0
        self._ramp_good_streak = 0
        self.lane_id = (getattr(env, "lane_id", None) or "default").strip() or "default"
        self._store = resolve_lane_throttle_store(store)
        self._now = now or time.time
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()

    @property
    def consecutive_429(self) -> int:
        return int(self._load().get("consecutive_429") or 0)

    @property
    def unhealthy(self) -> bool:
        until = float(self._load().get("unhealthy_until") or 0.0)
        return until > self._now()

    # Читает shared lane state (Redis или memory).
    def _load(self) -> dict[str, Any]:
        return self._store.load(self.lane_id)

    # Пишет shared lane state.
    def _save(self, state: dict[str, Any]) -> None:
        self._store.save(self.lane_id, state)

    # Человекочитаемый лог + JSON в debug для разбора.
    def _log_lane_event(
        self,
        event: str,
        sku: object | None,
        consecutive: int,
        cooldown_seconds: float,
    ) -> None:
        payload = {
            "sku": sku,
            "lane_id": self.lane_id,
            "event": event,
            "consecutive_429": consecutive,
            "cooldown_seconds": round(float(cooldown_seconds), 3),
        }
        logger.debug("lane_throttle %s", json.dumps(payload, ensure_ascii=False))
        if event == LANE_EVENT_SUCCESS:
            return
        label = {
            LANE_EVENT_HTTP_429: "HTTP 429",
            LANE_EVENT_CF_CHALLENGE: "CF challenge",
            LANE_EVENT_CAPTCHA: "CAPTCHA",
            LANE_EVENT_SUPPLIER_500: "HTTP 500",
            LANE_EVENT_TIMEOUT: "timeout",
            LANE_EVENT_NETWORK: "сеть",
        }
        base = event[:-5] if event.endswith("_wait") else event
        name = label.get(base, base)
        if event.endswith("_wait"):
            logger.warning(
                "[LANE %s] пауза %.0fс (%s)", self.lane_id, cooldown_seconds, name
            )
            return
        if event == LANE_EVENT_HTTP_429:
            logger.warning(
                "[LANE %s] HTTP 429 → пауза %.0fс",
                self.lane_id,
                cooldown_seconds,
            )
            return
        if event == LANE_EVENT_CF_CHALLENGE:
            logger.warning(
                "[LANE %s] CF challenge → пауза %.0fс → browser fallback",
                self.lane_id,
                cooldown_seconds,
            )
            return
        if event == LANE_EVENT_CAPTCHA:
            logger.warning(
                "[LANE %s] CAPTCHA → пауза %.0fс, lane unhealthy",
                self.lane_id,
                cooldown_seconds,
            )
            return
        if cooldown_seconds > 0:
            logger.warning(
                "[LANE %s] %s → пауза %.0fс",
                self.lane_id,
                name,
                cooldown_seconds,
            )

    # Ждёт lane cooldown/CAPTCHA unhealthy перед следующим HTTP request.
    async def await_http_allowed(self, sku: object | None = None) -> float:
        async with self._lock:
            return await self._await_http_allowed_locked(sku)

    async def _await_http_allowed_locked(self, sku: object | None) -> float:
        state = self._load()
        now = self._now()
        cooldown_until = max(
            float(state.get("cooldown_until") or 0.0),
            float(state.get("unhealthy_until") or 0.0),
        )
        remaining = max(0.0, cooldown_until - now)
        remaining = min(remaining, COOLDOWN_HARD_CAP_SECONDS)
        if remaining <= 0:
            return 0.0
        consecutive = int(state.get("consecutive_429") or 0)
        event = str(state.get("last_event") or "cooldown")
        self._log_lane_event(f"{event}_wait", sku, consecutive, remaining)
        self.telemetry.record_pacing_sleep(remaining)
        await self._sleep(remaining)
        return remaining

    # Обновляет consecutive_429 / cooldown / unhealthy по HTTP event.
    async def observe_http_event(self, event: str, sku: object | None = None) -> float:
        async with self._lock:
            return await self._observe_http_event_locked(event, sku)

    async def _observe_http_event_locked(self, event: str, sku: object | None) -> float:
        state = self._load()
        now = self._now()
        consecutive = int(state.get("consecutive_429") or 0)
        cooldown_until = float(state.get("cooldown_until") or 0.0)
        unhealthy_until = float(state.get("unhealthy_until") or 0.0)
        schedule = lane_429_schedule(self.env)
        applied = 0.0

        if event == LANE_EVENT_SUCCESS:
            consecutive = 0
            state["consecutive_429"] = 0
            state["last_event"] = event
            state["unhealthy_until"] = 0.0
            self._save(state)
            self._log_lane_event(event, sku, 0, 0.0)
            return 0.0

        if event == LANE_EVENT_HTTP_429:
            consecutive += 1
            applied = cooldown_for_consecutive_429(schedule, consecutive)
            cooldown_until = max(cooldown_until, now + applied)
            self._lane_cooldowns_used += 1
        elif event == LANE_EVENT_CF_CHALLENGE:
            applied = schedule[0] if schedule else DEFAULT_LANE_429_COOLDOWNS[0]
            cooldown_until = max(cooldown_until, now + applied)
            self._lane_cooldowns_used += 1
        elif event == LANE_EVENT_CAPTCHA:
            applied = float(
                getattr(self.env, "throttle_cooldown_max", COOLDOWN_HARD_CAP_SECONDS)
            )
            floor = schedule[-1] if schedule else applied
            applied = min(COOLDOWN_HARD_CAP_SECONDS, max(applied, floor))
            unhealthy_until = max(unhealthy_until, now + applied)
            cooldown_until = max(cooldown_until, unhealthy_until)
            self._lane_cooldowns_used += 1
        else:
            state["last_event"] = event
            self._save(state)
            self._log_lane_event(event, sku, consecutive, 0.0)
            return 0.0

        state["consecutive_429"] = consecutive
        state["cooldown_until"] = cooldown_until
        state["unhealthy_until"] = unhealthy_until
        state["last_event"] = event
        self._save(state)
        self._log_lane_event(event, sku, consecutive, applied)
        return applied

    # Проверяет challenge ratio и при необходимости ставит cooldown/ramp.
    async def maybe_throttle(self) -> None:
        if not self.env.challenge_throttle_enabled:
            return
        ratio = self.telemetry.challenge_ratio_last_window()
        if ratio < self.env.challenge_medium_threshold:
            self.mode = "normal"
            self._ramp_good_streak += 1
            if self._ramp_good_streak >= 20:
                self._ramp_step = 0
            return

        self._ramp_good_streak = 0
        if ratio < self.env.challenge_high_threshold:
            self.mode = "medium"
            return

        if self._cooldowns_used >= MAX_COOLDOWNS_PER_CHUNK:
            logger.warning(
                "challenge_throttle: лимит cooldown на чанк=%s",
                MAX_COOLDOWNS_PER_CHUNK,
            )
            self.mode = "normal"
            return

        cooldown = min(
            COOLDOWN_HARD_CAP_SECONDS,
            random.uniform(120.0, float(self.env.throttle_cooldown_max)),
        )
        self._cooldowns_used += 1
        self.mode = "cooldown"
        logger.warning(
            "throttle_cooldown: доля challenge=%.3f пауза=%.0f с (%s/%s)",
            ratio,
            cooldown,
            self._cooldowns_used,
            MAX_COOLDOWNS_PER_CHUNK,
        )
        self.telemetry.record_pacing_sleep(cooldown)
        await self._sleep(cooldown)
        self._ramp_step = 1
        self.mode = "ramp"

    @property
    def ramp_step(self) -> int:
        return self._ramp_step

    # Увеличивает шаг ramp после завершения burst (10→18→28→normal).
    def note_burst_completed(self) -> None:
        if self.mode != "ramp":
            return
        self._ramp_step = min(4, self._ramp_step + 1)
        if self._ramp_step >= 4:
            self.mode = "normal"
            self._ramp_step = 0


class SessionWarmer:
    # Периодически открывает listing/home для «живой» сессии.
    def __init__(
        self,
        env: "Settings",
        http_client: "ScraperHttpClient | None",
        telemetry: "PathTelemetry",
    ) -> None:
        self.env = env
        self.http_client = http_client
        self.telemetry = telemetry
        self._products_since_warm = 0
        self._last_warm_at = time.monotonic()
        self._collection_urls = env.get_collection_urls()

    # Заход на коллекцию/base URL и resync cookies в HTTP client.
    async def maybe_warm(self, ctx: Any) -> None:
        if not self.env.session_warming_enabled:
            return
        self._products_since_warm += 1
        elapsed_min = (time.monotonic() - self._last_warm_at) / 60
        if (
            self._products_since_warm < self.env.warm_every_products
            and elapsed_min < self.env.warm_every_minutes
        ):
            return

        target_url = self.env.base_url.rstrip("/")
        if self._collection_urls:
            target_url = random.choice(self._collection_urls)

        page = await ctx.new_page()
        try:
            await page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=self.env.collection_page_timeout_ms,
            )
            await page.wait_for_timeout(random.randint(2000, 4000))
            if self.http_client is not None:
                await self.http_client.sync_cookies_from_context(ctx)
                self.http_client.last_listing_url = target_url
        finally:
            await page.close()

        self._products_since_warm = 0
        self._last_warm_at = time.monotonic()
        logger.info("session_warmer: заход на %s", target_url)
