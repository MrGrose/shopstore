from decimal import Decimal
from types import SimpleNamespace

from src.schemas.order import OrderItemSchema, OrderShipmentItemSchema
from src.services.orders.order_service import OrderService
from src.services.orders.shipments import build_order_shipment_schemas


# Product stub для snapshot payload.
def _product(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "title": "Mini Padel Gravity Pro 2024 Gift - grey",
        "external_id": "p0000005320203",
        "supplier_price_eur": Decimal("10.00"),
        "category_l2": "Gifts",
        "category_l3": "Fun items",
        "sale_price": Decimal("4298"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# Cart line stub для _build_order_item_payload.
def _cart_item() -> SimpleNamespace:
    return SimpleNamespace(product_id=16547, variant_id=92146, quantity=1)


# New OrderItem payload фиксирует L2/L3 с Product.
def test_new_order_item_payload_captures_product_category() -> None:
    payload = OrderService.__new__(OrderService)._build_order_item_payload(
        cart_item=_cart_item(),
        unit_price=Decimal("4298"),
        product=_product(),
        variant=None,
    )

    assert payload["category_l2_captured"] == "Gifts"
    assert payload["category_l3_captured"] == "Fun items"
    assert (
        payload["product_title_captured"] == "Mini Padel Gravity Pro 2024 Gift - grey"
    )


# API отдаёт category_l2 и RU label.
def test_order_item_schema_returns_l2_and_ru_label() -> None:
    schema = OrderItemSchema(
        product_id=1,
        quantity=1,
        unit_price=Decimal("100"),
        product_title="Mini Padel Gravity Pro 2024 Gift - grey",
        category_l2="Gifts",
        category_l3="Fun items",
    )

    data = schema.model_dump()
    assert data["category_l2"] == "Gifts"
    assert data["category_l3"] == "Fun items"
    assert data["category_l2_label_ru"] == "Подарки"
    assert data["category_l3_label_ru"] == "Развлекательные товары"
    assert data["display_title"] == "Mini Padel Gravity Pro 2024 Gift"


# Смена Product.category_l2 не меняет уже собранный snapshot.
def test_product_category_change_does_not_change_existing_snapshot() -> None:
    product = _product(category_l2="Gifts", category_l3="Fun items")
    payload = OrderService.__new__(OrderService)._build_order_item_payload(
        cart_item=_cart_item(),
        unit_price=Decimal("4298"),
        product=product,
        variant=None,
    )
    product.category_l2 = "Shorts"
    product.category_l3 = None

    schema = OrderItemSchema(
        product_id=1,
        quantity=1,
        unit_price=Decimal("4298"),
        category_l2=str(payload["category_l2_captured"]),
        category_l3=str(payload["category_l3_captured"]),
    )
    assert schema.category_l2 == "Gifts"
    assert schema.category_l2_label_ru == "Подарки"
    assert schema.category_l3 == "Fun items"


# Без snapshot категория в API пустая.
def test_order_item_schema_without_snapshot_omits_category_labels() -> None:
    schema = OrderItemSchema(
        product_id=1,
        quantity=1,
        unit_price=Decimal("100"),
        product_title="Old item",
    )
    data = schema.model_dump()
    assert data["category_l2"] is None
    assert data["category_l3"] is None
    assert data["category_l2_label_ru"] is None
    assert data["category_l3_label_ru"] is None


# Schema читает captured, не live category_l2.
def test_order_item_schema_reads_captured_alias_not_live_product() -> None:
    item = SimpleNamespace(
        product_id=1,
        variant_id=None,
        quantity=1,
        unit_price=Decimal("100"),
        product_title="Lebron Shorts",
        category_l2_captured="Shorts",
        category_l3_captured=None,
        category_l2="Gifts",
    )
    schema = OrderItemSchema.model_validate(item)
    assert schema.category_l2 == "Shorts"
    assert schema.category_l2_label_ru == "Шорты"


# Shipment item получает тот же snapshot.
def test_shipment_item_uses_order_item_category_snapshot() -> None:
    row = SimpleNamespace(
        id=1,
        supplier_order_id=10,
        status="in_transit",
        status_updated_at=None,
        delivered_at=None,
        supplier_carrier="DHL",
        supplier_tracking_number="CJ-1",
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    item = SimpleNamespace(
        id=101,
        product_title="Lebron Shorts",
        product_title_captured=None,
        product_image_url=None,
        variant_option1=None,
        variant_option1_captured=None,
        variant_option2=None,
        variant_option2_captured=None,
        variant_option3=None,
        variant_option3_captured=None,
        category_l2_captured="Shorts",
        category_l3_captured=None,
    )
    line = SimpleNamespace(order_item_id=101, quantity=1)
    schemas = build_order_shipment_schemas([row], {10: [line]}, [item])
    ship_item = schemas[0].items[0]
    assert isinstance(ship_item, OrderShipmentItemSchema)
    assert ship_item.category_l2 == "Shorts"
    assert ship_item.category_l3 is None
    assert ship_item.category_l2_label_ru == "Шорты"
    assert ship_item.display_title == "Lebron Shorts"
