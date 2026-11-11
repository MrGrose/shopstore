import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")

_TELEGRAM_SDK = "telegram.org/js/telegram-web-app.js"
_LAUNCH_HASH = (
    "#tgWebAppData=query_id%3De2e%26user%3D%7B%22id%22%3A1%7D"
    "%26auth_date%3D1%26hash%3Dabc&tgWebAppVersion=7.0&tgWebAppPlatform=ios"
)
MINI_APP_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)


# True, если запрос — Telegram WebApp SDK.
def _is_telegram_sdk(url: str) -> bool:
    return _TELEGRAM_SDK in url


# Страница со сбором запросов к telegram.org.
def _tracked_page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    urls: list[str] = []
    page.on("request", lambda request: urls.append(request.url))
    return page, urls


# Открывает path и ждёт load.
def _goto(page: Page, path: str) -> None:
    page.goto(f"{BASE}{path}", wait_until="load", timeout=60000)


# Ждёт Home CTA.
def _expect_home(page: Page) -> None:
    expect(page.get_by_role("link", name="Открыть товары")).to_be_visible()
    path = urlparse(page.url).path
    assert path in {"", "/"}


# Ждёт ProductGrid: карточки, не fallback.
def _expect_catalog_grid(page: Page) -> None:
    expect(page.locator("#products [role='button']").first).to_be_visible(timeout=30000)


# Ждёт нижнюю навигацию Mini App.
def _expect_miniapp_nav(page: Page) -> None:
    expect(page.get_by_role("navigation", name="Навигация Mini App")).to_be_visible(
        timeout=15000
    )


@pytest.mark.e2e
def test_web_home_does_not_request_telegram_sdk() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, urls = _tracked_page(browser)
        _goto(page, "/")
        _expect_home(page)
        sdk = [url for url in urls if _is_telegram_sdk(url)]
        assert sdk == [], sdk
        browser.close()


@pytest.mark.e2e
def test_web_catalog_does_not_request_telegram_sdk() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, urls = _tracked_page(browser)
        _goto(page, "/catalog/padel")
        _expect_catalog_grid(page)
        sdk = [url for url in urls if _is_telegram_sdk(url)]
        assert sdk == [], sdk
        browser.close()


@pytest.mark.e2e
def test_miniapp_catalog_keeps_launch_params_after_router_start() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MINI_APP_UA,
        )
        page = context.new_page()
        page.goto(
            f"{BASE}/app/catalog{_LAUNCH_HASH}",
            wait_until="load",
            timeout=60000,
        )
        _expect_miniapp_nav(page)
        _expect_catalog_grid(page)
        stored = page.evaluate("() => sessionStorage.getItem('__telegram__initParams')")
        assert stored, stored
        assert "tgWebAppData" in stored
        assert "query_id=e2e" in stored
        assert "/app/catalog" in urlparse(page.url).path
        context.close()
        browser.close()


@pytest.mark.e2e
def test_miniapp_account_and_support_routes_are_reachable() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MINI_APP_UA,
        )
        page = context.new_page()
        page.goto(
            f"{BASE}/app/catalog{_LAUNCH_HASH}",
            wait_until="load",
            timeout=60000,
        )
        _expect_miniapp_nav(page)

        page.get_by_role("button", name="Профиль").click()
        page.wait_for_url(lambda url: "/account" in urlparse(url).path, timeout=15000)
        expect(page.get_by_role("button", name="Профиль")).to_be_visible()
        assert "tab=support" not in urlparse(page.url).query

        page.get_by_role("button", name="Поддержка").click()
        page.wait_for_url(
            lambda url: "tab=support" in urlparse(url).query, timeout=15000
        )
        expect(page.get_by_role("button", name="Поддержка")).to_be_visible()

        context.close()
        browser.close()
