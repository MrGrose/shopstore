import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import BasicAuth
from yarl import URL

from src.scraper.config.settings import Settings
from src.scraper.enrichment.http_validate import reject_http_html_reason

logger = logging.getLogger(__name__)

PAUSE_HARD_CAP_SECONDS = 90.0


# aiohttp proxy=/proxy_auth= из Playwright proxy dict; пустой -> не ставить прокси.
def aiohttp_proxy_kwargs(proxy: dict[str, str] | None) -> dict[str, Any]:
    if not proxy:
        return {}
    server = (proxy.get("server") or "").strip()
    if not server:
        return {}
    kwargs: dict[str, Any] = {"proxy": server}
    user = (proxy.get("username") or "").strip()
    password = proxy.get("password") or ""
    if user:
        kwargs["proxy_auth"] = BasicAuth(user, password)
    return kwargs


class ScraperHttpClient:
    # HTTP-first клиент: cookies из Playwright context + browser-like headers.
    def __init__(self, env: Settings, proxy: dict[str, str] | None = None) -> None:
        self.env = env
        self._proxy = proxy
        self._session: aiohttp.ClientSession | None = None
        self._cookie_jar = aiohttp.CookieJar(unsafe=True)
        self._requests_since_sync = 0
        self.last_listing_url = env.base_url.rstrip("/")

    # Закрывает aiohttp session.
    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # Лениво создаёт aiohttp ClientSession с cookie jar.
    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.env.dom_http_timeout_ms / 1000)
            self._session = aiohttp.ClientSession(
                cookie_jar=self._cookie_jar,
                timeout=timeout,
                trust_env=False,
            )
        return self._session

    # Playwright context — source of truth для auth cookies.
    async def sync_cookies_from_context(self, ctx: Any) -> int:
        cookies = await ctx.cookies()
        self._cookie_jar.clear()
        synced = 0
        for item in cookies:
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            domain = str(item.get("domain") or "")
            path = str(item.get("path") or "/")
            if not name:
                continue
            secure = bool(item.get("secure"))
            host = domain.lstrip(".")
            scheme = "https" if secure else "http"
            self._cookie_jar.update_cookies(
                {name: value},
                response_url=URL(f"{scheme}://{host}{path}"),
            )
            synced += 1
        self._requests_since_sync = 0
        logger.debug("HTTP cookie sync: cookies=%s", synced)
        return synced

    # Заголовки GET как у navigate в Chrome.
    def _browser_headers(self, url: str, referer: str | None) -> dict[str, str]:
        ref = referer or self.last_listing_url or self.env.base_url
        same_origin = urlparse(ref).netloc == urlparse(url).netloc
        return {
            "User-Agent": self.env.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if same_origin else "none",
            "Sec-Fetch-User": "?1",
            "Sec-Ch-Ua": (
                '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"'
            ),
            "Referer": ref,
        }

    # GET PDP через aiohttp; None + reject_reason если HTML не прошёл validate.
    async def fetch(
        self,
        url: str,
        ctx: Any,
        *,
        referer: str | None = None,
    ) -> tuple[str | None, int | None, str | None]:
        if self._requests_since_sync >= self.env.cookie_sync_every_n:
            await self.sync_cookies_from_context(ctx)

        session = await self._ensure_session()
        headers = self._browser_headers(url, referer)
        try:
            proxy_kw = aiohttp_proxy_kwargs(self._proxy)
            async with session.get(
                url, headers=headers, allow_redirects=True, **proxy_kw
            ) as response:
                html = (await response.text()) or ""
                status = response.status
        except TimeoutError as exc:
            logger.debug("HTTP-first aiohttp: timeout для %s — %s", url, exc)
            return None, None, "timeout"
        except Exception as exc:
            logger.debug("HTTP-first aiohttp: ошибка для %s — %s", url, exc)
            return None, None, "request_error"

        self._requests_since_sync += 1
        reject_reason = reject_http_html_reason(html, status)
        if reject_reason:
            return None, status, reject_reason
        return html, status, None
