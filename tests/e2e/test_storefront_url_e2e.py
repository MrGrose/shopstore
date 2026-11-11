"""Browser E2E for storefront URL cleanup (web + mini app + referral).

Requires local API with built storefront on http://localhost:8000:
    uv run pytest tests/e2e/test_storefront_url_e2e.py -m e2e -q
"""

import os
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")


def _open(page: Page, path: str) -> None:
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
    page.wait_for_timeout(400)


def _referral_cookie(context) -> str | None:
    for item in context.cookies(BASE):
        if item["name"] == "referral_code":
            return item["value"]
    return None


def _url_has_rackets(url: str) -> bool:
    return "section=rackets" in url or "sub=rackets" in url


def _url_has_shoes(url: str) -> bool:
    return "section=shoes" in url or "sub=shoes" in url


def _click_sub_rackets(page: Page, *, desktop: bool) -> None:
    if desktop:
        page.get_by_role("navigation", name="Подкатегории").get_by_role(
            "button", name="Ракетки", exact=True
        ).click()
    else:
        page.get_by_role("button", name="Ракетки", exact=True).click()
    page.wait_for_timeout(600)


def _expect_rackets_breadcrumb(page: Page) -> None:
    expect(page.get_by_role("navigation", name="Раздел каталога")).to_contain_text(
        "Ракетки"
    )


@pytest.mark.e2e
def test_web_home_and_catalog_routes() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/")
        expect(page.get_by_role("link", name="Открыть товары")).to_be_visible()
        assert urlparse(page.url).path in {"", "/"}

        _open(page, "/catalog")
        expect(page.get_by_text("Все товары")).to_be_visible()
        assert "/catalog/all" not in page.url

        _open(page, "/catalog/all")
        page.wait_for_url(lambda url: "/catalog/all" not in url, timeout=5000)
        assert page.url.rstrip("/").endswith("/catalog")

        browser.close()


@pytest.mark.e2e
def test_web_referral_capture_on_home_and_legacy_catalog() -> None:
    code = "urlmatrix42"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        _open(page, f"/?ref={code}")
        assert _referral_cookie(context) == code

        _open(page, f"/catalog?ref=legacy{code}")
        assert _referral_cookie(context) == f"legacy{code}"

        browser.close()


@pytest.mark.e2e
def test_ref_alias_server_redirect_lands_on_home_with_ref() -> None:
    alias = "urlmatrix-alias"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        _open(page, f"/ref/{alias}")
        assert "?ref=" in page.url
        assert alias in page.url
        assert _referral_cookie(context) == alias

        browser.close()


@pytest.mark.e2e
def test_catalog_legacy_and_mapping_category_urls() -> None:
    """Phase 8.6: legacy and mapping category URLs render catalog."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel?sub=rackets")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert "sub=rackets" in page.url or "section=rackets" in page.url

        _open(page, "/catalog/padel?section=rackets&node=pro")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert "section=rackets" in page.url or "sub=rackets" in page.url

        browser.close()


@pytest.mark.e2e
def test_miniapp_catalog_legacy_and_mapping_category_urls() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        )

        _open(page, "/app/catalog/padel?sub=rackets")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()

        _open(page, "/app/catalog/padel?section=rackets")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()

        browser.close()


@pytest.mark.e2e
def test_miniapp_catalog_entry_and_legacy_all_alias() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        )

        _open(page, "/app/")
        page.wait_for_url(
            lambda url: url.rstrip("/").endswith("/app/catalog"), timeout=5000
        )
        expect(
            page.get_by_label("Навигация Mini App").get_by_role("link", name="Каталог")
        ).to_be_visible()

        _open(page, "/app/catalog/all")
        page.wait_for_url(lambda url: "/catalog/all" not in url, timeout=5000)
        assert page.url.rstrip("/").endswith("/app/catalog")

        browser.close()


@pytest.mark.e2e
def test_catalog_legacy_sub_and_category_type_urls() -> None:
    """Phase 8.6: legacy sub + category_type renders catalog."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel?sub=rackets&category_type=pro")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert _url_has_rackets(page.url)

        browser.close()


@pytest.mark.e2e
def test_catalog_legacy_type_alias_param() -> None:
    """Phase 8.6: legacy type alias renders catalog."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel?sub=rackets&type=pro")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert _url_has_rackets(page.url)

        browser.close()


@pytest.mark.e2e
def test_catalog_tennis_and_running_legacy_sub_urls() -> None:
    """Phase 8.6: other sports accept legacy sub URLs."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/tennis?sub=rackets")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert "rackets" in page.url

        _open(page, "/catalog/running?sub=shoes")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert "shoes" in page.url

        browser.close()


@pytest.mark.e2e
def test_miniapp_catalog_legacy_category_type_url() -> None:
    """Phase 8.6: mini app legacy category_type renders catalog."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        )

        _open(page, "/app/catalog/padel?sub=rackets&category_type=pro")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible()
        assert _url_has_rackets(page.url)

        browser.close()


@pytest.mark.e2e
def test_web_catalog_sub_click_sets_url_and_breadcrumb() -> None:
    """E1: one click on sub-category writes URL and updates breadcrumb."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel")
        _click_sub_rackets(page, desktop=True)
        assert _url_has_rackets(page.url)
        _expect_rackets_breadcrumb(page)

        browser.close()


@pytest.mark.e2e
def test_miniapp_catalog_sub_click_sets_url_and_breadcrumb() -> None:
    """E11 click: mini app sub pill writes mapping URL."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        )

        _open(page, "/app/catalog/padel")
        _click_sub_rackets(page, desktop=False)
        assert _url_has_rackets(page.url)
        _expect_rackets_breadcrumb(page)

        browser.close()


@pytest.mark.e2e
def test_web_catalog_product_back_preserves_sub_filters() -> None:
    """E7: product open + back keeps section/sub filters from URL."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel")
        _click_sub_rackets(page, desktop=True)
        assert _url_has_rackets(page.url)

        product = page.locator("#products [role='button']").first
        expect(product).to_be_visible(timeout=10000)
        product.click()
        page.wait_for_url(lambda url: "/catalog/product/" in url, timeout=10000)

        page.get_by_role("button", name="Назад").click()
        page.wait_for_url(lambda url: "/catalog/padel" in url, timeout=10000)
        assert _url_has_rackets(page.url)
        _expect_rackets_breadcrumb(page)

        browser.close()


@pytest.mark.e2e
def test_web_catalog_sub_change_after_load_more() -> None:
    """E5: changing sub after paging resets URL to the new section."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel")
        _click_sub_rackets(page, desktop=True)
        assert _url_has_rackets(page.url)

        load_more = page.get_by_role("button", name="ПОКАЗАТЬ ЕЩЁ")
        if load_more.is_visible(timeout=3000):
            load_more.click()
            page.wait_for_timeout(800)

        sub_nav = page.get_by_role("navigation", name="Подкатегории")
        other_sub = sub_nav.get_by_role("button", name="Обувь", exact=True)
        if not other_sub.is_visible(timeout=3000):
            other_sub = (
                sub_nav.get_by_role("button").filter(has_not_text="Ракетки").first
            )
        other_sub.click()
        page.wait_for_timeout(600)

        assert "section=shoes" in page.url or "sub=shoes" in page.url
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_contain_text(
            "Обувь"
        )

        browser.close()


@pytest.mark.e2e
def test_catalog_tab_focus_refreshes_meta() -> None:
    """E6: returning to tab triggers catalog meta/navigation refresh."""
    tracked: list[str] = []

    def track_catalog_meta(route) -> None:
        url = route.request.url
        if "/catalog/navigation" in url or "/products/subcategories" in url:
            tracked.append(url)
        route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", track_catalog_meta)

        _open(page, "/catalog/padel")
        _click_sub_rackets(page, desktop=True)
        page.wait_for_timeout(800)
        baseline = len(tracked)

        page.evaluate(
            """
            async () => {
              let state = document.visibilityState;
              Object.defineProperty(document, "visibilityState", {
                configurable: true,
                get() { return state; },
              });
              state = "hidden";
              document.dispatchEvent(new Event("visibilitychange"));
              await new Promise((resolve) => setTimeout(resolve, 300));
              state = "visible";
              document.dispatchEvent(new Event("visibilitychange"));
            }
            """
        )
        page.wait_for_timeout(1200)

        assert len(tracked) > baseline

        browser.close()


@pytest.mark.e2e
def test_catalog_navigation_down_taxonomy_fallback() -> None:
    """E8: when navigation API fails, taxonomy breadcrumbs and sub-nav still work."""

    def block_navigation(route) -> None:
        if "/catalog/navigation" in route.request.url:
            route.fulfill(
                status=503, content_type="application/json", body='{"detail":"down"}'
            )
            return
        route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/*", block_navigation)

        _open(page, "/catalog/padel?section=rackets")
        expect(page.get_by_role("navigation", name="Подкатегории")).to_be_visible()
        _expect_rackets_breadcrumb(page)
        assert _url_has_rackets(page.url)

        browser.close()


@pytest.mark.e2e
def test_web_catalog_open_product_passes_variant_preset_to_pdp() -> None:
    """Catalog size filter is copied to PDP URL when opening a product."""
    preset_size = "43"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, f"/catalog/padel?section=shoes&size={preset_size}")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible(
            timeout=10000
        )

        product = page.locator("#products [role='button']").first
        expect(product).to_be_visible(timeout=10000)
        product.click()
        page.wait_for_url(lambda url: "/catalog/product/" in url, timeout=10000)
        assert f"size={preset_size}" in page.url

        browser.close()


@pytest.mark.e2e
def test_web_catalog_facet_reset_keeps_section_and_search_q() -> None:
    """Facet reset clears brand but keeps section and q in the URL."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel?section=rackets&brand=nike&q=e2efilters")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible(
            timeout=10000
        )

        reset_btn = (
            page.locator('h3:has-text("Фильтры")')
            .locator("..")
            .get_by_role("button", name="Сбросить")
        )
        expect(reset_btn).to_be_visible(timeout=10000)
        reset_btn.click()
        page.wait_for_timeout(600)

        assert _url_has_rackets(page.url)
        assert "q=e2efilters" in page.url
        assert "brand=nike" not in page.url

        browser.close()


@pytest.mark.e2e
def test_web_navbar_search_preserves_catalog_filters() -> None:
    """Navbar search on a catalog listing keeps section/size filters and sets q."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, "/catalog/padel?section=shoes&size=43")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible(
            timeout=10000
        )

        page.get_by_role("button", name="Поиск").click()
        search_input = page.get_by_placeholder("Название, бренд, категория, ID или SKU")
        expect(search_input).to_be_visible()
        search_input.fill("bullpadel")
        search_input.press("Enter")
        page.wait_for_timeout(600)

        assert "/catalog/padel" in page.url
        assert _url_has_shoes(page.url)
        assert "size=43" in page.url
        assert "q=bullpadel" in page.url

        browser.close()


@pytest.mark.e2e
def test_web_catalog_color_opaque_value_preserved_in_url() -> None:
    """Compound color in URL stays opaque (comma must not split to black)."""
    compound = "black, black"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        _open(page, f"/catalog/padel?section=shoes&color={compound}")
        expect(page.get_by_role("navigation", name="Раздел каталога")).to_be_visible(
            timeout=10000
        )
        page.wait_for_timeout(600)

        color_values = parse_qs(urlparse(page.url).query).get("color", [])
        assert color_values, page.url
        assert color_values[0] == compound

        browser.close()
