import os
import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")

_CATALOG_CHUNK = re.compile(r"/assets/CatalogRoutes-[^/?#]+\.js$")
_ENTRY_CHUNK = re.compile(r"/assets/index-[^/?#]+\.js$")
_VITE_DEV_MARKERS = ("/@vite/", "/@react-refresh", "/src/app/")


# True, если URL — catalog feature chunk (имя модуля стабильно, hash нет).
def _is_catalog_chunk(url: str) -> bool:
    return bool(_CATALOG_CHUNK.search(urlparse(url).path))


# True, если URL — Vite entry chunk.
def _is_entry_chunk(url: str) -> bool:
    return bool(_ENTRY_CHUNK.search(urlparse(url).path))


# True, если это JS-ресурс (script или .js path).
def _is_js_request(url: str, resource_type: str) -> bool:
    if resource_type == "script":
        return True
    return urlparse(url).path.endswith(".js")


# Страница со сбором JS-запросов и runtime errors.
def _tracked_page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    scripts: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []

    def on_request(request) -> None:
        if _is_js_request(request.url, request.resource_type):
            scripts.append(request.url)

    def on_console(msg) -> None:
        if msg.type == "error":
            console_errors.append(msg.text)

    page.on("request", on_request)
    page.on("console", on_console)
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    return page, scripts, console_errors, page_errors


# Skip, если витрина с Vite dev, а не production dist.
def _require_production_assets(scripts: list[str]) -> None:
    blob = " ".join(scripts)
    if any(marker in blob for marker in _VITE_DEV_MARKERS):
        pytest.skip("PR3 chunk tests need production storefront, not Vite dev")


# Падает, если были pageerror или console error (кроме favicon).
def _assert_no_runtime_errors(
    console_errors: list[str], page_errors: list[str]
) -> None:
    unexpected = [error for error in console_errors if "favicon" not in error.lower()]
    assert not unexpected, "console errors: " + " | ".join(unexpected)
    assert not page_errors, "page errors: " + " | ".join(page_errors)


# Ждёт Home CTA.
def _expect_home(page: Page) -> None:
    expect(page.get_by_role("link", name="Открыть товары")).to_be_visible()
    path = urlparse(page.url).path
    assert path in {"", "/"}


# Ждёт ProductGrid: карточки и sub-nav, не fallback.
def _expect_catalog_grid(page: Page) -> None:
    expect(page.locator("#products [role='button']").first).to_be_visible(timeout=30000)
    expect(page.get_by_role("navigation", name="Подкатегории")).to_be_visible()
    assert page.locator("#products [role='button']").count() >= 1


# Открывает path и ждёт load (без произвольного timeout).
def _goto(page: Page, path: str) -> None:
    page.goto(f"{BASE}{path}", wait_until="load", timeout=60000)


@pytest.mark.e2e
def test_direct_catalog_padel_renders_grid() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, scripts, console_errors, page_errors = _tracked_page(browser)
        _goto(page, "/catalog/padel")
        _require_production_assets(scripts)
        _expect_catalog_grid(page)
        assert "/catalog/padel" in urlparse(page.url).path
        assert any(_is_catalog_chunk(url) for url in scripts), scripts
        _assert_no_runtime_errors(console_errors, page_errors)
        browser.close()


@pytest.mark.e2e
def test_home_does_not_load_catalog_chunk() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, scripts, console_errors, page_errors = _tracked_page(browser)
        _goto(page, "/")
        _expect_home(page)
        _require_production_assets(scripts)
        assert any(_is_entry_chunk(url) for url in scripts), scripts
        catalog_scripts = [url for url in scripts if _is_catalog_chunk(url)]
        assert catalog_scripts == [], catalog_scripts
        _assert_no_runtime_errors(console_errors, page_errors)
        browser.close()


@pytest.mark.e2e
def test_home_to_catalog_loads_chunk_and_renders() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, scripts, console_errors, page_errors = _tracked_page(browser)
        _goto(page, "/")
        _expect_home(page)
        _require_production_assets(scripts)
        assert not any(_is_catalog_chunk(url) for url in scripts), scripts

        page.locator("a[href='/catalog/padel']").first.click()
        page.wait_for_url(
            lambda url: urlparse(url).path == "/catalog/padel", timeout=15000
        )
        _expect_catalog_grid(page)
        assert any(_is_catalog_chunk(url) for url in scripts), scripts
        _assert_no_runtime_errors(console_errors, page_errors)
        browser.close()


@pytest.mark.e2e
def test_back_from_catalog_returns_home() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page, scripts, console_errors, page_errors = _tracked_page(browser)
        _goto(page, "/")
        _expect_home(page)
        page.locator("a[href='/catalog/padel']").first.click()
        page.wait_for_url(
            lambda url: urlparse(url).path == "/catalog/padel", timeout=15000
        )
        _expect_catalog_grid(page)

        page.go_back()
        _expect_home(page)
        _assert_no_runtime_errors(console_errors, page_errors)
        browser.close()
