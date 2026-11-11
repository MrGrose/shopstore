import logging
import re

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PopupHandler:
    _COOKIE_ACCEPT_NAMES = (
        "Accept All Cookies",
        "Accept all",
        "Allow all",
        "Alle akzeptieren",
        "Accept",
    )

    # Клик по принять cookies.
    async def dismiss_cookie_consent_if_present(self, page: Page) -> None:
        for label in self._COOKIE_ACCEPT_NAMES:
            try:
                btn = page.get_by_role(
                    "button", name=re.compile(re.escape(label), re.I)
                )
                if await btn.count() == 0:
                    continue
                first = btn.first
                if await first.is_visible(timeout=2500):
                    await first.click(timeout=8000)
                    await page.wait_for_timeout(600)
                    return
            except Exception:
                continue
        for sel in (
            "#onetrust-accept-btn-handler",
            "button#onetrust-accept-btn-handler",
            '[id*="cookie"] button[class*="accept" i]',
        ):
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible(timeout=1500):
                    await loc.click(timeout=8000)
                    await page.wait_for_timeout(600)
                    return
            except Exception:
                continue

    # Модалка остаться на сайте.
    async def dismiss_geo_redirect_modal_if_present(self, page: Page) -> None:
        for pat in (
            re.compile(r"No,?\s*thanks!?", re.I),
            re.compile(r"No thanks", re.I),
            re.compile(r"Ei kiitos", re.I),
        ):
            try:
                btn = page.get_by_role("button", name=pat)
                if await btn.count() == 0:
                    continue
                first = btn.first
                if await first.is_visible(timeout=2500):
                    await first.click(timeout=15_000)
                    await page.wait_for_timeout(800)
                    return
            except Exception:
                continue

    # Баннер #geoip-banner: Nein danke / крестик / Escape / remove из DOM.
    async def dismiss_geoip_banner_if_present(self, page: Page) -> None:
        try:
            has_id = await page.evaluate(
                "() => !!document.getElementById('geoip-banner')"
            )
        except Exception:
            has_id = False

        if not has_id:
            try:
                loc = page.locator("button.geoip-no-btn").first
                if await loc.count() and await loc.is_visible(timeout=600):
                    await loc.click(timeout=3000, force=True)
                    await page.wait_for_timeout(300)
            except Exception:
                pass
            return

        banner = page.locator("#geoip-banner")
        for sel in (
            "#geoip-banner button.geoip-no-btn",
            '#geoip-banner button[aria-label*="Close" i]',
            '#geoip-banner button[aria-label*="Sluiten" i]',
            '#geoip-banner [data-dismiss="modal"]',
            "#geoip-banner .modal__close",
        ):
            try:
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible(timeout=400):
                    await btn.click(timeout=5000)
                    await page.wait_for_timeout(400)
                    if not await banner.first.is_visible(timeout=600):
                        logger.debug("Гео-баннер закрыт (клик)")
                        return
            except Exception:
                continue
        try:
            btn = page.get_by_role("button", name=re.compile(r"Nein,?\s*danke", re.I))
            if await btn.count() and await btn.first.is_visible(timeout=400):
                await btn.first.click(timeout=5000)
                await page.wait_for_timeout(400)
                if not await banner.first.is_visible(timeout=600):
                    logger.debug("Гео-баннер закрыт (клик)")
                    return
        except Exception:
            pass
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            await page.evaluate(
                """
                () => { const el = document.getElementById('geoip-banner');
                if (el) el.remove(); }
                """
            )
            logger.debug("Гео-баннер убран из DOM")
        except Exception as exc:
            logger.warning("Не удалось убрать geoip-banner: %s", exc)


# Синхронное закрытие баннера cookies.
def dismiss_cookie_consent_if_present_sync(page) -> None:
    for label in PopupHandler._COOKIE_ACCEPT_NAMES:
        try:
            btn = page.get_by_role("button", name=re.compile(re.escape(label), re.I))
            if btn.count() == 0:
                continue
            first = btn.first
            if first.is_visible(timeout=2500):
                first.click(timeout=8000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue
    for sel in (
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        '[id*="cookie"] button[class*="accept" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1500):
                loc.click(timeout=8000)
                page.wait_for_timeout(600)
                return
        except Exception:
            continue


# Синхронное закрытие модалки гео-редиректа (No thanks).
def dismiss_geo_redirect_modal_if_present_sync(page) -> None:
    for pat in (
        re.compile(r"No,?\s*thanks!?", re.I),
        re.compile(r"No thanks", re.I),
        re.compile(r"Ei kiitos", re.I),
    ):
        try:
            btn = page.get_by_role("button", name=pat)
            if btn.count() == 0:
                continue
            first = btn.first
            if first.is_visible(timeout=2500):
                first.click(timeout=15_000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue


# Синхронное снятие #geoip-banner (логин и _prepare_page).
def dismiss_geoip_banner_if_present_sync(page) -> None:
    try:
        has_id = page.evaluate("() => !!document.getElementById('geoip-banner')")
    except Exception:
        has_id = False

    if not has_id:
        try:
            loc = page.locator("button.geoip-no-btn").first
            if loc.count() and loc.is_visible(timeout=600):
                loc.click(timeout=3000, force=True)
                page.wait_for_timeout(300)
        except Exception:
            pass
        return

    banner = page.locator("#geoip-banner")
    for sel in (
        "#geoip-banner button.geoip-no-btn",
        '#geoip-banner button[aria-label*="Close" i]',
        '#geoip-banner button[aria-label*="Sluiten" i]',
        '#geoip-banner [data-dismiss="modal"]',
        "#geoip-banner .modal__close",
    ):
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible(timeout=400):
                btn.click(timeout=5000)
                page.wait_for_timeout(400)
                if not banner.first.is_visible(timeout=600):
                    logger.debug("Гео-баннер закрыт (клик)")
                    return
        except Exception:
            continue
    try:
        btn = page.get_by_role("button", name=re.compile(r"Nein,?\s*danke", re.I))
        if btn.count() and btn.first.is_visible(timeout=400):
            btn.first.click(timeout=5000)
            page.wait_for_timeout(400)
            if not banner.first.is_visible(timeout=600):
                logger.debug("Гео-баннер закрыт (клик)")
                return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        page.evaluate(
            """
            () => { const el = document.getElementById('geoip-banner');
            if (el) el.remove(); }
            """
        )
        logger.debug("Гео-баннер убран из DOM")
    except Exception as exc:
        logger.warning("Не удалось убрать geoip-banner: %s", exc)


# Закрытие модалки Shop Pay после первого шага Sign in.
def dismiss_shop_pay_modal_if_present_sync(page) -> None:
    for sel in (
        '[role="dialog"] button[aria-label*="lose" i]',
        'button[aria-label*="lose" i]',
        '[class*="shop"] button[aria-label*="lose" i]',
    ):
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=600):
                loc.click(timeout=4000)
                page.wait_for_timeout(400)
                logger.info("Закрыто окно Shop Pay")
                return
        except Exception:
            continue
