import pytest

from src.core.config import settings
from src.schemas.order import OrderItemSchema, OrderShipmentItemSchema


def test_order_item_schema_exposes_public_product_image_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    item = OrderItemSchema.model_validate(
        {
            "product_id": 1,
            "quantity": 1,
            "unit_price": "1000",
            "product_image_url": "/media/products/order-snap.jpg",
        }
    )
    assert item.product_image_url == (
        "https://media.example.com/media/products/order-snap.jpg"
    )


def test_order_shipment_item_schema_exposes_public_product_image_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    item = OrderShipmentItemSchema(
        order_item_id=1,
        quantity=1,
        product_image_url="/media/products/shipment-snap.jpg",
    )
    assert item.product_image_url == (
        "https://media.example.com/media/products/shipment-snap.jpg"
    )
