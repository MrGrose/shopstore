import asyncio
import logging
import random
from dataclasses import dataclass

from playwright.async_api import BrowserContext

from src.scraper.config.config import ParseConfig
from src.scraper.config.settings import Settings
from src.scraper.infrastructure.browser_manager import BrowserManager
from src.scraper.infrastructure.http_client import ScraperHttpClient
from src.scraper.pacing import (
    BurstPacer,
    ChallengeThrottle,
    SessionWarmer,
    resolve_lane_throttle_store,
)
from src.scraper.telemetry import PathTelemetry

logger = logging.getLogger(__name__)


class DomSession:
    # Собирает ссылки на browser, HTTP client и pacing одного DOM-чанка.
    def __init__(
        self,
        env: Settings,
        manager: BrowserManager,
        ctx: BrowserContext,
        telemetry: PathTelemetry,
        http_client: ScraperHttpClient | None,
        pacer: BurstPacer | None,
        warmer: SessionWarmer | None,
        throttle: ChallengeThrottle | None,
    ) -> None:
        self.env = env
        self.manager = manager
        self.ctx = ctx
        self.telemetry = telemetry
        self.http_client = http_client
        self.pacer = pacer
        self.warmer = warmer
        self.throttle = throttle

    # Поднимает browser и step4-компоненты по флагам из env.
    @classmethod
    async def open(cls, env: Settings, config: ParseConfig) -> "DomSession":
        manager = BrowserManager(config)
        ctx = await manager.launch_browser()
        telemetry = PathTelemetry(window_size=env.throttle_window_size)

        throttle = ChallengeThrottle(
            env,
            telemetry,
            store=resolve_lane_throttle_store(),
        )
        http_client: ScraperHttpClient | None = None
        if env.http_cookie_sync_enabled:
            http_client = ScraperHttpClient(env, manager.active_proxy())
            await http_client.sync_cookies_from_context(ctx)
            urls = env.get_collection_urls()
            if urls:
                http_client.last_listing_url = urls[0]

        pacer = (
            BurstPacer(env, telemetry, throttle=throttle)
            if env.burst_pacing_enabled
            else None
        )
        warmer = (
            SessionWarmer(env, http_client, telemetry)
            if env.session_warming_enabled
            else None
        )

        logger.info(
            "DomSession: flags session=%s cookie_sync=%s burst=%s warm=%s throttle=%s",
            env.dom_session_enabled,
            env.http_cookie_sync_enabled,
            env.burst_pacing_enabled,
            env.session_warming_enabled,
            env.challenge_throttle_enabled,
        )
        return cls(env, manager, ctx, telemetry, http_client, pacer, warmer, throttle)

    # Закрывает HTTP client и browser в конце DOM-чанка.
    async def close(self) -> None:
        if self.http_client is not None:
            await self.http_client.close()
        await self.manager.close_browser()

    # Копирует cookies из Playwright в HTTP client после browser fetch.
    async def sync_cookies_after_browser(self) -> None:
        if self.http_client is not None:
            await self.http_client.sync_cookies_from_context(self.ctx)

    # Хуки перед SKU: throttle и session warming.
    async def before_product(self) -> None:
        if self.throttle is not None:
            await self.throttle.maybe_throttle()
        if self.warmer is not None:
            await self.warmer.maybe_warm(self.ctx)

    # Хуки после SKU: burst pacing или legacy sleep.
    async def after_product(self, fetch_path: str) -> None:
        if self.pacer is not None:
            await self.pacer.after_product(fetch_path)
            return
        sleep_s = random.uniform(self.env.enrich_sleep_min, self.env.enrich_sleep_max)
        self.telemetry.record_pacing_sleep(sleep_s)
        await asyncio.sleep(sleep_s)


@dataclass(slots=True)
class LegacyDomChunk:
    env: Settings
    manager: BrowserManager
    ctx: BrowserContext
    telemetry: PathTelemetry
    http_client: ScraperHttpClient | None = None

    # Закрывает browser без HTTP client (legacy режим).
    async def close(self) -> None:
        await self.manager.close_browser()

    # No-op: в legacy нет HTTP cookie sync.
    async def sync_cookies_after_browser(self) -> None:
        return

    # No-op: в legacy нет warming/throttle.
    async def before_product(self) -> None:
        return

    # Legacy micro-pause между SKU.
    async def after_product(self, fetch_path: str) -> None:
        sleep_s = random.uniform(self.env.enrich_sleep_min, self.env.enrich_sleep_max)
        self.telemetry.record_pacing_sleep(sleep_s)
        await asyncio.sleep(sleep_s)


DomChunk = DomSession | LegacyDomChunk


# Открывает DomSession или legacy chunk в зависимости от SCRAPER_DOM_SESSION_ENABLED.
async def open_dom_chunk(env: Settings, config: ParseConfig) -> DomChunk:
    if env.dom_session_enabled:
        return await DomSession.open(env, config)
    manager = BrowserManager(config)
    ctx = await manager.launch_browser()
    telemetry = PathTelemetry(window_size=env.throttle_window_size)
    logger.info("DomSession: legacy chunk (SCRAPER_DOM_SESSION_ENABLED=false)")
    return LegacyDomChunk(env=env, manager=manager, ctx=ctx, telemetry=telemetry)
