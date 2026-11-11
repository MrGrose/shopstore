from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.core.config import settings
from src.models.cart import CartItem
from src.models.product import Product
from src.services.cart_service import CartService


def test_build_item_schema_exposes_public_product_image_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    product = MagicMock(spec=Product)
    product.title = "Racket"
    product.brand = "Brand"
    product.image_url = "/media/products/sample-uuid.jpg"
    product.stock = 5
    product.supplier_price_eur = Decimal("0")

    item = MagicMock(spec=CartItem)
    item.id = 1
    item.user_id = 10
    item.product_id = 42
    item.variant_id = None
    item.quantity = 1

    service = CartService(session=MagicMock())
    schema = service._build_item_schema(
        item,
        products_map={42: product},
        reserved_map={},
        variants_map={},
        variant_reserved_map={},
        resolved_unit_price=Decimal("1000"),
    )

    assert schema.product_image_url == (
        "https://media.example.com/media/products/sample-uuid.jpg"
    )


def test_build_item_schema_keeps_relative_url_without_public_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "")
    product = MagicMock(spec=Product)
    product.title = "Racket"
    product.brand = "Brand"
    product.image_url = "/media/products/sample-uuid.jpg"
    product.stock = 5
    product.supplier_price_eur = Decimal("0")

    item = MagicMock(spec=CartItem)
    item.id = 1
    item.user_id = 10
    item.product_id = 42
    item.variant_id = None
    item.quantity = 1

    service = CartService(session=MagicMock())
    schema = service._build_item_schema(
        item,
        products_map={42: product},
        reserved_map={},
        variants_map={},
        variant_reserved_map={},
        resolved_unit_price=Decimal("1000"),
    )

    assert schema.product_image_url == "/media/products/sample-uuid.jpg"
