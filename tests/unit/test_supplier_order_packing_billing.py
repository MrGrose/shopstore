from decimal import Decimal

from src.services.orders.supplier_orders import (
    SupplierOrderLineView,
    billed_supplier_order_count,
    format_supplier_order_place_copy,
    unpaid_delivery_eur,
)


# Case 9: goods floor, actual=minimum → 1×34.
def test_unpaid_delivery_actual_equals_minimum() -> None:
    assert billed_supplier_order_count(1, 1) == 1
    assert unpaid_delivery_eur(1, 1, Decimal("34")) == Decimal("34.00")


# Case 10: actual below new minimum → billed=minimum.
def test_unpaid_delivery_follows_higher_minimum() -> None:
    assert billed_supplier_order_count(1, 2) == 2
    assert unpaid_delivery_eur(1, 2, Decimal("34")) == Decimal("68.00")


# Case 11: actual above minimum → billed=actual.
def test_unpaid_delivery_follows_higher_actual() -> None:
    assert billed_supplier_order_count(3, 2) == 3
    assert unpaid_delivery_eur(3, 2, Decimal("34")) == Decimal("102.00")


# Пустой draft всё равно входит в actual, поэтому N растёт.
def test_empty_draft_counts_in_billed_n() -> None:
    assert billed_supplier_order_count(3, 2) == 3


# Payload copy берёт qty линии SO, не quantity OrderItem.
def test_place_copy_uses_line_quantity() -> None:
    view = SupplierOrderLineView(
        order_item_id=1,
        quantity=2,
        unit_supplier_eur=Decimal("10.00"),
        goods_eur=Decimal("20.00"),
        product_title="Racket",
    )
    text = format_supplier_order_place_copy(
        1, [view], {}, Decimal("20.00"), Decimal("29.99")
    )
    assert "× 2 × 10.00 EUR" in text
    assert "× 5 ×" not in text
