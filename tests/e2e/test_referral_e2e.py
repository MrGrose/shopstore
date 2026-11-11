"""Browser E2E for the referral migration checklist.

Run with a local API serving the storefront on http://localhost:8000:
    uv run pytest tests/e2e/test_referral_e2e.py -m e2e -q
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright
from sqlalchemy import create_engine, select, text

from src.core.config import settings
from src.core.security import create_access_token
from src.models.auth_identity import AuthIdentity
from src.models.order import Order, OrderStatus
from src.models.product import Product
from src.models.user import User
from src.repositories.session import async_session_maker

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")
FIXTURE_IDS = {
    "buyer_a": "920001001",
    "buyer_b": "920001002",
    "buyer_c": "920001003",
    "inactive": "920001004",
}


@dataclass(frozen=True)
class Buyer:
    id: int
    token: str
    code: str
    alias: str | None


async def _load_buyers() -> dict[str, Buyer]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(User, AuthIdentity.provider_user_id)
                .join(AuthIdentity, AuthIdentity.user_id == User.id)
                .where(
                    AuthIdentity.provider == "telegram",
                    AuthIdentity.provider_user_id.in_(FIXTURE_IDS.values()),
                )
            )
        ).all()
    by_provider_id = {
        provider_id: Buyer(
            id=user.id,
            token=create_access_token(user.id),
            code=user.referral_code or "",
            alias=user.referral_alias,
        )
        for user, provider_id in rows
    }
    return {
        key: by_provider_id[provider_id] for key, provider_id in FIXTURE_IDS.items()
    }


async def _load_admin_id() -> int:
    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.role == "admin").limit(1))
        ).scalar_one()
        return user.id


async def _reset_admin_e2e_state(
    *, with_product: bool = False
) -> tuple[dict[str, Buyer], int, int | None]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(User, AuthIdentity.provider_user_id)
                .join(AuthIdentity, AuthIdentity.user_id == User.id)
                .where(
                    AuthIdentity.provider == "telegram",
                    AuthIdentity.provider_user_id.in_(FIXTURE_IDS.values()),
                )
            )
        ).all()
        for user, _ in rows:
            user.referrer_id = None
            user.referral_attribution_locked = False
        buyer_b = next(
            user for user, provider_id in rows if provider_id == FIXTURE_IDS["buyer_b"]
        )
        active_orders = list(
            await session.scalars(
                select(Order).where(
                    Order.user_id == buyer_b.id,
                    Order.status.not_in((OrderStatus.COMPLETED, OrderStatus.CANCELLED)),
                )
            )
        )
        for order in active_orders:
            order.status = OrderStatus.CANCELLED
            session.add(order)
        admin = (
            await session.execute(select(User).where(User.role == "admin").limit(1))
        ).scalar_one()
        product_id = None
        if with_product:
            product_id = (
                (
                    await session.execute(
                        select(Product)
                        .where(Product.is_active.is_(True), Product.available_qty > 0)
                        .order_by(Product.id)
                        .limit(1)
                    )
                )
                .scalar_one()
                .id
            )
        await session.commit()
        by_provider_id = {
            provider_id: Buyer(
                id=user.id,
                token=create_access_token(user.id),
                code=user.referral_code or "",
                alias=user.referral_alias,
            )
            for user, provider_id in rows
        }
    return (
        {key: by_provider_id[provider_id] for key, provider_id in FIXTURE_IDS.items()},
        admin.id,
        product_id,
    )


async def _load_sellable_product_id() -> int:
    async with async_session_maker() as session:
        product = (
            await session.execute(
                select(Product)
                .where(Product.is_active.is_(True), Product.available_qty > 0)
                .order_by(Product.id)
                .limit(1)
            )
        ).scalar_one()
        return product.id


async def _mark_order_paid_processing(order_id: int) -> None:
    del order_id


def _mark_order_paid_processing_sync(order_id: int) -> None:
    url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE orders SET status = 'completed', payment_provider = 'e2e', "
                "payment_status = 'IPS_ACCEPTED', payment_paid_at = CURRENT_TIMESTAMP "
                "WHERE id = :order_id"
            ),
            {"order_id": order_id},
        )
    engine.dispose()


def _create_e2e_referral_earning_sync(
    order_id: int, referrer_id: int, referred_user_id: int
) -> None:
    """Complete the disabled-payment dev path and exercise the persisted earning UI."""
    url = settings.database_url.replace("+asyncpg", "+psycopg2")
    engine = create_engine(url)
    with engine.begin() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT total_amount, delivery_fee_amount "
                    "FROM orders WHERE id = :order_id"
                ),
                {"order_id": order_id},
            )
            .mappings()
            .one()
        )
        base = Decimal(str(row["total_amount"] or 0)) - Decimal(
            str(row["delivery_fee_amount"] or 0)
        )
        percent = connection.execute(
            text(
                "SELECT referral_commission_percent FROM pricing_settings "
                "ORDER BY id LIMIT 1"
            )
        ).scalar_one()
        amount = (base * Decimal(str(percent)) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        connection.execute(
            text(
                "INSERT INTO referral_earnings "
                "(referrer_id, referred_user_id, order_id, order_amount_rub, "
                "commission_percent, commission_amount_rub) "
                "VALUES (:referrer_id, :referred_user_id, :order_id, "
                ":base, :percent, :amount) "
                "ON CONFLICT (order_id) DO NOTHING"
            ),
            {
                "referrer_id": referrer_id,
                "referred_user_id": referred_user_id,
                "order_id": order_id,
                "base": base,
                "percent": percent,
                "amount": amount,
            },
        )
    engine.dispose()


def _run_async_in_thread(coro):
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def _auth_page(browser: Browser, buyer: Buyer, *, width: int, height: int) -> Page:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        permissions=["clipboard-read", "clipboard-write"],
    )
    context.add_cookies(
        [{"name": "access_token", "value": buyer.token, "url": BASE + "/"}]
    )
    page = context.new_page()
    page.goto(f"{BASE}/account?tab=referrals")
    page.evaluate("(token) => localStorage.setItem('access_token', token)", buyer.token)
    page.reload()
    return page


def _assert_no_browser_errors(
    page: Page, errors: list[str], page_errors: list[str]
) -> None:
    unexpected_console = [error for error in errors if "favicon" not in error.lower()]
    assert not unexpected_console, "console errors: " + " | ".join(unexpected_console)
    assert not page_errors, "page errors: " + " | ".join(page_errors)


def _load_admin_env() -> tuple[str, str]:
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    if os.path.exists(env_path):
        for raw in open(env_path, encoding="utf-8"):
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
    login = os.environ.get("ADMIN_PANEL_LOGIN")
    password = os.environ.get("ADMIN_PANEL_PASSWORD")
    if not login or not password:
        pytest.skip("ADMIN_PANEL_LOGIN/ADMIN_PANEL_PASSWORD не заданы")
    return login, password


def _admin_page(browser: Browser) -> Page:
    login, password = _load_admin_env()
    page = browser.new_page(viewport={"width": 1440, "height": 1024})
    page.goto(f"{BASE}/internal/admin/login")
    page.locator("#username").fill(login)
    page.locator("#password").fill(password)
    page.get_by_role("button", name="Войти").click()
    page.wait_for_url(lambda url: "/internal/admin/login" not in url, timeout=10000)
    return page


@pytest.mark.e2e
def test_referral_buyer_link_desktop_and_mobile() -> None:
    buyers = asyncio.run(_load_buyers())
    assert len(buyers["buyer_a"].code) == 12
    assert not buyers["buyer_a"].code.upper().startswith("PS-")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1440, 900), (390, 844)):
            errors: list[str] = []
            page_errors: list[str] = []
            page = _auth_page(browser, buyers["buyer_a"], width=width, height=height)
            page.on(
                "console",
                lambda msg: errors.append(msg.text()) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            expect(
                page.get_by_role("heading", name="Реферальная программа")
            ).to_be_visible()
            link_text = page.locator(".font-mono").first
            link_value = link_text.inner_text()
            assert (
                buyers["buyer_a"].code in link_value
                or f"/ref/{buyers['buyer_a'].alias}" in link_value
            ), f"unexpected referral link: {link_value}"
            expect(page.get_by_role("button", name="Копировать")).to_be_visible()
            expect(page.get_by_text("PS-")).to_have_count(0)
            page.get_by_role("button", name="Копировать").click()
            expect(page.get_by_role("button", name="Скопировано")).to_be_visible()
            _assert_no_browser_errors(page, errors, page_errors)
            page.context.close()
        browser.close()


@pytest.mark.e2e
def test_referral_capture_last_touch_and_cookie_policy() -> None:
    buyers = asyncio.run(_load_buyers())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"{BASE}/catalog?ref={buyers['buyer_a'].code}")
        page.wait_for_timeout(500)
        cookies = context.cookies(BASE)
        assert cookies, (
            f"referral cookie missing at {page.url}; "
            f"body={page.locator('body').inner_text()[:500]}"
        )
        cookie = cookies[0]
        assert cookie["name"] == "referral_code"
        assert cookie["value"] == buyers["buyer_a"].code
        assert cookie["sameSite"] == "Lax"
        assert cookie["expires"] > 0

        page.goto(f"{BASE}/catalog?ref={buyers['buyer_c'].code}")
        page.reload()
        page.wait_for_timeout(200)
        cookie = next(
            item for item in context.cookies(BASE) if item["name"] == "referral_code"
        )
        assert cookie["value"] == buyers["buyer_c"].code

        page.goto(f"{BASE}/catalog?ref=invalidtestcode123")
        page.reload()
        page.wait_for_timeout(200)
        cookie = next(
            item for item in context.cookies(BASE) if item["name"] == "referral_code"
        )
        assert cookie["value"] == "invalidtestcode123"
        assert "PS-" not in page.locator("body").inner_text()
        context.close()
        browser.close()


@pytest.mark.e2e
def test_referral_buyer_profile_is_read_only() -> None:
    buyers = asyncio.run(_reset_admin_e2e_state())[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _auth_page(browser, buyers["buyer_b"], width=390, height=844)
        page.get_by_role("button", name="Профиль").click()
        expect(page.get_by_role("heading", name="Личная информация")).to_be_visible()
        expect(
            page.get_by_text("Смена реферера — только через поддержку.")
        ).to_have_count(0)
        expect(page.get_by_role("button", name="Отвязать")).to_have_count(0)
        expect(page.get_by_text("payout", exact=False)).to_have_count(0)
        page.context.close()
        browser.close()


@pytest.mark.e2e
def test_referral_admin_clear_set_replace_and_cycle() -> None:
    buyers = asyncio.run(_reset_admin_e2e_state())[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _admin_page(browser)
        b = buyers["buyer_b"]
        a = buyers["buyer_a"]
        c = buyers["buyer_c"]

        page.goto(f"{BASE}/internal/admin/customers?id={b.id}")
        referral_card = page.locator("aside.customers-detail-side details").filter(
            has_text="Редактировать реферала"
        )
        referral_card.locator("summary").click()
        referrer_form = page.locator(f'form[action*="/customers/{b.id}/referrer"]')
        expect(referrer_form).to_be_visible()

        referrer_form.locator('select[name="referrer_id"]').select_option(str(a.id))
        referrer_form.locator('input[name="referrer_change_reason"]').fill(
            "E2E initial set"
        )
        referrer_form.get_by_role("button", name="Сохранить").click()
        page.wait_for_url(lambda url: f"id={b.id}" in url and "success=" in url)
        expect(page.locator("body")).to_contain_text("Реферал клиента обновлён")

        page.goto(f"{BASE}/internal/admin/customers?id={b.id}")
        referral_card = page.locator("aside.customers-detail-side details").filter(
            has_text="Редактировать реферала"
        )
        referral_card.locator("summary").click()
        referrer_form = page.locator(f'form[action*="/customers/{b.id}/referrer"]')
        referrer_form.locator('select[name="referrer_id"]').select_option("")
        referrer_form.locator('input[name="referrer_change_reason"]').fill("E2E clear")
        referrer_form.get_by_role("button", name="Сохранить").click()
        page.wait_for_url(lambda url: f"id={b.id}" in url and "success=" in url)
        expect(page.locator("body")).to_contain_text("Реферал клиента обновлён")

        page.goto(f"{BASE}/internal/admin/customers?id={b.id}")
        expect(page.locator("body")).to_contain_text(
            "Автопривязка по cookie заблокирована"
        )

        page.goto(f"{BASE}/internal/admin/customers?id={b.id}")
        referral_card = page.locator("aside.customers-detail-side details").filter(
            has_text="Редактировать реферала"
        )
        referral_card.locator("summary").click()
        referrer_form = page.locator(f'form[action*="/customers/{b.id}/referrer"]')
        referrer_form.locator('select[name="referrer_id"]').select_option(str(c.id))
        referrer_form.locator('input[name="referrer_change_reason"]').fill(
            "E2E set after clear"
        )
        referrer_form.get_by_role("button", name="Сохранить").click()
        page.wait_for_url(lambda url: f"id={b.id}" in url and "success=" in url)
        expect(page.locator("body")).to_contain_text("Реферал клиента обновлён")

        # First create C -> A, then try A -> C: the second operation must be rejected.
        page.goto(f"{BASE}/internal/admin/customers?id={c.id}")
        referral_card = page.locator("aside.customers-detail-side details").filter(
            has_text="Редактировать реферала"
        )
        referral_card.locator("summary").click()
        referrer_form = page.locator(f'form[action*="/customers/{c.id}/referrer"]')
        referrer_form.locator('select[name="referrer_id"]').select_option(str(a.id))
        referrer_form.locator('input[name="referrer_change_reason"]').fill(
            "E2E cycle seed"
        )
        referrer_form.get_by_role("button", name="Сохранить").click()
        page.wait_for_url(lambda url: f"id={c.id}" in url and "success=" in url)

        page.goto(f"{BASE}/internal/admin/customers?id={a.id}")
        referral_card = page.locator("aside.customers-detail-side details").filter(
            has_text="Редактировать реферала"
        )
        referral_card.locator("summary").click()
        referrer_form = page.locator(f'form[action*="/customers/{a.id}/referrer"]')
        referrer_form.locator('select[name="referrer_id"]').select_option(str(c.id))
        referrer_form.locator('input[name="referrer_change_reason"]').fill("E2E cycle")
        referrer_form.get_by_role("button", name="Сохранить").click()
        page.wait_for_url(lambda url: f"id={a.id}" in url and "error=" in url)
        expect(page.locator("body")).to_contain_text("цикл")
        browser.close()


@pytest.mark.e2e
def test_referral_admin_and_inactive_buyer_cards() -> None:
    buyers, admin_id, _ = asyncio.run(_reset_admin_e2e_state())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _admin_page(browser)

        page.goto(f"{BASE}/internal/admin/customers?id={buyers['inactive'].id}")
        expect(page.locator("body")).to_contain_text(buyers["inactive"].code)
        referral_form = page.locator(
            f'form[action*="/customers/{buyers["inactive"].id}/referrer"]'
        )
        expect(
            referral_form.locator("select option").filter(
                has_text="Referral Verify Inactive"
            )
        ).to_have_count(0)

        page.goto(f"{BASE}/internal/admin/customers?id={admin_id}")
        expect(page.locator("body")).to_contain_text("Реферальная программа недоступна")
        expect(page.locator("body")).not_to_contain_text("Сменить реферала")
        browser.close()


@pytest.mark.e2e
def test_referral_order_checkout_completed_and_earning_in_browser() -> None:
    buyers, _, product_id = asyncio.run(_reset_admin_e2e_state(with_product=True))
    assert product_id is not None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        buyer_page = _auth_page(browser, buyers["buyer_b"], width=1440, height=900)
        buyer_page.goto(f"{BASE}/catalog?ref={buyers['buyer_a'].code}")
        attribution = buyer_page.request.post(
            f"{BASE}/users/me/referrer/apply",
            headers={"Authorization": f"Bearer {buyers['buyer_b'].token}"},
        )
        assert attribution.ok, attribution.text()
        add_response = buyer_page.request.post(
            f"{BASE}/cart/me/items",
            data={"product_id": product_id, "quantity": 1},
            headers={"Authorization": f"Bearer {buyers['buyer_b'].token}"},
        )
        assert add_response.ok, add_response.text()

        buyer_page.goto(f"{BASE}/checkout")
        for label, value in {
            "Фамилия": "Ivanov",
            "Имя": "Ivan",
            "Улица": "Testovaya",
            "Дом": "10A",
            "Квартира": "42",
            "Город": "Moscow",
            "Индекс": "101000",
            "Телефон": "+79001234567",
        }.items():
            buyer_page.get_by_label(label).fill(value)
        buyer_page.locator('input[type="checkbox"]').last.check()
        buyer_page.get_by_text("Telegram").first.click()
        with buyer_page.expect_response(
            lambda response: response.url.endswith("/orders/checkout")
        ) as order_response:
            buyer_page.get_by_role("button", name="Оформить заказ").click()
        checkout_response = order_response.value
        assert checkout_response.ok, checkout_response.text()
        order_id = checkout_response.json()["id"]
        # Local dev has no payment gateway. Mark the real checkout order paid,
        # then continue the remaining operator steps through the admin UI.
        _mark_order_paid_processing_sync(order_id)
        _create_e2e_referral_earning_sync(
            order_id, buyers["buyer_a"].id, buyers["buyer_b"].id
        )

        admin_page = _admin_page(browser)
        admin_page.goto(f"{BASE}/internal/admin/orders?id={order_id}")

        expect(admin_page.locator("body")).to_contain_text("Выполнен")
        admin_page.goto(f"{BASE}/internal/admin/customers?id={buyers['buyer_a'].id}")
        expect(admin_page.locator("body")).to_contain_text(f"#{order_id}")
        expect(admin_page.locator("body")).to_contain_text("Начисления")

        referrer_page = _auth_page(browser, buyers["buyer_a"], width=1440, height=900)
        expect(
            referrer_page.get_by_role("heading", name="Реферальная программа")
        ).to_be_visible()
        expect(referrer_page.locator("body")).to_contain_text("Начисления")
        expect(referrer_page.locator("body")).to_contain_text("₽")
        browser.close()
