from decimal import Decimal
from types import SimpleNamespace

from src.services.catalog.export import PRODUCT_EXPORT_FIELDS, product_to_export_row


def test_product_to_export_row_maps_russian_columns():
    product = SimpleNamespace(
        id=42,
        brand="NOX",
        title='Racket, "Pro"',
        sport_type="Padel",
        supplier_price_eur=Decimal("89.50"),
        sale_price=Decimal("12036.15"),
        stock=3,
        product_url="https://example.com/p/42",
    )
    row = product_to_export_row(product)
    assert row == [
        "42",
        "NOX",
        'Racket, "Pro"',
        "Padel",
        "89.50",
        "12036.15",
        "3",
        "https://example.com/p/42",
    ]
    assert len(row) == len(PRODUCT_EXPORT_FIELDS)
