import os
from typing import Any
from urllib.parse import urlencode

from src.services.orders.dhl_tracking import DHL_SEARCH_URL, parse_dhl_http_response


# Определяет, нужно ли запускать браузер в headless-режиме.
def _playwright_headless() -> bool:
    return os.environ.get("SCRAPER_HEADLESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


# Собирает kwargs прокси для браузерного контекста Playwright.
def _browser_context_proxy(proxy_url: str | None) -> dict[str, Any] | None:
    if not proxy_url:
        return None
    return {"server": proxy_url}


# Загружает JSON DHL search API через Playwright (worker-dhl / scraper image).
async def fetch_dhl_tracking_payload_via_browser(
    piececode: str,
    language: str = "ru",
    proxy_url: str | None = None,
) -> dict[str, Any]:
    # Lazy import: runtime worker-tracking не тянет Playwright в образ.
    from playwright.async_api import async_playwright

    params = {"piececode": piececode.strip(), "language": language}
    url = f"{DHL_SEARCH_URL}?{urlencode(params)}"
    proxy = _browser_context_proxy(proxy_url)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=_playwright_headless())
        try:
            context = await browser.new_context(
                locale="de-DE",
                proxy=proxy,
            )
            try:
                response = await context.request.get(url, timeout=45_000)
                status = response.status
                content_type = response.headers.get("content-type", "")
                text = await response.text()
            finally:
                await context.close()
        finally:
            await browser.close()

    return parse_dhl_http_response(status, text, content_type or "")
