import pytest

from src.integrations.supplier_demo import http_validation as shared
from src.scraper.enrichment import http_validate as legacy

VALID_PDP = """
<html>
  <div id="product-data"></div>
  <span class="tp-price-item__member-price"
        data-tp-gtm-final-price="119.90"></span>
</html>
"""


def test_valid_pdp_is_accepted() -> None:
    assert shared.reject_http_html_reason(VALID_PDP, 200) is None


def test_login_link_on_valid_pdp_is_not_login_page() -> None:
    html = VALID_PDP.replace("</html>", '<a href="/account/login">Login</a></html>')
    assert shared.reject_http_html_reason(html, 200) is None


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<a href="/account/login">Login</a>', "login"),
        ("captcha required", "no_product_data"),
        ('<div class="cf-turnstile"></div>', "captcha"),
        ("Cloudflare challenge", "challenge"),
        ("plain unexpected page", "no_product_data"),
        ("Something went wrong", "error_page"),
    ],
)
def test_reject_reason_for_invalid_page(html: str, expected: str) -> None:
    assert shared.reject_http_html_reason(html, 200) == expected


def test_missing_member_price_is_rejected() -> None:
    html = '<div id="product-data" data-tp-gtm-final-price="100"></div>'
    assert shared.reject_http_html_reason(html, 200) == "no_member_price"


def test_missing_final_price_is_rejected() -> None:
    html = '<div id="product-data" class="tp-price-item__member-price"></div>'
    assert shared.reject_http_html_reason(html, 200) == "no_final_price"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "blocked"),
        (403, "blocked"),
        (429, "rate_limited"),
        (500, "server_error"),
        (502, "server_error"),
        (503, "server_error"),
    ],
)
def test_challenge_reason_for_http_status(status: int, expected: str) -> None:
    reject_reason = shared.reject_http_html_reason("", status)
    assert shared.http_challenge_reason("", status, reject_reason) == expected


def test_access_denied_body_is_blocked() -> None:
    assert shared.http_challenge_reason("Access denied", 200) == "blocked"


def test_legacy_scraper_import_reexports_shared_functions() -> None:
    assert legacy.reject_http_html_reason is shared.reject_http_html_reason
    assert legacy.http_challenge_reason is shared.http_challenge_reason


# Слово captcha в CF JS не делает страницу CAPTCHA.
def test_cf_js_captcha_word_is_challenge() -> None:
    html = (
        "<title>Just a moment...</title>"
        "<script>captcha:false; cloudflare challenge</script>"
    )
    assert shared.reject_http_html_reason(html, 200) == "challenge"
    assert shared.classify_lane_http_event(html, 200) == "cf_challenge"
    assert shared.classify_lane_http_event(html, 429) == "http_429"
    assert shared.classify_lane_http_event("", 500) == "supplier_500"
