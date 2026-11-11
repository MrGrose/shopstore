from decimal import Decimal

from src.schemas.catalog_import import (
    ProductImportList,
    coerce_import_price,
    coerce_variant_price,
)


# Цена товара из строки с € и запятой.
def test_coerce_import_price_parses_euro_string():
    assert coerce_import_price("12,50 €") == Decimal("12.50")


# Цена товара из int в центах.
def test_coerce_import_price_parses_cents_int():
    assert coerce_import_price(1250) == Decimal("12.50")


# Цена варианта из int в центах Shopify.
def test_coerce_variant_price_parses_cents_int():
    assert coerce_variant_price(999) == Decimal("9.99")


# pdp_meta supplier и listing stock flags.
def test_product_import_pdp_meta_flags():
    payload = ProductImportList.from_raw_products(
        [
            {
                "title": "Test",
                "product_url": "https://example.com/p",
                "pdp_meta": {
                    "stock_source": "collection_listing_fallback",
                    "supplier": {
                        "product_type": "Padel rackets",
                        "import_collection_sport": "Padel",
                    },
                },
            }
        ]
    ).products[0]
    assert payload.pdp_meta.has_supplier_block
    assert payload.pdp_meta.listing_stock_synced
