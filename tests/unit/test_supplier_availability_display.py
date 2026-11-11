from src.content.supplier_availability_display import (
    enrich_supplier_check_display,
    format_supplier_check_price_line,
    format_supplier_check_status,
)

_SAMPLE_ITEM = {
    "found": True,
    "inventory_quantity": 1,
    "product_title": "Babolat Technical Viper",
    "category_l2": "Padel rackets",
    "variant_label": "370g",
    "supplier_price_eur": "66.34",
    "captured_price_eur": "68.03",
    "eur_delta_abs": "1.69",
}


def test_supplier_check_status_and_price_line() -> None:
    assert format_supplier_check_status(_SAMPLE_ITEM) == "вариант найден, 1 шт."
    assert (
        format_supplier_check_price_line(_SAMPLE_ITEM)
        == "Цена TP: 66.34 EUR (у нас — 68.03 EUR) · дешевле на 1.69 EUR"
    )


def test_enrich_supplier_check_display_for_admin_partial() -> None:
    enriched = enrich_supplier_check_display(_SAMPLE_ITEM)

    assert enriched["status_text"] == "вариант найден, 1 шт."
    assert enriched["price_prefix_text"] == ("Цена TP: 66.34 EUR (у нас — 68.03 EUR)")
    assert enriched["price_delta_tone"] == "lower"
    assert enriched["price_delta_text"] == "дешевле на 1.69 EUR"
    assert enriched["price_line_text"] == format_supplier_check_price_line(_SAMPLE_ITEM)
