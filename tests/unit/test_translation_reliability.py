from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.models.product import Product
from src.services.catalog.importing.enrichment_writer import compute_update_flags
from src.services.catalog.importing.helpers import (
    apply_description,
    hash_text,
    translate_chunk_descriptions,
)
from src.services.catalog.importing.product_complete import is_enrichment_hold
from src.utils.html_text import strip_html_plaintext
from src.utils.translate_descriptions import (
    HUGE_RAW_CHARS,
    _translate_chunk,
    is_google_error_page,
    is_invalid_translation_response,
    stored_description_ru_is_valid,
    translate_plain_text_to_ru,
    translation_backfill_skip_reason,
)

_EN_RAW = (
    "Explore the Versatility of the adidas Sports Bag Designed for the sport "
    "enthusiast who needs space for shoes, rackets and training gear every day."
)
_VALID_RU = (
    "Кроссовки Nike Court Slam для тенниса с амортизацией Zoom Air "
    "и верхом из кожи adidas. Артикул SKU-12345."
)
_GOOGLE_ERROR_ASCII = (
    "Error 500 (Server Error)!!1500.That's an error.There was an error. "
    "Please try again later.That's all we know."
)
_GOOGLE_ERROR_UNICODE = (
    "Error 500 (Server Error)!!1500.That’s an error.There was an error. "
    "Please try again later.That’s all we know."
)
_IMPRINT = "TRADINTER S.L. Madrid www.bullpadel.com"


@pytest.fixture(autouse=True)
def _disable_libretranslate(monkeypatch):
    monkeypatch.setattr(
        "src.utils.translate_descriptions._libre_settings",
        lambda: ("", 60.0),
    )


# Включает fake LibreTranslate URL для тестов fallback.
def _enable_lt(monkeypatch, timeout: float = 5.0) -> None:
    monkeypatch.setattr(
        "src.utils.translate_descriptions._libre_settings",
        lambda: ("http://libretranslate.test", timeout),
    )


# Собирает Product для unit-тестов apply_description / storefront.
def _product(
    raw: str | None = _EN_RAW,
    ru: str | None = None,
    desc_hash: str | None = None,
    dom_attempts: int = 0,
    dom_last_error: str | None = None,
) -> Product:
    cleaned = strip_html_plaintext(raw)
    return Product(
        title="Sports bag",
        brand="adidas",
        sale_price=Decimal("10.00"),
        regular_price=Decimal("10.00"),
        supplier_price_eur=Decimal("10.00"),
        stock=1,
        product_url="https://example.com/bag",
        is_active=True,
        description_raw=cleaned,
        description_ru=ru,
        description_hash=desc_hash if desc_hash is not None else hash_text(cleaned),
        dom_attempts=dom_attempts,
        dom_last_error=dom_last_error,
    )


# Базовые kwargs compute_update_flags с совпадающими ценой/стоком.
def _flags_kwargs(existing: Product, incoming_description: str, is_dom_full: bool):
    return {
        "existing": existing,
        "sale_price": Decimal(existing.supplier_price_eur or 0),
        "regular_price": Decimal(existing.regular_price or 0),
        "stock": int(existing.stock or 0),
        "incoming_variant_signature": (),
        "current_variant_signature": (),
        "incoming_gallery_layout": (),
        "current_gallery_layout": (),
        "incoming_gallery_url_signature": (),
        "current_gallery_url_signature": (),
        "incoming_feature_signature": (),
        "current_feature_signature": (),
        "incoming_description": incoming_description,
        "is_dom_full": is_dom_full,
        "is_dom_import": True,
        "incoming_has_features": False,
        "catalog": {
            "category_l1": existing.category_l1,
            "category_l2": existing.category_l2,
            "category_l3": existing.category_l3,
            "gender": existing.gender,
        },
        "category_l2": existing.category_l2,
        "sport_type": existing.sport_type,
        "trade_group": existing.trade_group,
        "write_categories": False,
    }


def test_google_error_ascii_and_unicode_are_invalid():
    assert is_google_error_page(_GOOGLE_ERROR_ASCII) is True
    assert is_google_error_page(_GOOGLE_ERROR_UNICODE) is True
    assert is_invalid_translation_response(_EN_RAW, _GOOGLE_ERROR_ASCII) is True
    assert is_invalid_translation_response(_EN_RAW, _GOOGLE_ERROR_UNICODE) is True


def test_empty_and_source_echo_are_invalid():
    assert is_invalid_translation_response(_EN_RAW, None) is True
    assert is_invalid_translation_response(_EN_RAW, "   ") is True
    assert is_invalid_translation_response(_EN_RAW, _EN_RAW) is True


def test_valid_ru_with_latin_brands_is_not_invalid():
    assert is_invalid_translation_response(_EN_RAW, _VALID_RU) is False
    assert stored_description_ru_is_valid(_VALID_RU) is True


def test_no_cyrillic_alone_is_not_the_invalid_rule():
    paraphrased_en = _EN_RAW.replace("Explore", "Discover")
    assert paraphrased_en != _EN_RAW
    assert is_invalid_translation_response(_EN_RAW, paraphrased_en) is False
    assert stored_description_ru_is_valid(paraphrased_en) is False


def test_translate_chunk_exception_returns_none(monkeypatch):
    def boom(text: str, source: str) -> str:
        raise RuntimeError("connection reset")

    monkeypatch.setattr("src.utils.translate_descriptions._google_translate", boom)
    assert _translate_chunk(_EN_RAW, "en") is None


def test_translate_chunk_http_200_error_page_returns_none(monkeypatch):
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: _GOOGLE_ERROR_UNICODE,
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_translate_chunk_empty_and_echo_return_none(monkeypatch):
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: text,
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_translate_chunk_valid_ru_returned(monkeypatch):
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: _VALID_RU,
    )
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU


def test_rate_limit_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(text: str, source: str) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Too many requests")
        return _VALID_RU

    slept: list[float] = []
    monkeypatch.setattr("src.utils.translate_descriptions._google_translate", flaky)
    monkeypatch.setattr("src.utils.translate_descriptions.time.sleep", slept.append)
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU
    assert calls["n"] == 3
    assert len(slept) == 2


def test_dhl_plain_text_keeps_source_when_chunk_fails(monkeypatch):
    monkeypatch.setattr(
        "src.utils.translate_descriptions._translate_chunk",
        lambda text, source: None,
    )
    assert translate_plain_text_to_ru("left the depot", source="en") == "left the depot"


def test_apply_description_same_hash_valid_ru_skips():
    product = _product(ru=_VALID_RU)
    original_ru = product.description_ru
    apply_description(product, _EN_RAW, {_EN_RAW: "другой текст на русском языке тут"})
    assert product.description_ru == original_ru


def test_apply_description_same_hash_empty_ru_retries():
    product = _product(ru=None)
    apply_description(product, _EN_RAW, {_EN_RAW: _VALID_RU})
    assert product.description_ru == _VALID_RU


def test_apply_description_same_hash_echo_retries():
    product = _product(ru=_EN_RAW)
    apply_description(product, _EN_RAW, {_EN_RAW: _VALID_RU})
    assert product.description_ru == _VALID_RU


def test_apply_description_same_hash_google_error_retries():
    product = _product(ru=_GOOGLE_ERROR_UNICODE)
    apply_description(product, _EN_RAW, {_EN_RAW: _VALID_RU})
    assert product.description_ru == _VALID_RU


def test_apply_description_raw_changed_translates():
    product = _product(raw="Old english marketing copy for a racket bag.", ru=_VALID_RU)
    new_raw = _EN_RAW
    apply_description(product, new_raw, {new_raw: _VALID_RU})
    assert product.description_raw == new_raw
    assert product.description_hash == hash_text(new_raw)
    assert product.description_ru == _VALID_RU


def test_apply_description_failed_preserves_valid_ru():
    product = _product(ru=_VALID_RU)
    apply_description(product, _EN_RAW + " extra", {})
    assert product.description_ru == _VALID_RU
    assert product.description_raw.endswith("extra")


def test_apply_description_failed_clears_invalid_ru():
    product = _product(ru=_GOOGLE_ERROR_ASCII)
    apply_description(product, _EN_RAW, {})
    assert product.description_ru is None
    assert product.description_raw == _EN_RAW


def test_translation_failure_does_not_alter_dom_attempts_or_hold():
    product = _product(
        ru=_GOOGLE_ERROR_ASCII,
        dom_attempts=5,
        dom_last_error="invalid_description",
    )
    apply_description(product, _EN_RAW, {})
    assert product.dom_attempts == 5
    assert product.dom_last_error == "invalid_description"
    assert is_enrichment_hold(product, max_attempts=5) is True


def test_full_flags_retry_when_ru_invalid_even_if_hash_matches():
    product = _product(ru=_GOOGLE_ERROR_UNICODE)
    flags = compute_update_flags(**_flags_kwargs(product, _EN_RAW, is_dom_full=True))
    assert flags.has_changes is True


def test_full_flags_skip_when_ru_valid_and_hash_matches():
    product = _product(ru=_VALID_RU)
    flags = compute_update_flags(**_flags_kwargs(product, _EN_RAW, is_dom_full=True))
    assert flags.has_changes is False


def test_lite_flags_ignore_invalid_ru():
    product = _product(ru=_GOOGLE_ERROR_ASCII)
    flags = compute_update_flags(**_flags_kwargs(product, _EN_RAW, is_dom_full=False))
    assert flags.has_changes is False


def test_storefront_falls_back_to_raw_on_google_error():
    product = _product(ru=_GOOGLE_ERROR_UNICODE)
    assert product.description == _EN_RAW


def test_storefront_shows_valid_ru():
    product = _product(ru=_VALID_RU)
    assert product.description == _VALID_RU


def test_backfill_selects_empty_echo_error_and_excludes_the_rest():
    assert translation_backfill_skip_reason(_EN_RAW, None, is_active=True) is None
    assert translation_backfill_skip_reason(_EN_RAW, _EN_RAW, is_active=True) is None
    assert (
        translation_backfill_skip_reason(_EN_RAW, _GOOGLE_ERROR_ASCII, is_active=True)
        is None
    )
    assert (
        translation_backfill_skip_reason(_EN_RAW, _VALID_RU, is_active=True)
        == "valid_ru"
    )
    assert translation_backfill_skip_reason(_IMPRINT, None, is_active=True) == "imprint"
    assert (
        translation_backfill_skip_reason("x" * HUGE_RAW_CHARS, None, is_active=True)
        == "huge_raw"
    )
    assert translation_backfill_skip_reason(_VALID_RU, None, is_active=True) == "raw_ru"
    assert (
        translation_backfill_skip_reason(_EN_RAW, _GOOGLE_ERROR_ASCII, is_active=False)
        == "inactive"
    )


@pytest.mark.asyncio
async def test_translate_chunk_descriptions_omits_invalid(monkeypatch):
    monkeypatch.setattr(
        "src.services.catalog.importing.helpers._translate_sleep_range",
        lambda: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "src.services.catalog.importing.helpers._translate_parallelism",
        lambda: 1,
    )
    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.asyncio.sleep",
        AsyncMock(),
    )

    def fake_html(text: str, source: str, sleep_range: tuple[float, float]):
        if "error" in text:
            return _GOOGLE_ERROR_ASCII
        if "echo" in text:
            return text
        return _VALID_RU

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.translate_description_html",
        fake_html,
    )
    result = await translate_chunk_descriptions(
        [_EN_RAW, "error page source text for tennis bag", "echo source text here"]
    )
    assert result[_EN_RAW] == _VALID_RU
    assert "error page source text for tennis bag" not in result
    assert "echo source text here" not in result


# Fake httpx.post response for LibreTranslate tests.
class _FakeLtResponse:
    def __init__(self, status_code: int = 200, payload=None, json_error: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


# Ставит httpx.post заглушку и собирает вызовы.
def _stub_lt_http(monkeypatch, response=None, error=None):
    calls: list[dict] = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr("src.utils.translate_descriptions.httpx.post", fake_post)
    return calls


def test_google_valid_does_not_call_libretranslate(monkeypatch):
    _enable_lt(monkeypatch)
    calls = _stub_lt_http(
        monkeypatch, _FakeLtResponse(payload={"translatedText": "не должно"})
    )
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: _VALID_RU,
    )
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU
    assert calls == []


def test_google_error_page_uses_libretranslate(monkeypatch):
    _enable_lt(monkeypatch)
    calls = _stub_lt_http(
        monkeypatch, _FakeLtResponse(payload={"translatedText": _VALID_RU})
    )
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: _GOOGLE_ERROR_UNICODE,
    )
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU
    assert len(calls) == 1
    assert calls[0]["json"]["source"] == "en"
    assert calls[0]["json"]["target"] == "ru"
    assert calls[0]["json"]["format"] == "text"


def test_google_echo_uses_libretranslate(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(payload={"translatedText": _VALID_RU}))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: _EN_RAW,
    )
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU


def test_google_exception_uses_libretranslate(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(payload={"translatedText": _VALID_RU}))

    def boom(text: str, source: str) -> str:
        raise RuntimeError("connection reset")

    monkeypatch.setattr("src.utils.translate_descriptions._google_translate", boom)
    assert _translate_chunk(_EN_RAW, "en") == _VALID_RU


def test_libretranslate_echo_returns_none(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(payload={"translatedText": _EN_RAW}))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_libretranslate_empty_returns_none(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(payload={"translatedText": "  "}))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_libretranslate_http_500_returns_none(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(status_code=500, payload={"error": "x"}))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_libretranslate_malformed_json_returns_none(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, _FakeLtResponse(json_error=True))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_libretranslate_timeout_returns_none(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(monkeypatch, error=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_empty_libretranslate_url_skips_http(monkeypatch):
    calls = _stub_lt_http(
        monkeypatch, _FakeLtResponse(payload={"translatedText": _VALID_RU})
    )
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None
    assert calls == []


def test_libretranslate_error_text_is_rejected(monkeypatch):
    _enable_lt(monkeypatch)
    _stub_lt_http(
        monkeypatch,
        _FakeLtResponse(payload={"translatedText": _GOOGLE_ERROR_ASCII}),
    )
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") is None


def test_libretranslate_latin_heavy_valid_is_kept(monkeypatch):
    _enable_lt(monkeypatch)
    paraphrased = _EN_RAW.replace("Explore", "Discover")
    _stub_lt_http(monkeypatch, _FakeLtResponse(payload={"translatedText": paraphrased}))
    monkeypatch.setattr(
        "src.utils.translate_descriptions._google_translate",
        lambda text, source: "",
    )
    assert _translate_chunk(_EN_RAW, "en") == paraphrased
    assert is_invalid_translation_response(_EN_RAW, paraphrased) is False


@pytest.mark.asyncio
async def test_import_products_does_not_call_translate_chunk(monkeypatch):
    from src.schemas.catalog_import import ProductImportList
    from src.services.catalog.importing.coordinator import ProductImportService

    async def boom(*args, **kwargs):
        raise AssertionError("translate_chunk_descriptions must not run")

    monkeypatch.setattr(
        "src.services.catalog.importing.coordinator.imp.translate_chunk_descriptions",
        boom,
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    svc = ProductImportService(session)
    svc.pricing_service.get_margin_rules = AsyncMock()
    svc.pricing_service.get_settings = AsyncMock(return_value=MagicMock(eur_rate=1))
    result = await svc.import_products(ProductImportList(products=[]))
    assert result["created"] == 0
    assert result["updated"] == 0


def test_apply_description_stamps_translated_hash_when_keeping_old_ru():
    product = _product(ru=_VALID_RU)
    old_hash = product.description_hash
    new_raw = _EN_RAW + " extra"
    apply_description(product, new_raw, {})
    assert product.description_ru == _VALID_RU
    assert product.description_raw.endswith("extra")
    assert product.description_translated_hash == old_hash


def test_lite_flags_persist_when_raw_hash_changes():
    product = _product(ru=_VALID_RU)
    flags = compute_update_flags(
        **_flags_kwargs(product, _EN_RAW + " extra copy", is_dom_full=False)
    )
    assert flags.has_changes is True
