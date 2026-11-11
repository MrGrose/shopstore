from src.utils.html_text import (
    is_manufacturer_imprint_description,
    strip_manufacturer_imprint_from_description,
)


def test_is_manufacturer_imprint_description_detects_legal_block():
    text = (
        "TRADINTER S.L. Transpaderne, 29 4 Izsa., Building Barajas I, "
        "Madrid 28042, Spain www.bullpadel.com"
    )
    assert is_manufacturer_imprint_description(text) is True


def test_is_manufacturer_imprint_description_allows_real_description():
    text = "Experience Unmatched Comfort with the Oneda Tank Top for Women " * 3
    assert is_manufacturer_imprint_description(text) is False


def test_strip_manufacturer_imprint_from_description_keeps_product_text():
    text = (
        "Experience Unmatched Comfort with the Oneda Tank Top for Women. "
        "Designed specifically for the dynamic world of padel. "
        "TRADINTER S.L. Transpaderne, 29 4 Izsa., Building Barajas I, "
        "Madrid 28042, Spain www.bullpadel.com"
    )
    cleaned = strip_manufacturer_imprint_from_description(text)
    assert "TRADINTER" not in cleaned
    assert cleaned.startswith("Experience Unmatched Comfort")
