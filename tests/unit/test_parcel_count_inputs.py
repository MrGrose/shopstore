from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from src.core.config import settings
from src.core.order_limits import (
    estimate_supplier_orders,
    live_supplier_lines,
    recommend_draft_parcels,
)
from src.models.order import OrderItem
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import _captured_parcel_lines


def _cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))


def _ids(lines: list[tuple[int, int, Decimal]] | None) -> list[int]:
    assert lines is not None
    return [item_id for item_id, _qty, _unit in lines]


# --- live cart / checkout ---


# Синтетический id на каждую строку входа. Пропуск не создаёт вторую строку.
def test_live_lines_are_unique_and_stable() -> None:
    product = SimpleNamespace(supplier_price_eur=Decimal("140.00"))
    items = [
        SimpleNamespace(product_id=9, quantity=1),
        SimpleNamespace(product_id=8, quantity=0),
        SimpleNamespace(product_id=9, quantity=2),
        SimpleNamespace(product_id=7, quantity=1),
    ]
    lines = live_supplier_lines(items, {9: product})
    again = live_supplier_lines(items, {9: product})
    assert lines == again
    assert lines == [
        (1, 1, Decimal("140.00")),
        (2, 2, Decimal("140.00")),
    ]
    assert len(_ids(lines)) == len(set(_ids(lines)))


def test_live_lines_parcel_count_matches_calculator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap(monkeypatch)
    product = SimpleNamespace(supplier_price_eur=Decimal("140"))
    items = [SimpleNamespace(product_id=1, quantity=1) for _ in range(5)]
    lines = live_supplier_lines(items, {1: product})
    assert _ids(lines) == [1, 2, 3, 4, 5]
    goods = Decimal("700")
    estimate = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines)
    assert estimate.minimum_orders == len(recommend_draft_parcels(lines)) == 5


# --- captured order items ---


def test_captured_lines_use_order_item_id_once() -> None:
    items = [
        SimpleNamespace(
            id=10, quantity=1, supplier_price_eur_captured=Decimal("140.00")
        ),
        SimpleNamespace(
            id=11, quantity=0, supplier_price_eur_captured=Decimal("200.00")
        ),
        SimpleNamespace(
            id=12, quantity=3, supplier_price_eur_captured=Decimal("80.00")
        ),
    ]
    payload = cast(list[OrderItem], items)
    lines = _captured_parcel_lines(payload)
    assert lines == _captured_parcel_lines(payload)
    assert lines == [
        (10, 1, Decimal("140.00")),
        (12, 3, Decimal("80.00")),
    ]
    assert len(_ids(lines)) == len(set(_ids(lines)))


def test_captured_lines_parcel_count_matches_calculator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap(monkeypatch)
    items = [
        SimpleNamespace(
            id=item_id,
            quantity=1,
            supplier_price_eur_captured=Decimal("140.00"),
        )
        for item_id in range(1, 6)
    ]
    lines = _captured_parcel_lines(cast(list[OrderItem], items))
    estimate = estimate_supplier_orders(
        Decimal("700"),
        Decimal("34"),
        supplier_lines=lines,
    )
    assert estimate.minimum_orders == len(recommend_draft_parcels(lines)) == 5


# --- admin display ---


def test_display_keeps_distinct_item_ids_and_packer_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap(monkeypatch)
    items = [
        SimpleNamespace(
            id=item_id,
            product_id=1,
            quantity=1,
            supplier_price_eur_captured=Decimal("140.00"),
        )
        for item_id in (4, 9, 2, 7, 3)
    ]
    items.append(
        SimpleNamespace(
            id=99,
            product_id=1,
            quantity=0,
            supplier_price_eur_captured=Decimal("140.00"),
        )
    )
    tracking = SimpleNamespace(
        supplier_cost_eur_snapshot=Decimal("1.00"),
        delivery_fee_eur_snapshot=Decimal("0"),
    )
    display = OrderService._supplier_order_estimate_display(tracking, items, {})
    again = OrderService._supplier_order_estimate_display(tracking, items, {})
    assert display == again
    int_keys = [key for key in display["item_eur_by_id"] if isinstance(key, int)]
    assert sorted(int_keys) == [2, 3, 4, 7, 9]
    expected = [(item.id, 1, Decimal("140.00")) for item in items if item.quantity > 0]
    estimate = estimate_supplier_orders(
        Decimal("700"),
        Decimal("0"),
        supplier_lines=expected,
    )
    assert display["minimum_orders"] == estimate.minimum_orders == 5
