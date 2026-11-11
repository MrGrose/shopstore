from src.models.product import Product
from src.services.catalog.display.taxonomy import (
    is_catalogized_product,
    is_invalid_taxonomy_product,
)


def test_catalogized_requires_l1_l2_sport() -> None:
    p = Product(id=1, title="t", brand="b", sale_price=1, supplier_price_eur=1)
    p.sport_type = "Tennis"
    p.category_l1 = "Tennis"
    p.category_l2 = "Grips"
    p.category_l3 = None
    assert is_catalogized_product(p) is True


def test_invalid_taxonomy_active_missing_l2() -> None:
    p = Product(id=1, title="t", brand="b", sale_price=1, supplier_price_eur=1)
    p.is_active = True
    p.sport_type = "Tennis"
    p.category_l1 = "Tennis"
    p.category_l2 = None
    assert is_invalid_taxonomy_product(p) is True
    assert is_catalogized_product(p) is False


def test_inactive_invalid_taxonomy_not_flagged() -> None:
    p = Product(id=1, title="t", brand="b", sale_price=1, supplier_price_eur=1)
    p.is_active = False
    p.sport_type = None
    assert is_invalid_taxonomy_product(p) is False
