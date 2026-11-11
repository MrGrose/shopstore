from decimal import Decimal

import pytest

from src.models.pricing import PricingSettings
from src.services.pricing_service import PricingService


def _rapira_payload(*, ask_price: float = 76.36, symbol: str = "USDT/RUB") -> dict:
    return {
        "code": 0,
        "message": "SUCCESS",
        "data": [
            {
                "symbol": symbol,
                "askPrice": ask_price,
                "bidPrice": ask_price - 0.01,
            }
        ],
    }


def test_parse_rapira_eur_rate_success() -> None:
    rate = PricingService.parse_rapira_eur_rate(
        _rapira_payload(),
        multiplier=Decimal("1.2"),
    )
    assert rate == Decimal("91.6320")


def test_parse_rapira_eur_rate_api_error() -> None:
    with pytest.raises(ValueError, match="Ошибка API Rapira"):
        PricingService.parse_rapira_eur_rate({"code": 1, "message": "FAIL"})


def test_parse_rapira_eur_rate_missing_pair() -> None:
    with pytest.raises(ValueError, match="не найдена"):
        PricingService.parse_rapira_eur_rate(_rapira_payload(symbol="EUR/RUB"))


def test_parse_rapira_eur_rate_invalid_ask_price() -> None:
    with pytest.raises(ValueError, match="askPrice"):
        PricingService.parse_rapira_eur_rate(_rapira_payload(ask_price=0))


def test_rapira_eur_rate_source() -> None:
    assert (
        PricingService.rapira_eur_rate_source(
            symbol="USDT/RUB",
            multiplier=Decimal("1.2"),
        )
        == "rapira:USDT/RUB*1.20"
    )


def test_resolve_eur_rate_multiplier_prefers_settings() -> None:
    settings = PricingSettings(markup_multiplier=Decimal("1.35"))
    assert PricingService.resolve_eur_rate_multiplier(settings) == Decimal("1.35")


def test_format_eur_rate_source_display_normalizes_multiplier() -> None:
    assert (
        PricingService.format_eur_rate_source_display("rapira:USDT/RUB*1.1700")
        == "rapira:USDT/RUB*1.17"
    )
