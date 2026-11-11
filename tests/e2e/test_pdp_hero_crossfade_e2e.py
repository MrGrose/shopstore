import os
from collections import Counter
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, sync_playwright

BASE = os.environ.get("REFERRAL_E2E_BASE", "http://localhost:8000")

_INSTALL = """
() => {
  window.__pdp = { snaps: [], t0: performance.now(), lastKey: null };
  const widthOf = (u) => {
    try { return new URL(u, location.origin).searchParams.get('width') || '-'; }
    catch { return '-'; }
  };
  window.__pdpSnap = (why) => {
    const frame = document.querySelector('[data-pdp-hero="frame"]');
    const preview = document.querySelector('[data-pdp-hero="preview"]');
    const hero = document.querySelector('[data-pdp-hero="image"]');
    const pulse = !!(frame && frame.querySelector('.animate-pulse'));
    const box = frame?.getBoundingClientRect();
    window.__pdp.snaps.push({
      t: Math.round(performance.now() - window.__pdp.t0),
      why,
      pulse,
      previewMounted: !!preview,
      previewW: preview ? widthOf(preview.currentSrc || preview.src) : null,
      heroMounted: !!hero,
      heroW: hero ? widthOf(hero.currentSrc || hero.src) : null,
      box: box ? { w: Math.round(box.width), h: Math.round(box.height) } : null,
    });
  };
  const obs = new MutationObserver(() => {
    const preview = document.querySelector('[data-pdp-hero="preview"]');
    const hero = document.querySelector('[data-pdp-hero="image"]');
    const frame = document.querySelector('[data-pdp-hero="frame"]');
    const pulse = !!(frame && frame.querySelector('.animate-pulse'));
    const key = [!!preview, !!hero, pulse].join(':');
    if (key !== window.__pdp.lastKey) {
      window.__pdp.lastKey = key;
      window.__pdpSnap('dom');
    }
  });
  obs.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['src', 'class'],
  });
}
"""


# Ширина Shopify/CDN из query width=.
def _cdn_width(url: str) -> str:
    return (parse_qs(urlparse(url).query).get("width") or ["-"])[0]


# Счётчик width= для shop/cdn картинок.
def _shop_widths(urls: list[str]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for url in urls:
        if "cdn/shop" not in url and "/cdn/" not in url:
            continue
        counts[_cdn_width(url)] += 1
    return dict(counts)


# Снимки hero после клика по карточке каталога.
def _click_pdp(page: Page, catalog_url: str) -> dict:
    page.goto(catalog_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#products [role='button']", timeout=30000)
    page.wait_for_timeout(300)
    page.evaluate(_INSTALL)
    imgs: list[str] = []

    # Собирает URL image-запросов после клика/навигации.
    def on_req(req) -> None:
        if req.resource_type == "image":
            imgs.append(req.url)

    page.on("request", on_req)
    page.locator("#products [role='button']").first.click()
    page.wait_for_url(lambda url: "/catalog/product/" in url, timeout=20000)
    page.wait_for_function(
        """() => {
          const frame = document.querySelector('[data-pdp-hero="frame"]');
          const preview = document.querySelector('[data-pdp-hero="preview"]');
          const hero = document.querySelector('[data-pdp-hero="image"]');
          const pulse = frame && frame.querySelector('.animate-pulse');
          const back = Array.from(document.querySelectorAll('button, a')).some(
            (el) => (el.textContent || '').trim() === 'Назад'
          );
          return !!frame && !pulse && (!!preview || (!!hero && back));
        }""",
        timeout=20000,
    )
    page.evaluate("window.__pdpSnap('after-nav')")
    page.wait_for_selector("text=Назад", timeout=20000)
    page.wait_for_selector('[data-pdp-hero="image"]', timeout=20000)
    page.wait_for_timeout(400)
    page.evaluate("window.__pdpSnap('settled')")
    diag = page.evaluate("() => window.__pdp")
    thumbs = page.locator(".product-pdp-col button img").count()
    return {
        "path": page.evaluate("() => location.pathname"),
        "thumbs": thumbs,
        "img_widths": _shop_widths(imgs),
        "diag": diag,
    }


# Deep-link PDP без catalog preview.
def _deeplink(page: Page, url: str) -> dict:
    imgs: list[str] = []

    # Собирает URL image-запросов после клика/навигации.
    def on_req(req) -> None:
        if req.resource_type == "image":
            imgs.append(req.url)

    page.on("request", on_req)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.evaluate(_INSTALL)
    page.wait_for_selector("text=Назад", timeout=20000)
    page.wait_for_selector('[data-pdp-hero="image"]', timeout=20000)
    page.wait_for_timeout(400)
    page.evaluate("window.__pdpSnap('settled')")
    return {
        "path": page.evaluate("() => location.pathname"),
        "thumbs": page.locator(".product-pdp-col button img").count(),
        "img_widths": _shop_widths(imgs),
        "diag": page.evaluate("() => window.__pdp"),
    }


# Catalog preview в том же кадре, затем hero 1400; без серого pulse.
def _assert_preview_then_hero(
    diag: dict,
    *,
    preview_width: str,
    require_preview: bool,
) -> None:
    snaps = diag.get("snaps") or []
    assert snaps, "no PDP snapshots"
    assert not any(snap.get("pulse") for snap in snaps), snaps
    live = [snap for snap in snaps if snap.get("previewMounted")]
    if require_preview:
        assert live, f"preview never mounted: {snaps!r}"
        assert any(snap.get("previewW") == preview_width for snap in live), live
    elif live:
        assert any(snap.get("previewW") == preview_width for snap in live), live
    settled = snaps[-1]
    assert settled.get("heroMounted") is True
    assert settled.get("previewMounted") is False
    assert settled.get("heroW") == "1400"
    boxes = [snap.get("box") for snap in snaps if snap.get("box")]
    if len(boxes) >= 2:
        assert boxes[0]["w"] == boxes[-1]["w"], boxes
        assert boxes[0]["h"] == boxes[-1]["h"], boxes


# Hero 1400 есть, compact-карточки 720 на desktop нет.
def _assert_desktop_widths(widths: dict[str, int]) -> None:
    assert "1400" in widths
    assert "720" not in widths


# Hero 1400 есть, desktop-карточки 560 в mini/mobile нет.
def _assert_compact_widths(widths: dict[str, int]) -> None:
    assert "1400" in widths
    assert "560" not in widths


@pytest.mark.e2e
# Desktop: cache miss/hit, gallery, back, deep-link — 560 затем 1400, без pulse.
def test_pdp_hero_crossfade_desktop_cache_and_gallery() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        miss = _click_pdp(page, f"{BASE}/catalog/padel")
        _assert_desktop_widths(miss["img_widths"])
        _assert_preview_then_hero(
            miss["diag"], preview_width="560", require_preview=True
        )

        page.go_back()
        page.wait_for_selector("#products [role='button']", timeout=20000)
        hit = _click_pdp(
            page, page.url if "/catalog/" in page.url else f"{BASE}/catalog/padel"
        )
        _assert_preview_then_hero(
            hit["diag"], preview_width="560", require_preview=False
        )
        assert "720" not in hit["img_widths"]

        product_path = miss["path"]
        page.goto(f"{BASE}/catalog/padel", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#products [role='button']", timeout=30000)
        cards = page.locator("#products [role='button']")
        gallery_path = None
        for index in range(min(cards.count(), 10)):
            page.goto(
                f"{BASE}/catalog/padel", wait_until="domcontentloaded", timeout=60000
            )
            page.wait_for_selector("#products [role='button']", timeout=30000)
            page.locator("#products [role='button']").nth(index).click()
            page.wait_for_url(lambda url: "/catalog/product/" in url, timeout=20000)
            page.wait_for_selector("text=Назад", timeout=20000)
            if page.locator(".product-pdp-col button img").count() > 1:
                gallery_path = page.evaluate("() => location.pathname")
                page.get_by_role("button", name="Следующее фото").click()
                page.wait_for_timeout(400)
                hero = page.locator("[data-pdp-hero='image']")
                src = hero.get_attribute("src") or ""
                assert "width=1400" in src
                assert page.locator("[data-pdp-hero='preview']").count() == 0
                break

        page.get_by_role("button", name="Назад").click()
        page.wait_for_url(
            lambda url: "/catalog/" in url and "/product/" not in url, timeout=20000
        )
        _click_sub = page.get_by_role("navigation", name="Подкатегории").get_by_role(
            "button", name="Обувь", exact=True
        )
        if _click_sub.count() > 0:
            _click_sub.click()
            page.wait_for_timeout(500)
        page.wait_for_selector("#products [role='button']", timeout=20000)
        other = _click_pdp(page, page.url)
        _assert_preview_then_hero(
            other["diag"], preview_width="560", require_preview=True
        )
        assert other["path"] != product_path or gallery_path

        deeplink = _deeplink(page, BASE + product_path)
        assert "720" not in deeplink["img_widths"]
        assert "1400" in deeplink["img_widths"]
        settled = (deeplink["diag"].get("snaps") or [{}])[-1]
        assert settled.get("previewMounted") is False
        assert settled.get("heroW") == "1400"

        browser.close()


@pytest.mark.e2e
# Mobile 390 и /app: 720 затем 1400, preview без серого pulse.
def test_pdp_hero_crossfade_mobile_and_miniapp() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        mobile = browser.new_context(viewport={"width": 390, "height": 844})
        page = mobile.new_page()
        miss = _click_pdp(page, f"{BASE}/catalog/padel")
        _assert_compact_widths(miss["img_widths"])
        _assert_preview_then_hero(
            miss["diag"], preview_width="720", require_preview=True
        )
        mobile.close()

        app = browser.new_context(viewport={"width": 390, "height": 844})
        page = app.new_page()
        app_miss = _click_pdp(page, f"{BASE}/app/catalog/padel")
        _assert_compact_widths(app_miss["img_widths"])
        _assert_preview_then_hero(
            app_miss["diag"], preview_width="720", require_preview=True
        )
        assert "/app/" in app_miss["path"] or "catalog/product" in app_miss["path"]
        app.close()

        browser.close()
