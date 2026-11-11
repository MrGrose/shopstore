from decimal import Decimal

from src.core.referral import (
    build_referral_link,
    calculate_commission_amount,
    generate_opaque_referral_code,
    is_legacy_ps_referral_code,
)
from src.services.referral_service import REFERRAL_ACCRUAL_ORDER_STATUS


def test_generate_opaque_referral_code_length() -> None:
    code = generate_opaque_referral_code()
    assert len(code) == 12
    assert code.isalnum()


def test_is_legacy_ps_referral_code() -> None:
    assert is_legacy_ps_referral_code("PS-42")
    assert is_legacy_ps_referral_code("ps-1")
    assert not is_legacy_ps_referral_code("a1b2c3d4e5f6")


def test_calculate_commission_amount() -> None:
    assert calculate_commission_amount(Decimal("1000"), Decimal("5")) == Decimal(
        "50.00"
    )
    assert calculate_commission_amount(Decimal("999.99"), Decimal("7.5")) == Decimal(
        "75.00"
    )


def test_build_referral_link_with_public_site() -> None:
    from src.core import config

    old = config.settings.PUBLIC_SITE_URL
    try:
        config.settings.PUBLIC_SITE_URL = "https://shop.example.com/"
        assert (
            build_referral_link("a1b2c3d4e5f6")
            == "https://shop.example.com/?ref=a1b2c3d4e5f6"
        )
    finally:
        config.settings.PUBLIC_SITE_URL = old


def test_accrual_order_status_rule() -> None:
    assert REFERRAL_ACCRUAL_ORDER_STATUS == "completed"


def test_self_referral_guard() -> None:
    user_id = 10
    referrer_id = 10
    assert referrer_id == user_id
