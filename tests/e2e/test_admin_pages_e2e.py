import os
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect, sync_playwright

from tests.e2e.conftest import load_dotenv

EXCLUDED_ADMIN_PAGES = ("dashboard", "parsing")


@dataclass(frozen=True)
class AdminE2EPage:
    page_id: str
    path: str
    ready_selector: str
    controls: tuple[str, ...]
    attached_controls: tuple[str, ...] = ()
    interact: str | None = None


ADMIN_E2E_PAGES: tuple[AdminE2EPage, ...] = (
    AdminE2EPage(
        "orders",
        "/internal/admin/orders",
        "#admin-orders-filters",
        (
            '#admin-orders-filters input[name="q"]',
            "#admin-orders-filters .admin-filter-pill",
            "[data-date-range-trigger]",
            "#admin-orders-delete-btn",
        ),
        interact="orders_status_pill",
    ),
    AdminE2EPage(
        "products",
        "/internal/admin/products",
        ".products-page-tabs",
        (
            'a.products-page-tabs__link:has-text("Список")',
            'a.products-page-tabs__link:has-text("Массовые")',
            'a.products-page-tabs__link:has-text("Бренды")',
            ".products-filter-pills .admin-filter-pill",
            "#admin-products-table",
            'a.admin-btn-pill:has-text("Новый товар")',
        ),
        attached_controls=("#admin-product-detail",),
        interact="products_tabs",
    ),
    AdminE2EPage(
        "product_new",
        "/internal/admin/products/new",
        "#admin-product-create-form",
        (
            '#admin-product-create-form input[name="title"]',
            '#admin-product-create-form input[name="is_active"]',
            "#admin-product-image-files",
            'button[form="admin-product-create-form"]',
        ),
    ),
    AdminE2EPage(
        "customers",
        "/internal/admin/customers",
        "#admin-customers-filters",
        ('#admin-customers-filters input[name="q"]',),
        interact="customers_search",
    ),
    AdminE2EPage(
        "prices",
        "/internal/admin/prices",
        ".prices-grid",
        (
            'input[name="eur_rate"]',
            'input[name="markup_multiplier"]',
            'input[name="delivery_fee_eur"]',
            'input[name="service_commission_percent"]',
            'input[name="referral_commission_percent"]',
            'form[action="/internal/admin/prices/settings"] button[type="submit"]',
            'form[action="/internal/admin/prices/refresh-rate"] button',
            'form[action="/internal/admin/prices/recalculate"] button',
        ),
    ),
    AdminE2EPage(
        "margins",
        "/internal/admin/margins",
        ".margins-sports",
        (
            ".margins-sports .admin-filter-pill",
            ".margin-group-card",
            ".margin-fallback",
        ),
        interact="margins_sport_pill",
    ),
    AdminE2EPage(
        "promos",
        "/internal/admin/promos",
        ".promos-layout",
        (
            ".promos-toolbar .admin-filter-pill",
            ".promos-create-card",
            ".promos-help-card",
            'input[name="code"]',
            'select[name="discount_type"]',
            'select[name="usage_mode"]',
            'input[name="active_to"]',
            ".promos-form__actions button",
        ),
        interact="promos_filter",
    ),
    AdminE2EPage(
        "support",
        "/internal/admin/support",
        ".support-page",
        (".orders-filters__pills .admin-filter-pill",),
        attached_controls=("#admin-support-delete-btn",),
        interact="support_pill",
    ),
    AdminE2EPage(
        "finance",
        "/internal/admin/finance",
        "#admin-finance-filters",
        (
            ".finance-presets .admin-filter-pill",
            ".finance-groups .admin-filter-pill",
            "[data-date-range-trigger]",
            'a.admin-btn-pill:has-text("Скачать CSV")',
        ),
        interact="finance_preset",
    ),
)


# Логин в админку через форму.
def playwright_admin_login(page: Page, base: str) -> None:
    login = os.environ["ADMIN_PANEL_LOGIN"]
    password = os.environ["ADMIN_PANEL_PASSWORD"]
    page.goto(f"{base}/internal/admin/login")
    page.fill("#username", login)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(
        lambda url: "/internal/admin/login" not in url,
        timeout=15000,
    )


# Ждёт HTMX-таблицу заказов или empty-state.
def _wait_orders_table(page: Page) -> None:
    page.wait_for_selector(
        "#admin-orders-table .orders-table-wrap, #admin-orders-table .orders-empty",
        timeout=15000,
    )


# Ждёт HTMX-таблицу товаров или empty-state.
def _wait_products_table(page: Page) -> None:
    page.wait_for_selector(
        "#admin-products-search-input, #admin-products-table .empty.muted",
        timeout=15000,
    )


# Проверяет видимость контролов на странице.
def _assert_controls_visible(
    page: Page, selectors: tuple[str, ...], page_id: str
) -> None:
    missing: list[str] = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="attached", timeout=10000)
        except Exception:
            missing.append(selector)
            continue
        if not locator.is_visible():
            missing.append(f"{selector} (hidden)")
    assert not missing, f"{page_id}: missing controls {missing}"


# Проверяет наличие контролов в DOM (могут быть скрыты до действия пользователя).
def _assert_controls_attached(
    page: Page, selectors: tuple[str, ...], page_id: str
) -> None:
    missing: list[str] = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="attached", timeout=10000)
        except Exception:
            missing.append(selector)
    assert not missing, f"{page_id}: missing attached controls {missing}"


# Безопасные клики по фильтрам (без submit форм с сохранением).
def _interact_page(page: Page, page_id: str, kind: str | None) -> None:
    if kind == "orders_status_pill":
        _wait_orders_table(page)
        pill = page.locator("#admin-orders-filters .admin-filter-pill").nth(1)
        if pill.is_visible():
            pill.click()
            page.wait_for_timeout(400)
            _wait_orders_table(page)
        trigger = page.locator("[data-date-range-trigger]").first
        if trigger.is_visible():
            trigger.click()
            expect(page.locator("[data-date-range-popover]").first).to_be_visible()
            page.keyboard.press("Escape")
        return

    if kind == "products_tabs":
        _wait_products_table(page)
        page.locator('a.products-page-tabs__link:has-text("Массовые")').click()
        expect(page.locator("#admin-products-group-top-select")).to_be_visible()
        page.locator('a.products-page-tabs__link:has-text("Бренды")').click()
        expect(page.locator("#admin-products-brands-search-input")).to_be_visible()
        page.locator('a.products-page-tabs__link:has-text("Список")').click()
        _wait_products_table(page)
        sort = page.locator("#admin-products-sort-select")
        if sort.is_visible():
            options = sort.locator("option")
            if options.count() > 1:
                sort.select_option(index=1)
                page.wait_for_timeout(400)
        return

    if kind == "customers_search":
        page.wait_for_selector(
            "#admin-customers-table .customers-table-wrap, "
            "#admin-customers-table .customers-empty:not(.customers-empty--compact)",
            timeout=15000,
        )
        search = page.locator('#admin-customers-filters input[name="q"]')
        if search.is_visible():
            search.fill("1")
            page.wait_for_timeout(400)
        return

    if kind == "margins_sport_pill":
        pills = page.locator(".margins-sports .admin-filter-pill")
        if pills.count() > 1:
            pills.nth(1).click()
            page.wait_for_load_state("networkidle")
        return

    if kind == "support_pill":
        pills = page.locator(".orders-filters__pills .admin-filter-pill")
        if pills.count() > 1:
            pills.nth(1).click()
            page.wait_for_load_state("networkidle")
        return

    if kind == "finance_preset":
        preset = page.locator(".finance-presets .admin-filter-pill").first
        if preset.is_visible():
            preset.click()
            page.wait_for_load_state("networkidle")
        group = page.locator(".finance-groups .admin-filter-pill").nth(1)
        if group.is_visible():
            group.click()
            page.wait_for_load_state("networkidle")
        return

    if kind == "promos_filter":
        pill = page.locator(".promos-toolbar .admin-filter-pill").nth(1)
        if pill.is_visible():
            pill.click()
            page.wait_for_load_state("networkidle")
        expect(page.locator(".promos-help-card")).to_be_visible()
        expect(page.locator("text=Справка по типам")).to_be_visible()
        return

    if kind is not None:
        raise AssertionError(f"{page_id}: unknown interact kind {kind!r}")


# Прогон одной admin-страницы в браузере.
def _check_admin_page(page: Page, base: str, spec: AdminE2EPage) -> None:
    page.goto(f"{base}{spec.path}")
    page.wait_for_selector(spec.ready_selector, timeout=15000)
    _assert_controls_visible(page, spec.controls, spec.page_id)
    _assert_controls_attached(page, spec.attached_controls, spec.page_id)
    _interact_page(page, spec.page_id, spec.interact)


# E2E: все list-страницы админки (кроме dashboard/parsing).
def run_admin_pages_e2e(base: str) -> list[str]:
    load_dotenv()
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            playwright_admin_login(page, base)
            for spec in ADMIN_E2E_PAGES:
                try:
                    _check_admin_page(page, base, spec)
                    print(f"PASS {spec.page_id}")
                except Exception as exc:
                    print(f"FAIL {spec.page_id}: {exc}")
                    failures.append(spec.page_id)
        finally:
            browser.close()
    return failures


@pytest.mark.e2e
def test_admin_pages_controls_e2e(e2e_base_url: str) -> None:
    failed = run_admin_pages_e2e(e2e_base_url)
    assert not failed, f"failed pages: {', '.join(failed)}"


@pytest.mark.e2e
def test_admin_excluded_pages_not_in_e2e_suite() -> None:
    covered = {spec.page_id for spec in ADMIN_E2E_PAGES}
    for page_id in EXCLUDED_ADMIN_PAGES:
        assert page_id not in covered


if __name__ == "__main__":
    load_dotenv()
    base = os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
    raise SystemExit(0 if not run_admin_pages_e2e(base) else 1)
