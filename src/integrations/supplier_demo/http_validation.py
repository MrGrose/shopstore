from http import HTTPStatus

REAL_CAPTCHA_TOKENS = (
    "cf-turnstile",
    "g-recaptcha",
    "h-captcha",
    "hcaptcha",
    "turnstile",
)
CF_CHALLENGE_TOKENS = (
    "just a moment",
    "cf-browser-verification",
    "cf-challenge",
    "checking your browser",
    "cdn-cgi/challenge",
)


# Реальный captcha-виджет, не слово captcha в CF JS.
def is_real_captcha_html(html: str) -> bool:
    low = (html or "").lower()
    return any(token in low for token in REAL_CAPTCHA_TOKENS)


# CF interstitial / managed challenge, не CAPTCHA-виджет.
def is_cf_challenge_html(html: str, title: str | None = None) -> bool:
    blob = f"{title or ''} {html or ''}".lower()
    if any(token in blob for token in CF_CHALLENGE_TOKENS):
        return True
    return "cloudflare" in blob and "challenge" in blob


# Проверка HTTP HTML страницы товара Supplier-Demo.
def reject_http_html_reason(html: str, status: int | None) -> str | None:
    low = html.lower()
    if status is not None and status >= HTTPStatus.BAD_REQUEST:
        return f"status={status}"
    if "something went wrong" in low or "temporarily unavailable" in low:
        return "error_page"
    if "product-data" not in low:
        if "/account/login" in low:
            return "login"
        if is_cf_challenge_html(html):
            return "challenge"
        if is_real_captcha_html(html):
            return "captcha"
        return "no_product_data"
    if "tp-price-item__member-price" not in low:
        return "no_member_price"
    if "data-tp-gtm-final-price" not in low:
        return "no_final_price"
    return None


# Построить причину challenge ответа Supplier-Demo.
def http_challenge_reason(
    html: str,
    status: int | None,
    reject_reason: str | None = None,
) -> str | None:
    reason = (
        reject_reason
        if reject_reason is not None
        else reject_http_html_reason(html, status)
    )
    if reason in {"login", "captcha", "challenge"}:
        return reason
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return "rate_limited"
    if status is not None and status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return "server_error"
    low = html.lower()
    blocked_statuses = {HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED}
    if status in blocked_statuses or "access denied" in low:
        return "blocked"
    return None


# Lane HTTP event: 429 / CF challenge / CAPTCHA / 500 / timeout — без смешивания.
def classify_lane_http_event(
    html: str = "",
    status: int | None = None,
    reject_reason: str | None = None,
) -> str:
    if reject_reason == "timeout":
        return "timeout"
    if reject_reason == "request_error":
        return "network"
    parsed_status = status
    if parsed_status is None and reject_reason and reject_reason.startswith("status="):
        try:
            parsed_status = int(reject_reason.split("=", 1)[1])
        except ValueError:
            parsed_status = None
    if parsed_status == HTTPStatus.TOO_MANY_REQUESTS:
        return "http_429"
    if parsed_status is not None and parsed_status >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return "supplier_500"
    reason = http_challenge_reason(html or "", parsed_status, reject_reason)
    if reason == "rate_limited":
        return "http_429"
    if reason == "challenge":
        return "cf_challenge"
    if reason == "captcha":
        return "captcha"
    if reason == "server_error":
        return "supplier_500"
    if reject_reason is None:
        return "http_success"
    return "other"
