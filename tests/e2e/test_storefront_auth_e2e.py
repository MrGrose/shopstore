"""Browser E2E for storefront auth flows (web login guard, logout, Mini App retry).

Requires local API with built storefront on http://localhost:8000:
    uv run pytest tests/e2e/test_storefront_auth_e2e.py -m e2e -q
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect, sync_playwright
from sqlalchemy import select

from src.core.security import create_access_token
from src.models.auth_identity import AuthIdentity
from src.models.user import User
from src.repositories.session import async_session_maker

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")
BUYER_TELEGRAM_ID = "920001001"

MINI_APP_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

TELEGRAM_EMPTY_INIT_DATA_MOCK = """
window.Telegram = {
  WebApp: {
    initData: 'query_id=e2e&user=%7B%22id%22%3A1%7D&auth_date=1&hash=invalid',
    platform: 'ios',
    version: '7.0',
    ready: () => {},
    expand: () => {},
    setHeaderColor: () => {},
    setBackgroundColor: () => {},
  },
};
"""


@dataclass(frozen=True)
class Buyer:
    id: int
    token: str


async def _load_buyer() -> Buyer:
    async with async_session_maker() as session:
        row = (
            await session.execute(
                select(User)
                .join(AuthIdentity, AuthIdentity.user_id == User.id)
                .where(
                    AuthIdentity.provider == "telegram",
                    AuthIdentity.provider_user_id == BUYER_TELEGRAM_ID,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        pytest.skip("E2E buyer fixture 920001001 not found in DB")
    return Buyer(id=row.id, token=create_access_token(row.id))


def _run_async(coro):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _open(page: Page, path: str) -> None:
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    page.wait_for_timeout(400)


def _storefront_auth(page: Page, token: str) -> None:
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE + "/"}]
    )
    page.evaluate("(t) => localStorage.setItem('access_token', t)", token)


@pytest.mark.e2e
def test_web_account_redirects_to_login_when_unauthenticated() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/account")
        page.wait_for_url(lambda url: "/login" in url, timeout=8000)
        assert "next=%2Faccount" in page.url or "next=/account" in page.url

        browser.close()


@pytest.mark.e2e
def test_web_login_page_renders_phone_entry() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/login?next=%2Faccount")
        expect(page.get_by_placeholder("Номер телефона")).to_be_visible()

        browser.close()


@pytest.mark.e2e
def test_web_authenticated_account_and_logout() -> None:
    buyer = _run_async(_load_buyer())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        _storefront_auth(page, buyer.token)
        _open(page, "/account")
        expect(page.get_by_role("button", name="Заказы")).to_be_visible()

        page.get_by_role("button", name="Выйти").click()
        page.wait_for_url(lambda url: "/catalog" in url, timeout=8000)
        token = page.evaluate("() => localStorage.getItem('access_token')")
        assert not token

        context.close()
        browser.close()


def _block_telegram_sdk(route) -> None:
    if "telegram-web-app.js" in route.request.url:
        route.fulfill(status=200, content_type="application/javascript", body="")
        return
    route.continue_()


@pytest.mark.e2e
def test_miniapp_auth_retry_without_init_data() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=MINI_APP_UA,
        )
        context.route("**/*", _block_telegram_sdk)
        page = context.new_page()
        page.add_init_script(TELEGRAM_EMPTY_INIT_DATA_MOCK)

        _open(page, "/app/account")

        retry = page.get_by_role("button", name="Повторить вход")
        expect(retry).to_be_visible(timeout=15000)
        expect(page.get_by_text("Telegram", exact=False)).to_be_visible()

        retry.click()
        page.wait_for_timeout(800)
        expect(page.get_by_role("button", name="Повторить вход")).to_be_visible()

        context.close()
        browser.close()
