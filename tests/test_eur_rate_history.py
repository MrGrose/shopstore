from decimal import Decimal

from src.services.pricing_service import PricingService


def test_eur_rate_change_pct_up() -> None:
    pct = PricingService.eur_rate_change_pct(Decimal("100"), Decimal("110"))
    assert pct == Decimal("10.0")


def test_eur_rate_change_pct_down() -> None:
    pct = PricingService.eur_rate_change_pct(Decimal("100"), Decimal("95"))
    assert pct == Decimal("-5.0")


def test_eur_rate_change_pct_unchanged() -> None:
    assert PricingService.eur_rate_change_pct(
        Decimal("100"), Decimal("100")
    ) == Decimal("0.0")


def test_format_eur_rate_change_flash() -> None:
    msg = PricingService.format_eur_rate_change_flash(
        Decimal("100"),
        Decimal("110"),
    )
    assert msg is not None
    assert "+10.0%" in msg
    assert "Переоценка" in msg


def test_format_eur_rate_change_flash_no_change() -> None:
    assert (
        PricingService.format_eur_rate_change_flash(Decimal("100"), Decimal("100"))
        is None
    )
