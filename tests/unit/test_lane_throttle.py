from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.integrations.supplier_demo.http_validation import (
    classify_lane_http_event,
    reject_http_html_reason,
)
from src.scraper.enrichment.product_dom import fetch_product_html
from src.scraper.pacing import (
    ChallengeThrottle,
    MemoryLaneThrottleStore,
    RedisLaneThrottleStore,
)
from src.scraper.telemetry import DomFetchMeta, PathTelemetry


# Settings-like env для ChallengeThrottle без полного Settings().
def _env(lane_id: str = "1") -> SimpleNamespace:
    return SimpleNamespace(
        lane_id=lane_id,
        lane_429_cooldowns="15,30,45,60",
        lane_429_throttle_enabled=True,
        throttle_cooldown_max=300,
        challenge_throttle_enabled=False,
        challenge_medium_threshold=0.05,
        challenge_high_threshold=0.12,
        burst_min=15,
        burst_max=40,
        dom_http_first=True,
        dom_http_timeout_ms=5000,
        dom_page_timeout_ms=5000,
        cookie_sync_every_n=50,
    )


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ChallengeThrottle с fake clock/sleep и общим store.
def _throttle(
    lane_id: str = "1",
    store: MemoryLaneThrottleStore | RedisLaneThrottleStore | None = None,
    clock: _Clock | None = None,
    slept: list[float] | None = None,
) -> tuple[ChallengeThrottle, _Clock, list[float]]:
    clock = clock or _Clock()
    slept = slept if slept is not None else []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    throttle = ChallengeThrottle(
        _env(lane_id),
        PathTelemetry(),
        store=store or MemoryLaneThrottleStore(),
        now=clock,
        sleep=_sleep,
    )
    return throttle, clock, slept


# 1. Первый 429 ставит cooldown 15s.
@pytest.mark.asyncio
async def test_first_429_sets_15s_cooldown() -> None:
    throttle, _, slept = _throttle()
    applied = await throttle.observe_http_event("http_429", sku=101)
    assert applied == 15.0
    assert throttle.consecutive_429 == 1
    waited = await throttle.await_http_allowed(sku=102)
    assert waited == 15.0
    assert slept == [15.0]


# 2. Подряд идущие 429 увеличивают cooldown.
@pytest.mark.asyncio
async def test_consecutive_429_increases_cooldown() -> None:
    throttle, clock, slept = _throttle()
    expected = [15.0, 30.0, 45.0, 60.0]
    for sku, cooldown in enumerate(expected, start=1):
        applied = await throttle.observe_http_event("http_429", sku=sku)
        assert applied == cooldown
        waited = await throttle.await_http_allowed(sku=sku)
        assert waited == cooldown
        clock.advance(0)
    assert slept == expected
    assert throttle.consecutive_429 == 4


# 5×429 не доходит до SCRAPER_THROTTLE_COOLDOWN_MAX (300).
@pytest.mark.asyncio
async def test_five_429_sum_stays_under_cooldown_max() -> None:
    throttle, _, slept = _throttle()
    expected = [15.0, 30.0, 45.0, 60.0, 60.0]
    for sku, cooldown in enumerate(expected, start=1):
        applied = await throttle.observe_http_event("http_429", sku=sku)
        assert applied == cooldown
        assert applied < 300.0
        await throttle.await_http_allowed(sku=sku)
    assert slept == expected
    assert sum(slept) == 210.0


# 3. Успешный HTTP сбрасывает consecutive_429.
@pytest.mark.asyncio
async def test_success_resets_consecutive_429() -> None:
    throttle, clock, _ = _throttle()
    await throttle.observe_http_event("http_429", sku=1)
    clock.advance(15)
    await throttle.observe_http_event("http_success", sku=2)
    assert throttle.consecutive_429 == 0
    applied = await throttle.observe_http_event("http_429", sku=3)
    assert applied == 15.0
    assert throttle.consecutive_429 == 1


# 4. Cooldown lane1 не блокирует HTTP lane2.
@pytest.mark.asyncio
async def test_lane1_cooldown_does_not_block_lane2() -> None:
    store = MemoryLaneThrottleStore()
    clock = _Clock()
    slept1: list[float] = []
    slept2: list[float] = []
    lane1, _, _ = _throttle("1", store=store, clock=clock, slept=slept1)
    lane2, _, _ = _throttle("2", store=store, clock=clock, slept=slept2)
    await lane1.observe_http_event("http_429", sku=1)
    waited2 = await lane2.await_http_allowed(sku=2)
    assert waited2 == 0.0
    assert slept2 == []
    waited1 = await lane1.await_http_allowed(sku=3)
    assert waited1 == 15.0


# 5. CF challenge с словом captcha в JS — не CAPTCHA.
def test_cf_challenge_is_not_captcha() -> None:
    html = (
        "<html><title>Just a moment...</title>"
        "<script>window._cf_chl_opt={captcha:false}</script>"
        "cloudflare challenge</html>"
    )
    assert reject_http_html_reason(html, 200) == "challenge"
    assert classify_lane_http_event(html, 200) == "cf_challenge"
    assert classify_lane_http_event("captcha in js", 429) == "http_429"


# 6. Реальная CAPTCHA помечает lane unhealthy и ставит cooldown.
@pytest.mark.asyncio
async def test_real_captcha_marks_lane_unhealthy() -> None:
    throttle, _, slept = _throttle()
    html = '<div class="cf-turnstile" data-sitekey="x"></div>'
    assert reject_http_html_reason(html, 200) == "captcha"
    applied = await throttle.observe_http_event("captcha", sku=9)
    assert applied == 300.0
    assert throttle.unhealthy is True
    waited = await throttle.await_http_allowed(sku=10)
    assert waited == 300.0
    assert slept == [300.0]


# 7. Нет tight HTTP retry: один HTTP 429, потом browser, cooldown перед следующим HTTP.
@pytest.mark.asyncio
async def test_no_tight_http_retry_loop() -> None:
    throttle, _, slept = _throttle()
    env = _env()
    session = SimpleNamespace(
        throttle=throttle,
        http_client=None,
        sync_cookies_after_browser=AsyncMock(),
    )
    http_calls = {"n": 0}
    browser_calls = {"n": 0}

    async def fake_http(ctx, url, env):
        http_calls["n"] += 1
        return None, DomFetchMeta(
            path="http",
            latency_ms=1,
            source="http_path",
            http_reject_reason="status=429",
            error_class="rate_limit",
            success=False,
        )

    async def fake_browser(ctx, url, env, source):
        browser_calls["n"] += 1
        return "<html>ok</html>", DomFetchMeta(
            path="browser",
            latency_ms=1,
            source=source,
            success=True,
        )

    with (
        patch(
            "src.scraper.enrichment.product_dom._fetch_product_html_via_http_legacy",
            fake_http,
        ),
        patch(
            "src.scraper.enrichment.product_dom._fetch_product_html_via_http_synced",
            fake_http,
        ),
        patch(
            "src.scraper.enrichment.product_dom._fetch_product_html_browser",
            fake_browser,
        ),
    ):
        html, path, _http_reject = await fetch_product_html(
            ctx=object(),
            url="https://example.com/p",
            env=env,
            session=session,
            http_first=True,
            sku=55,
        )
        assert html == "<html>ok</html>"
        assert path == "browser"
        assert http_calls["n"] == 1
        assert browser_calls["n"] == 1
        assert slept == []
        await fetch_product_html(
            ctx=object(),
            url="https://example.com/p2",
            env=env,
            session=session,
            http_first=True,
            sku=56,
        )
    assert http_calls["n"] == 2
    assert browser_calls["n"] == 2
    assert slept == [15.0]


# 8. Browser fallback после 429/challenge остаётся.
@pytest.mark.asyncio
async def test_browser_fallback_still_runs_after_429() -> None:
    throttle, _, _ = _throttle()
    env = _env()
    session = SimpleNamespace(
        throttle=throttle,
        http_client=None,
        sync_cookies_after_browser=AsyncMock(),
    )

    async def fake_http(ctx, url, env):
        return None, DomFetchMeta(
            path="http",
            latency_ms=1,
            source="http_path",
            http_reject_reason="status=429",
            success=False,
        )

    async def fake_browser(ctx, url, env, source):
        return "<pdp/>", DomFetchMeta(
            path="browser", latency_ms=2, source=source, success=True
        )

    with (
        patch(
            "src.scraper.enrichment.product_dom._fetch_product_html_via_http_legacy",
            fake_http,
        ),
        patch(
            "src.scraper.enrichment.product_dom._fetch_product_html_browser",
            fake_browser,
        ),
    ):
        html, path, _http_reject = await fetch_product_html(
            object(), "https://example.com/p", env, session=session, sku=1
        )
    assert path == "browser"
    assert html == "<pdp/>"


# 9. Два worker одной lane делят throttle state.
@pytest.mark.asyncio
async def test_two_workers_same_lane_share_throttle_state() -> None:
    store = MemoryLaneThrottleStore()
    clock = _Clock()
    worker_a, _, _ = _throttle("1", store=store, clock=clock)
    worker_b, _, slept_b = _throttle("1", store=store, clock=clock)
    await worker_a.observe_http_event("http_429", sku=1)
    assert worker_b.consecutive_429 == 1
    waited = await worker_b.await_http_allowed(sku=2)
    assert waited == 15.0
    assert slept_b == [15.0]

    fake_redis = _FakeRedis()
    redis_store = RedisLaneThrottleStore(fake_redis)
    w1, _, _ = _throttle("1", store=redis_store, clock=_Clock())
    w2, _, slept2 = _throttle("1", store=redis_store, clock=_Clock())
    await w1.observe_http_event("http_429", sku=11)
    await w1.observe_http_event("http_429", sku=12)
    assert w2.consecutive_429 == 2
    waited = await w2.await_http_allowed(sku=13)
    assert waited == 30.0
    assert slept2 == [30.0]


# 10. Разные lane держат независимое состояние.
@pytest.mark.asyncio
async def test_separate_lanes_have_independent_state() -> None:
    store = MemoryLaneThrottleStore()
    clock = _Clock()
    lane1, _, _ = _throttle("1", store=store, clock=clock)
    lane2, _, slept2 = _throttle("2", store=store, clock=clock)
    await lane1.observe_http_event("http_429", sku=1)
    await lane1.observe_http_event("http_429", sku=2)
    assert lane1.consecutive_429 == 2
    assert lane2.consecutive_429 == 0
    assert await lane2.await_http_allowed(sku=3) == 0.0
    assert slept2 == []


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        raw = value if isinstance(value, bytes) else str(value).encode()
        self.data[key] = raw

    def ping(self) -> bool:
        return True
