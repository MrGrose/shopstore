from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from src.api.http_cache import build_product_etag


def test_build_product_etag_stable_for_same_product_state() -> None:
    product = MagicMock()
    product.id = 7
    product.sale_price = Decimal("100.00")
    product.regular_price = Decimal("120.00")
    product.stock = 5
    product.catalog_in_stock = True
    product.is_active = True
    product.catalog_synced_at = datetime(2026, 8, 6, 12, 0, 0)

    first = build_product_etag(product, 3)
    second = build_product_etag(product, 3)

    assert first == second
    assert first.startswith('W/"p7-')


def test_build_product_etag_changes_when_price_changes() -> None:
    product = MagicMock()
    product.id = 7
    product.sale_price = Decimal("100.00")
    product.regular_price = Decimal("120.00")
    product.stock = 5
    product.catalog_in_stock = True
    product.is_active = True
    product.catalog_synced_at = None

    first = build_product_etag(product, 1)
    product.sale_price = Decimal("90.00")
    second = build_product_etag(product, 1)

    assert first != second
