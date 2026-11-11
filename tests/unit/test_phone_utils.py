import pytest

from src.utils.phone import mask_phone, normalize_ru_mobile_phone


def test_normalize_ru_mobile_phone_from_8_prefix():
    assert normalize_ru_mobile_phone("89991234567") == "+79991234567"


def test_normalize_ru_mobile_phone_from_10_digits():
    assert normalize_ru_mobile_phone("9991234567") == "+79991234567"


def test_normalize_ru_mobile_phone_from_e164():
    assert normalize_ru_mobile_phone("+79991234567") == "+79991234567"


def test_normalize_ru_mobile_phone_invalid():
    with pytest.raises(ValueError, match="российский мобильный"):
        normalize_ru_mobile_phone("12345")


def test_mask_phone():
    assert mask_phone("+79991234567") == "+7999***67"
