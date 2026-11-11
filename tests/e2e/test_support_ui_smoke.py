import asyncio
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

from src.core.security import create_access_token
from src.repositories.session import async_session_maker
from tests.integration.helpers.test_customer import create_test_customer

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


async def setup_email_buyer(stamp: str) -> tuple[int, str]:
    email = f"smoke-support-{stamp}@local.test"
    async with async_session_maker() as session:
        user = await create_test_customer(
            session,
            name=f"Smoke Support {stamp}",
            email=email,
            telegram_username=None,
            telegram_id=None,
        )
        await session.commit()
        user_id = user.id
    return user_id, create_access_token(user_id)


def admin_client(base: str) -> httpx.Client:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    client = httpx.Client(base_url=base, follow_redirects=True, timeout=30)
    client.post(
        "/internal/admin/login",
        data={
            "username": login,
            "password": password,
            "next": "/internal/admin/products",
        },
    )
    return client


def cleanup_user_http(base: str, user_id: int) -> None:
    try:
        client = admin_client(base)
        response = client.post(f"/internal/admin/customers/{user_id}/delete")
        if response.status_code not in (200, 303):
            print(f"WARN cleanup user #{user_id}: HTTP {response.status_code}")
    except Exception as exc:
        print(f"WARN cleanup user #{user_id}: {exc}")


def storefront_auth(page, base: str, token: str) -> None:
    page.goto(base)
    page.context.add_cookies(
        [
            {
                "name": "access_token",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "sameSite": "Lax",
            }
        ]
    )
    page.evaluate("(token) => localStorage.setItem('access_token', token)", token)


def playwright_admin_login(page, base: str) -> None:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    page.goto(f"{base}/internal/admin/login")
    page.fill("#username", login)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(
        lambda url: "/internal/admin/login" not in url,
        timeout=10000,
    )


def run_lk_support_create(base: str, token: str, stamp: str) -> int:
    body = f"Smoke LK support {stamp}"
    ticket_id: int | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        storefront_auth(page, base, token)
        page.goto(f"{base}/account?tab=support")
        page.wait_for_selector('h2:has-text("Поддержка")', timeout=15000)
        page.wait_for_selector('h3:has-text("Новое обращение")', timeout=10000)
        page.wait_for_selector(
            'input[type="file"][accept*="image/jpeg"]', timeout=10000
        )
        page.fill('textarea[placeholder="Опишите вопрос или проблему"]', body)
        page.click('button:has-text("Отправить")')
        page.wait_for_selector(f'text="{body}"', timeout=15000)
        heading = page.locator(
            "h3", has_text=re.compile(r"Обращение #\d+")
        ).inner_text()
        match = re.search(r"#(\d+)", heading)
        if not match:
            raise RuntimeError(f"lk support: не найден ticket id ({heading})")
        ticket_id = int(match.group(1))
        browser.close()
    if ticket_id is None:
        raise RuntimeError("lk support: ticket_id не получен")
    return ticket_id


def run_admin_reply_tg_badge(base: str, ticket_id: int, stamp: str) -> None:
    reply = f"Smoke admin reply {stamp}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        playwright_admin_login(page, base)
        page.goto(f"{base}/internal/admin/support?id={ticket_id}")
        page.wait_for_selector("#support-reply", timeout=10000)
        page.wait_for_selector("#support-reply-files", timeout=10000)
        page.fill("#support-reply", reply)
        page.get_by_role("button", name="Отправить ответ").click()
        page.wait_for_url(
            lambda url: f"id={ticket_id}" in url and "/internal/admin/support" in url,
            timeout=15000,
        )
        page.wait_for_selector("text=TG не доставлен", timeout=10000)
        if reply not in page.content():
            raise RuntimeError("admin reply: текст ответа не на странице")
        if "Telegram клиенту не доставлен" not in page.content():
            raise RuntimeError("admin reply: нет flash об ошибке TG")
        browser.close()


def run_support_ui_smoke() -> list[str]:
    load_env()
    base = os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
    stamp = str(int(time.time()))
    user_id: int | None = None
    ticket_id: int | None = None
    results: list[tuple[str, bool, str]] = []

    try:
        user_id, token = asyncio.run(setup_email_buyer(stamp))
    except Exception as exc:
        results.append(("setup_email_buyer", False, str(exc)))
        failed = [name for name, ok, _ in results if not ok]
        for name, ok, info in results:
            suffix = f" ({info})" if info else ""
            print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")
        return failed

    try:
        ticket_id = run_lk_support_create(base, token, stamp)
        results.append(("playwright_lk_support_create", True, f"ticket_id={ticket_id}"))
    except Exception as exc:
        results.append(("playwright_lk_support_create", False, str(exc)))

    if ticket_id:
        try:
            run_admin_reply_tg_badge(base, ticket_id, stamp)
            results.append(
                ("playwright_admin_reply_tg_badge", True, f"ticket_id={ticket_id}")
            )
        except Exception as exc:
            results.append(("playwright_admin_reply_tg_badge", False, str(exc)))
    else:
        results.append(("playwright_admin_reply_tg_badge", False, "no ticket"))

    if user_id:
        cleanup_user_http(base, user_id)

    failed = []
    for name, ok, info in results:
        suffix = f" ({info})" if info else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")
        if not ok:
            failed.append(name)
    return failed


@pytest.mark.e2e
def test_support_ui_smoke() -> None:
    failed = run_support_ui_smoke()
    assert not failed, f"failed checks: {', '.join(failed)}"


if __name__ == "__main__":
    raise SystemExit(0 if not run_support_ui_smoke() else 1)
