from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from src.jobs.dom_processing_claim import filter_held_dom_processing_products
from src.scraper.config.settings import (
    duration_to_seconds,
    resolved_dom_enqueue_lock_ttl_seconds,
    resolved_dom_processing_claim_ttl_minutes,
)
from src.scraper.enrichment.product_dom import _html_markers, classify_dom_error
from src.scraper.infrastructure.http_client import aiohttp_proxy_kwargs
from src.scraper.telemetry import map_dom_error_class


# Markers dump без captcha-ключа не должен стать captcha.
def test_classify_false_captcha_markers_is_no_product_data() -> None:
    html = "<html><body>Shoes in stock</body></html>"
    err = RuntimeError(
        "DOM без product-data; "
        + _html_markers(html, "https://example.com/p", "Shoes", 200)
    )
    assert classify_dom_error(err) == "no_product_data"
    assert "'captcha'" not in str(err)
    assert "'challenge'" not in str(err)
    assert "'blocked'" not in str(err)


# Явный captcha=True / turnstile в HTML остаётся captcha.
def test_classify_true_captcha_marker() -> None:
    html = "<html>turnstile widget</html>"
    err = RuntimeError(
        "DOM без product-data; "
        + _html_markers(html, "https://example.com/p", "Wait", 200)
    )
    assert classify_dom_error(err) == "captcha"


# challenge=True по cloudflare, без ложного captcha-ключа.
def test_classify_true_challenge_marker() -> None:
    html = "<html>cloudflare challenge</html>"
    err = RuntimeError(
        "DOM без product-data; "
        + _html_markers(html, "https://example.com/p", "Just a moment", 200)
    )
    assert classify_dom_error(err) == "challenge"


# blocked по access denied в HTML.
def test_classify_true_blocked_marker() -> None:
    html = "<html>access denied</html>"
    err = RuntimeError(
        "DOM без product-data; "
        + _html_markers(html, "https://example.com/p", "Denied", 200)
    )
    assert classify_dom_error(err) == "blocked"


# HTTP reject reason по-прежнему мапится в captcha.
def test_map_dom_error_class_keeps_explicit_captcha_reason() -> None:
    assert map_dom_error_class("captcha") == "captcha"
    assert map_dom_error_class("no_product_data") == "price_not_found"


# Claim/lock TTL поднимаются до catalog_dom_job_timeout.
def test_resolved_ttl_covers_job_timeout() -> None:
    env = SimpleNamespace(
        dom_processing_claim_ttl_minutes=15,
        dom_enqueue_lock_ttl_seconds=1800,
        catalog_dom_job_timeout="3h",
    )
    assert duration_to_seconds("3h") == 10800
    assert resolved_dom_processing_claim_ttl_minutes(env) == 180
    assert resolved_dom_enqueue_lock_ttl_seconds(env) == 10800


# Mock без job timeout не ломает старые тесты.
def test_resolved_ttl_without_job_timeout_keeps_configured() -> None:
    env = SimpleNamespace(dom_processing_claim_ttl_minutes=15)
    assert resolved_dom_processing_claim_ttl_minutes(env) == 15


# Direct egress не ставит aiohttp proxy.
def test_aiohttp_proxy_kwargs_none_is_empty() -> None:
    assert aiohttp_proxy_kwargs(None) == {}
    assert aiohttp_proxy_kwargs({}) == {}


# Playwright proxy dict → aiohttp proxy= и proxy_auth.
def test_aiohttp_proxy_kwargs_from_playwright_dict() -> None:
    kwargs = aiohttp_proxy_kwargs(
        {"server": "http://10.0.0.1:8000", "username": "u", "password": "p"}
    )
    assert kwargs["proxy"] == "http://10.0.0.1:8000"
    assert kwargs["proxy_auth"].login == "u"
    assert kwargs["proxy_auth"].password == "p"


# Старый дамп с ключом captcha: False не классифицируется как captcha.
def test_classify_strips_false_dict_keys() -> None:
    dump = (
        "DOM без product-data; markers={'captcha': False, "
        "'challenge': False, 'blocked': False}"
    )
    assert classify_dom_error(dump) == "no_product_data"


# AsyncSession mock для filter_held.
def _session_maker_mock() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=None)
    return session_cm, session


# При включённом token в SQL есть owner_token.
@pytest.mark.asyncio
async def test_filter_held_with_token_filters_owner() -> None:
    session_cm, session = _session_maker_mock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [1]
    session.execute = AsyncMock(return_value=result)
    products = [{"id": 1}, {"id": 2}]
    with patch(
        "src.jobs.dom_processing_claim.async_session_maker",
        return_value=session_cm,
    ):
        held = await filter_held_dom_processing_products(products, "token-a")
    assert held == [{"id": 1}]
    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "dom_processing_owner_token" in str(compiled)


# Без token живой claim проверяется без фильтра владельца.
@pytest.mark.asyncio
async def test_filter_held_without_token_skips_owner_filter() -> None:
    session_cm, session = _session_maker_mock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [1, 2]
    session.execute = AsyncMock(return_value=result)
    products = [{"id": 1}, {"id": 2}]
    with patch(
        "src.jobs.dom_processing_claim.async_session_maker",
        return_value=session_cm,
    ):
        held = await filter_held_dom_processing_products(products)
    assert held == products
    stmt = session.execute.await_args.args[0]
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "dom_processing_owner_token" not in str(compiled)
