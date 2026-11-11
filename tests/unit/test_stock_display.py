import pytest

from src.core.stock_display import storefront_stock_status_key
from src.schemas.product import ProductPublicCardSchema


@pytest.mark.parametrize(
    ("qty", "expected"),
    [
        (0, "out_of_stock"),
        (1, "last"),
        (2, "low"),
        (6, "in_stock"),
    ],
)
def test_storefront_stock_status_key(qty: int, expected: str) -> None:
    assert storefront_stock_status_key(qty) == expected


def test_product_public_card_exposes_buyable_qty_and_stock_status() -> None:
    from decimal import Decimal

    card = ProductPublicCardSchema(
        id=1,
        title="Racket",
        brand="Babolat",
        sale_price=Decimal("10000"),
        regular_price=Decimal("12000"),
        product_url="/p/1",
        is_active=True,
        available_stock=2,
    )

    assert card.buyable_qty == 2
    assert card.stock_status == "low"


def test_variant_buyable_qty_prefers_available_quantity() -> None:
    from src.core.stock_display import variant_buyable_qty

    assert variant_buyable_qty(10, False, available_quantity=2) == 2
    assert variant_buyable_qty(10, True, available_quantity=0) == 0
    assert variant_buyable_qty(0, True, available_quantity=None) == 0
    assert variant_buyable_qty(3, True, available_quantity=None) == 3
