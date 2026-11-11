from urllib.parse import urlsplit, urlunsplit


def safe_relative_redirect_path(
    path: str | None,
    *,
    default: str = "/catalog",
) -> str:
    normalized = (path or "").strip() or default
    if not normalized.startswith("/") or normalized.startswith("//"):
        return default
    return normalized


def safe_storefront_next_url(next_q: str | None, default: str = "/catalog") -> str:
    return safe_relative_redirect_path(next_q, default=default)


def storefront_web_catalog_url(public_site_url: str = "") -> str:
    base = (public_site_url or "").strip().rstrip("/")
    if base:
        return f"{base}/catalog"
    return "/catalog"


# Абсолютный URL страницы поддержки на витрине.
def storefront_support_url(
    *,
    public_site_url: str = "",
    mini_app_url: str = "",
) -> str:
    base = (public_site_url or "").strip().rstrip("/")
    if base:
        return f"{base}/account?tab=support"
    mini = (mini_app_url or "").strip()
    if not mini:
        return ""
    parsed = urlsplit(mini)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/")
    app_base = path if path.endswith("/app") else f"{path}/app" if path else "/app"
    return f"{parsed.scheme}://{parsed.netloc}{app_base}/account?tab=support"


# Нормализует URL Mini App и гарантирует путь /app.
def normalize_mini_app_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url.strip())
    path = parsed.path.rstrip("/")
    normalized_path = "/app" if path in {"", "/"} else path
    return urlunsplit(
        (parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment)
    )


# Абсолютный URL вкладки ЛК внутри Mini App (web_app-кнопки бота).
def mini_app_account_tab_url(mini_app_url: str, tab: str) -> str:
    base = normalize_mini_app_url(mini_app_url).rstrip("/")
    return f"{base}/account?tab={tab}"


def _mini_app_short_name_from_path(path: str) -> str:
    normalized = (path or "").strip().strip("/")
    if not normalized:
        return "app"
    return normalized.split("/")[-1] or "app"


def _bot_username_from_mini_app_url(mini_app_url: str) -> str:
    parsed = urlsplit((mini_app_url or "").strip())
    host = (parsed.hostname or "").lower()
    if host.endswith(".telegram.me"):
        return host[: -len(".telegram.me")]
    if host in {"t.me", "telegram.me", "www.t.me"}:
        parts = parsed.path.strip("/").split("/")
        return parts[0] if parts else ""
    return ""


def storefront_telegram_open_url(
    *,
    mini_app_url: str = "",
    bot_username: str = "",
) -> str:
    mini = (mini_app_url or "").strip()
    bot = (bot_username or "").strip().lstrip("@") or _bot_username_from_mini_app_url(
        mini
    )

    if mini:
        parsed = urlsplit(mini)
        host = (parsed.hostname or "").lower()
        if host in {"t.me", "telegram.me", "www.t.me"}:
            path = parsed.path.strip("/")
            if path:
                return f"https://t.me/{path}"

    short_name = _mini_app_short_name_from_path(urlsplit(mini).path if mini else "/app")
    if bot:
        return f"https://t.me/{bot}/{short_name}"
    return ""
