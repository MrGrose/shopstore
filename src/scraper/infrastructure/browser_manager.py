import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.sync_api import Browser as SyncBrowser
from playwright.sync_api import BrowserContext as SyncBrowserContext
from playwright.sync_api import sync_playwright

from src.scraper.config.config import ParseConfig
from src.scraper.config.settings import load_settings

from .popup_handler import (
    dismiss_cookie_consent_if_present_sync,
    dismiss_geo_redirect_modal_if_present_sync,
    dismiss_geoip_banner_if_present_sync,
    dismiss_shop_pay_modal_if_present_sync,
)
from .session_paths import DEFAULT_STORAGE_STATE_PATH, storage_state_search_paths

logger = logging.getLogger(__name__)

_SCRAPER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_USER_DATA_DIR = _SCRAPER_DIR / ".playwright_profile"

_PERSISTENT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
]


# Добавляет схему для Playwright, если в env только host:port.
def _normalize_proxy_server_url(entry: str) -> str:
    e = entry.strip()
    if not e:
        return ""
    low = e.lower()
    if low.startswith(("http://", "https://", "socks5://")):
        return e
    return f"http://{e}"


# Собирает список конфигов Playwright proxy:
# - один URL (или host:port);
# - несколько endpoint через запятую в server при пустом ports_csv;
# - один хост в server + SCRAPER_PROXY_PORTS=8001,8002 (только цифры).
def build_proxy_pool(
    server: str,
    ports_csv: str,
    username: str,
    password: str,
) -> list[dict[str, str]]:
    base_server = server.strip()
    if not base_server:
        return []
    u = username.strip()
    p = password.strip()

    def _pack(srv: str) -> dict[str, str]:
        proxy: dict[str, str] = {"server": srv}
        if u:
            proxy["username"] = u
        if p:
            proxy["password"] = p
        return proxy

    raw_ports = ports_csv.strip()

    if "," in base_server and not raw_ports:
        out: list[dict[str, str]] = []
        for piece in base_server.split(","):
            norm = _normalize_proxy_server_url(piece)
            if not norm:
                continue
            if not urlparse(norm).hostname:
                continue
            out.append(_pack(norm))
        return out

    base_norm = _normalize_proxy_server_url(base_server)
    if not raw_ports:
        return [_pack(base_norm)] if base_norm else []

    parsed = urlparse(base_norm)
    host = parsed.hostname
    if not host:
        return [_pack(base_norm)]

    valid_ports: list[str] = []
    for item in raw_ports.split(","):
        port = item.strip()
        if port.isdigit():
            valid_ports.append(port)
    if not valid_ports:
        return [_pack(base_norm)]

    scheme = parsed.scheme or "http"
    candidates: list[dict[str, str]] = []
    for port in valid_ports:
        srv = urlunparse((scheme, f"{host}:{port}", "", "", "", ""))
        candidates.append(_pack(srv))
    return candidates


# Lane: один egress на все replicas. Hash worker_name и PROXY_WORKER_SLOT не используем.
def resolve_proxy_worker_slot(pool_size: int) -> int:
    if pool_size > 1:
        logger.warning(
            "Прокси-пул size=%s: lane берёт только первый endpoint, "
            "SCRAPER_PROXY_PORTS и SCRAPER_PROXY_WORKER_SLOT игнорируются",
            pool_size,
        )
    return 0


# Пул из основных SCRAPER_PROXY_* (пустой server → без прокси).
def _build_proxy_configs(env_settings) -> list[dict[str, str]]:
    return build_proxy_pool(
        env_settings.proxy_server,
        env_settings.proxy_ports,
        env_settings.proxy_username,
        env_settings.proxy_password,
    )


# Пул для финального прогона упавших страниц листинга
def build_recovery_proxy_pool(env_settings) -> list[dict[str, str]]:
    base = env_settings.recovery_proxy_server.strip()
    if not base:
        return []
    user = env_settings.recovery_proxy_username.strip() or (
        env_settings.proxy_username.strip()
    )
    pwd = env_settings.recovery_proxy_password.strip() or (
        env_settings.proxy_password.strip()
    )
    ports = env_settings.recovery_proxy_ports.strip() or (
        env_settings.proxy_ports.strip()
    )
    return build_proxy_pool(base, ports, user, pwd)


# Async Chromium для парсинга и sync Playwright для login.py / экспорт storage_state.
class BrowserManager:
    def __init__(self, config: ParseConfig):
        self.config = config
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._async_playwright: Playwright | None = None
        self._proxy_pool: list[dict[str, str]] = []
        self._active_proxy: dict[str, str] | None = None
        self._storage_state: str | dict = {}
        self._uses_persistent_context = False

    # Путь к JSON Playwright storage_state или None (гость / файл отсутствует).
    def _resolve_storage_state(self) -> str | None:
        if self.config.storage_state_path:
            p = Path(self.config.storage_state_path)
            return str(p) if p.is_file() else None
        if not self.config.use_storage_state_if_exists:
            return None
        for candidate in storage_state_search_paths():
            if candidate.is_file():
                return str(candidate)
        return None

    def _resolve_persistent_profile(self) -> Path | None:
        profile = self._persistent_user_data_dir()
        return profile if profile.is_dir() else None

    # Текст ошибки, если require_storage_state, а файла нет.
    def _missing_storage_state_detail(self) -> str:
        if self.config.storage_state_path:
            p = Path(self.config.storage_state_path)
            return f"storage_state_path={p} - файла нет или он не читается."
        if not self.config.use_storage_state_if_exists:
            return (
                "use_storage_state_if_exists=False и storage_state_path не задан "
                "контекст без сохранённой сессии."
            )
        paths = ", ".join(str(p) for p in storage_state_search_paths())
        profile = self._persistent_user_data_dir()
        return f"нет JSON storage_state: {paths}; persistent profile: {profile}"

    # Старт Playwright, launch Chromium, new_context с куками
    # из storage_state при наличии.
    # proxy_pool: явный пул (например recovery); None — из SCRAPER_PROXY_* в .env.
    async def launch_browser(
        self,
        *,
        proxy_pool: list[dict[str, str]] | None = None,
    ) -> BrowserContext:
        self._async_playwright = await async_playwright().start()
        hl = self.config.headless
        env = load_settings()
        ch = (env.playwright_channel or "").strip() or None
        self._proxy_pool = (
            list(proxy_pool) if proxy_pool is not None else _build_proxy_configs(env)
        )
        slot = resolve_proxy_worker_slot(len(self._proxy_pool))
        self._active_proxy = self._proxy_for_slot(slot)
        state = self._resolve_storage_state()
        persistent_profile = None if state else self._resolve_persistent_profile()
        # Без channel - встроенный Chromium Playwright;
        # для persistent profile лучше тот же Chrome, что у ручной сессии.
        if ch is None and (persistent_profile or not hl):
            ch = "chrome"
        launch_base_kw: dict = {"headless": hl}
        if ch:
            launch_base_kw["channel"] = ch

        logger.info(
            "Парсинг: без_окна=%s, канал=%s, прокси_пул=%s",
            hl,
            ch or "bundled-chromium",
            len(self._proxy_pool),
        )
        if state:
            logger.info("Сессия: загружен storage_state из %s", state)
        elif persistent_profile:
            proxy = self._active_proxy
            persistent_kw = {**launch_base_kw, "args": _PERSISTENT_ARGS}
            if proxy:
                persistent_kw["proxy"] = proxy
            self.context = (
                await self._async_playwright.chromium.launch_persistent_context(
                    str(persistent_profile),
                    **persistent_kw,
                )
            )
            self._uses_persistent_context = True
            logger.info("Сессия: постоянный профиль %s", persistent_profile)
            return self.context
        elif self.config.require_storage_state:
            raise RuntimeError(
                "Требуется файл сессии (require_storage_state=True), но "
                + self._missing_storage_state_detail()
            )
        else:
            logger.warning(
                "Сессия: не найден JSON storage_state (искали: %s). Парсинг как гость."
            )
        self._storage_state = state or {}
        self.browser = await self._async_playwright.chromium.launch(**launch_base_kw)
        self.context = await self.new_context_for_slot(slot)
        return self.context

    # Возвращает прокси для слота (round-robin по списку портов).
    def _proxy_for_slot(self, slot: int) -> dict[str, str] | None:
        if not self._proxy_pool:
            return None
        return self._proxy_pool[slot % len(self._proxy_pool)]

    # Playwright proxy текущего context, или None если direct.
    def active_proxy(self) -> dict[str, str] | None:
        return self._active_proxy

    # True, если включён прокси-пул и требуется отдельный context под слот.
    def has_proxy_pool(self) -> bool:
        return bool(self._proxy_pool)

    # Создаёт новый BrowserContext с прокси по номеру слота.
    async def new_context_for_slot(self, slot: int) -> BrowserContext:
        if self._uses_persistent_context and self.context is not None:
            if slot:
                logger.warning("Постоянный профиль не поддерживает proxy slot=%s", slot)
            return self.context
        if self.browser is None:
            raise RuntimeError("Browser не запущен. Сначала вызовите launch_browser().")
        proxy = self._proxy_for_slot(slot)
        self._active_proxy = proxy
        ctx_kwargs: dict = {"storage_state": self._storage_state}
        if proxy:
            ctx_kwargs["proxy"] = proxy
        context = await self.browser.new_context(**ctx_kwargs)
        if proxy:
            logger.info("Контекст slot=%s через прокси=%s", slot, proxy.get("server"))
        return context

    # Создаёт BrowserContext без прокси (для прямых запросов PDP).
    async def new_context_without_proxy(self) -> BrowserContext:
        if self._uses_persistent_context and self.context is not None:
            return self.context
        if self.browser is None:
            raise RuntimeError("Browser не запущен. Сначала вызовите launch_browser().")
        context = await self.browser.new_context(storage_state=self._storage_state)
        logger.info("Контекст без прокси для PDP создан")
        return context

    # Закрытие context, browser и остановка драйвера Playwright.
    async def close_browser(self):
        if self.context:
            await self.context.close()
            self.context = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self._async_playwright:
            await self._async_playwright.stop()
            self._async_playwright = None
        self._uses_persistent_context = False

    # Синхронный вход: .env, форма логина, Russia, запись storage_state в out.
    # Браузер всегда с окном (headless=False).
    def run_login_and_save_state(
        self,
        *,
        state_path: Path | None = None,
        user_data_dir: Path | None = None,
        use_persistent_profile: bool = True,
        manual_fallback: bool = True,
        browser_channel: str | None = None,
        connect_cdp_url: str | None = None,
    ) -> Path:
        env = load_settings()
        email, password = env.email.strip(), env.password.strip()
        if not email or not password:
            raise ValueError(
                "В .env задайте EMAIL и PASSWORD (или LOGIN_EMAIL / LOGIN_PASSWORD)"
            )

        base = self.config.base_url
        login_url = f"{base}/account/login"
        configured = self.config.storage_state_path
        out = Path(state_path or configured or DEFAULT_STORAGE_STATE_PATH)
        out.parent.mkdir(parents=True, exist_ok=True)

        profile = Path(user_data_dir or self._persistent_user_data_dir())
        profile.mkdir(parents=True, exist_ok=True)

        channel = (browser_channel or env.playwright_channel or "").strip() or None
        proxies = _build_proxy_configs(env) if env.login_use_proxy else []
        proxy = proxies[0] if proxies else None

        logger.info("База: %s", base)
        logger.info("Экспорт storage_state: %s", out)
        logger.info(
            "Постоянный профиль: %s (постоянный=%s)", profile, use_persistent_profile
        )
        if channel:
            logger.info("Канал браузера: %s", channel)
        logger.info("Прокси для логина: %s", proxy.get("server") if proxy else "off")

        browser: SyncBrowser | None = None
        context: SyncBrowserContext | None = None

        with sync_playwright() as p:
            try:
                if connect_cdp_url:
                    try:
                        browser = p.chromium.connect_over_cdp(connect_cdp_url.strip())
                        if not browser.contexts:
                            raise RuntimeError(
                                "CDP подключён, но контексты не найдены. "
                                "Откройте вкладку в Chrome и повторите."
                            )
                        context = browser.contexts[0]
                        page = context.pages[0] if context.pages else context.new_page()
                        logger.info("CDP: подключено к %s", connect_cdp_url.strip())
                    except Exception as exc:
                        logger.warning(
                            "CDP недоступен (%s). "
                            "Переключаемся на обычный сценарий логина.",
                            exc,
                        )
                        connect_cdp_url = None
                        browser = None
                        context = None
                if connect_cdp_url is None and use_persistent_profile:
                    launch_kw: dict = {
                        "user_data_dir": str(profile),
                        "headless": False,
                        "locale": "en-US",
                        "viewport": {"width": 1280, "height": 800},
                        "user_agent": env.user_agent,
                        "args": list(_PERSISTENT_ARGS),
                        "slow_mo": 50,
                    }
                    if channel:
                        launch_kw["channel"] = channel
                    if proxy:
                        launch_kw["proxy"] = proxy
                    context = p.chromium.launch_persistent_context(**launch_kw)
                    page = context.pages[0] if context.pages else context.new_page()
                    if out.is_file():
                        self._apply_cookies_from_storage_state(context, out)
                else:
                    simple_launch_kw: dict = {
                        "headless": False,
                        "args": list(_PERSISTENT_ARGS),
                    }
                    if proxy:
                        simple_launch_kw["proxy"] = proxy
                    browser = p.chromium.launch(**simple_launch_kw)
                    context = browser.new_context(
                        user_agent=env.user_agent, locale="en-US"
                    )
                    page = context.new_page()

                self._prepare_page(page, base)

                page.goto(login_url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_timeout(500)
                dismiss_geo_redirect_modal_if_present_sync(page)
                dismiss_geoip_banner_if_present_sync(page)
                dismiss_cookie_consent_if_present_sync(page)

                email_visible = False
                try:
                    page.locator("#CustomerEmail").wait_for(
                        state="visible", timeout=12_000
                    )
                    email_visible = True
                except Exception:
                    logger.info("Форма логина не показана — проверяем активную сессию")

                if email_visible:
                    page.locator("#CustomerEmail").fill(email)
                    page.locator("button.tp-main-customer-form__button").filter(
                        has_text=re.compile(r"Sign in", re.I)
                    ).first.click()
                    page.wait_for_timeout(1200)
                    dismiss_shop_pay_modal_if_present_sync(page)

                    page.locator("#CustomerPassword").wait_for(
                        state="visible", timeout=35_000
                    )
                    page.locator("#CustomerPassword").fill(password)
                    page.locator("button.tp-main-customer-form__button").filter(
                        has_text=re.compile(r"Sign in", re.I)
                    ).first.click()
                else:
                    page.goto(
                        f"{base}/account",
                        wait_until="domcontentloaded",
                        timeout=120_000,
                    )
                    page.wait_for_timeout(800)

                try:
                    page.wait_for_url(
                        re.compile(r".*/account(?!/login).*", re.I), timeout=45_000
                    )
                except Exception:
                    if manual_fallback:
                        input("После успешного входа нажмите Enter… ")
                    else:
                        raise RuntimeError("Вход не подтвержден")

                self._ensure_logged_in(page, base, manual_fallback=manual_fallback)

                self._prepare_page(page, base)
                try:
                    self.select_shipping_country_russia(page)
                except Exception as exc:
                    logger.warning(
                        "Пропуск выбора доставки Russia при сохранении состояния: %s",
                        exc,
                    )

                context.storage_state(path=str(out))
                logger.info("Состояние storage_state сохранено: %s", out)
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass

        return out

    # Каталог профиля Chromium.
    def _persistent_user_data_dir(self) -> Path:
        raw = load_settings().playwright_profile.strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return DEFAULT_USER_DATA_DIR

    # Добавляет cookies из JSON в persistent context.
    def _apply_cookies_from_storage_state(
        self, context: SyncBrowserContext, path: Path
    ) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Не удалось прочитать %s: %s", path, exc)
            return
        cookies = data.get("cookies") or []
        if not cookies:
            return
        try:
            context.add_cookies(cookies)
            logger.info("Подмешаны cookies из %s (%s шт.)", path, len(cookies))
        except Exception as exc:
            logger.warning("Не удалось добавить cookies в контекст: %s", exc)

    # Открытие главной и закрытие попапов перед логином или после него.
    def _prepare_page(self, page, base_url: str) -> None:
        page.goto(base_url + "/", wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(600)
        dismiss_geo_redirect_modal_if_present_sync(page)
        dismiss_geoip_banner_if_present_sync(page)
        dismiss_cookie_consent_if_present_sync(page)

    # Эвристика: на /account виден logout или нет формы логина.
    def account_session_looks_logged_in(self, page) -> bool:
        try:
            u = (page.url or "").lower()
            if "account/login" in u:
                return False
            if page.locator('a[href*="account/logout" i]').count():
                return True
            if page.locator("#CustomerEmail").count():
                return False
        except Exception:
            pass
        return False

    # Цикл goto /account до подтверждённой сессии или ручной паузы.
    def _ensure_logged_in(
        self, page, base: str, *, manual_fallback: bool, max_manual_tries: int = 3
    ) -> None:
        for attempt in range(max_manual_tries if manual_fallback else 1):
            page.goto(f"{base}/account", wait_until="domcontentloaded", timeout=120_000)
            page.wait_for_timeout(1000)
            if self.account_session_looks_logged_in(page):
                logger.info("Сессия ЛК подтверждена (/account)")
                return
            if not manual_fallback:
                raise RuntimeError("Вход не выполнен: /account")
            logger.warning(
                "Вход не подтверждён (попытка %s/%s). В браузере откройте и войдите.",
                attempt + 1,
                max_manual_tries,
            )
            input("Когда в шапке будет аккаунт (не гость), нажмите Enter… ")
        raise RuntimeError("Не удалось подтвердить вход после ручных попыток")

    # Выбор страны доставки Russia в шапке (sync Page).
    def select_shipping_country_russia(self, page) -> None:
        try:
            active = page.locator(".tp-localization__active-item").first
            if active.count() and re.search(
                r"Russia|Rusland|Россия", active.inner_text() or "", re.I
            ):
                logger.info("Доставка уже Russia")
                return
        except Exception:
            pass

        ship_btn = page.locator('button[aria-controls*="HeaderShippingCountry"]').first
        try:
            ship_btn.click(timeout=20_000)
        except Exception as exc:
            logger.warning(
                "Кнопка страны доставки: %s — пробуем .tp-localization__select", exc
            )
            try:
                page.locator(".tp-localization__select").first.click(timeout=15_000)
            except Exception as exc2:
                logger.warning(
                    "Альтернативный селектор: %s — кликаем принудительно", exc2
                )
                ship_btn.click(timeout=15_000, force=True)

        page.wait_for_timeout(800)
        russia_label = re.compile(r"Russia|Rusland|Россия", re.I)
        dropdown = page.locator('[id*="HeaderShippingCountry-country-results"]')
        try:
            dropdown.wait_for(state="visible", timeout=12_000)
            dropdown.get_by_text(russia_label).first.click(timeout=18_000)
        except Exception:
            page.get_by_text(russia_label).first.click(timeout=15_000)

        page.wait_for_timeout(2000)
        logger.info("Выбрана доставка Russia")

    # То же выставление Russia для async Page (после открытия витрины в парсере).
    async def select_shipping_country_russia_async(self, page: Page) -> None:
        try:
            active = page.locator(".tp-localization__active-item").first
            if await active.count() and re.search(
                r"Russia|Rusland|Россия", (await active.inner_text() or ""), re.I
            ):
                logger.info("Доставка уже Russia")
                return
        except Exception:
            pass

        ship_btn = page.locator('button[aria-controls*="HeaderShippingCountry"]').first
        try:
            await ship_btn.click(timeout=20_000)
        except Exception as exc:
            logger.warning(
                "Кнопка страны доставки: %s — пробуем .tp-localization__select", exc
            )
            try:
                await page.locator(".tp-localization__select").first.click(
                    timeout=15_000
                )
            except Exception as exc2:
                logger.warning(
                    "Альтернативный селектор: %s — кликаем принудительно", exc2
                )
                await ship_btn.click(timeout=15_000, force=True)

        await page.wait_for_timeout(800)
        russia_label = re.compile(r"Russia|Rusland|Россия", re.I)
        dropdown = page.locator('[id*="HeaderShippingCountry-country-results"]')
        try:
            await dropdown.wait_for(state="visible", timeout=12_000)
            await dropdown.get_by_text(russia_label).first.click(timeout=18_000)
        except Exception:
            await page.get_by_text(russia_label).first.click(timeout=15_000)

        await page.wait_for_timeout(2000)
        logger.info("Выбрана доставка Russia")
