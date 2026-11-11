from src.core.referral import normalize_referral_alias, validate_referral_alias


def test_normalize_referral_alias_uppercase() -> None:
    assert normalize_referral_alias("Martin") == "martin"
    assert normalize_referral_alias("  MARTIN  ") == "martin"


def test_validate_referral_alias_accepts_valid() -> None:
    assert validate_referral_alias("martin") is None
    assert validate_referral_alias("m_1-test") is None


def test_validate_referral_alias_rejects_reserved() -> None:
    assert validate_referral_alias("admin") is not None
    assert validate_referral_alias("catalog") is not None


def test_validate_referral_alias_rejects_ps_prefix() -> None:
    assert validate_referral_alias("ps-42") is not None
    assert validate_referral_alias("ps-martin") is not None


def test_validate_referral_alias_empty_ok() -> None:
    assert validate_referral_alias("") is None
