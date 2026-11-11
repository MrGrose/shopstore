from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.services.orders.supplier_availability.client import (
    SupplierVariantCheckResult,
    SupplierVariantSnapshot,
)
from src.services.orders.supplier_availability.service import (
    VERDICT_MANUAL,
    VERDICT_READY,
    composition_hash,
    compute_item_verdict,
    compute_order_verdict,
    quantity_sufficient,
    snapshot_is_fresh,
    snapshot_matches_composition,
    validate_supplier_snapshot_for_admin_action,
)
from src.utils.datetime_fmt import utc_now_naive


def _item(order_item_id: int = 1, product_id: int = 10, qty: int = 1) -> MagicMock:
    item = MagicMock()
    item.id = order_item_id
    item.product_id = product_id
    item.variant_id = 5
    item.quantity = qty
    item.variant_external_id_captured = "910001"
    item.variant_sku_captured = "SKU-1"
    return item


def _check_result(
    *,
    found: bool = True,
    available: bool = True,
    inventory: int | None = 10,
    price: str = "15.00",
) -> SupplierVariantCheckResult:
    snapshot = None
    if found:
        snapshot = SupplierVariantSnapshot(
            variant_id="910001",
            sku="SKU-1",
            available=available,
            inventory_quantity=inventory,
            current_price_eur=price,
            member_price_eur=price,
        )
    return SupplierVariantCheckResult(
        product_url="https://www.supplier-demo.com/products/demo",
        requested_variant_id="910001",
        requested_sku="SKU-1",
        found=found,
        snapshot=snapshot,
        session_valid=True,
        html_validation=None,
        http_status=200,
        latency_ms=100,
        challenge=None,
        error=None,
    )


def test_quantity_sufficient_with_inventory() -> None:
    assert quantity_sufficient(2, available=True, inventory_quantity=5) is True
    assert quantity_sufficient(2, available=True, inventory_quantity=1) is False


def test_quantity_sufficient_single_without_inventory() -> None:
    assert quantity_sufficient(1, available=True, inventory_quantity=None) is True
    assert quantity_sufficient(2, available=True, inventory_quantity=None) is None


def test_compute_order_verdict_ready() -> None:
    row = compute_item_verdict(
        required_quantity=1,
        check=_check_result(),
        captured_price_eur=Decimal("14.00"),
    )
    assert compute_order_verdict([row]) == VERDICT_READY


def test_compute_order_verdict_manual_when_not_found() -> None:
    row = compute_item_verdict(
        required_quantity=1,
        check=_check_result(found=False),
        captured_price_eur=None,
    )
    assert compute_order_verdict([row]) == VERDICT_MANUAL


def test_compute_order_verdict_manual_on_insufficient_qty() -> None:
    row = compute_item_verdict(
        required_quantity=3,
        check=_check_result(inventory=1),
        captured_price_eur=Decimal("15.00"),
    )
    assert row["needs_manual_review"] is True
    assert compute_order_verdict([row]) == VERDICT_MANUAL


def test_composition_hash_stable() -> None:
    first = composition_hash([_item()])
    second = composition_hash([_item()])
    assert first == second


def test_snapshot_matches_composition() -> None:
    assert snapshot_matches_composition({"composition_hash": "abc"}, "abc") is True
    assert snapshot_matches_composition({"composition_hash": "abc"}, "xyz") is False


def test_snapshot_is_fresh() -> None:
    now = utc_now_naive()
    snapshot = {
        "expires_at": (now.replace(microsecond=0)).isoformat(),
    }
    assert snapshot_is_fresh(snapshot, now=now.replace(microsecond=0)) is True


def test_validate_supplier_snapshot_rejects_stale() -> None:
    now = utc_now_naive()
    order = MagicMock()
    order.supplier_availability_json = {
        "checked_at": (now - timedelta(minutes=10)).isoformat(),
        "expires_at": (now - timedelta(minutes=1)).isoformat(),
        "composition_hash": composition_hash([_item()]),
    }
    with pytest.raises(ValueError, match="устарел"):
        validate_supplier_snapshot_for_admin_action(order, [_item()])


def test_validate_supplier_snapshot_rejects_composition_change() -> None:
    now = utc_now_naive()
    order = MagicMock()
    order.supplier_availability_json = {
        "checked_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "composition_hash": "stale-hash",
    }
    with pytest.raises(ValueError, match="Состав заказа изменился"):
        validate_supplier_snapshot_for_admin_action(order, [_item()])


def test_validate_supplier_snapshot_allows_fresh_match() -> None:
    now = utc_now_naive()
    items = [_item()]
    order = MagicMock()
    order.supplier_availability_json = {
        "checked_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "composition_hash": composition_hash(items),
    }
    validate_supplier_snapshot_for_admin_action(order, items)


def test_compute_item_verdict_prefers_current_over_member_for_delta() -> None:
    snapshot = SupplierVariantSnapshot(
        variant_id="1",
        sku="X",
        available=True,
        inventory_quantity=3,
        current_price_eur="189.03",
        member_price_eur="252.06",
    )
    check = SupplierVariantCheckResult(
        product_url="https://example.com/p",
        requested_variant_id="1",
        requested_sku="X",
        found=True,
        snapshot=snapshot,
        session_valid=True,
        html_validation=None,
        http_status=200,
        latency_ms=1,
        challenge=None,
        error=None,
    )
    row = compute_item_verdict(1, check, Decimal("189.03"))
    assert row["supplier_price_eur"] == "189.03"
    assert row["eur_delta_abs"] == "0.00"


def test_compute_item_verdict_no_member_price_skips_public_fallback() -> None:
    snapshot = SupplierVariantSnapshot(
        variant_id="1",
        sku="X",
        available=True,
        inventory_quantity=3,
        current_price_eur="99.99",
        member_price_eur=None,
    )
    check = SupplierVariantCheckResult(
        product_url="https://example.com/p",
        requested_variant_id="1",
        requested_sku="X",
        found=True,
        snapshot=snapshot,
        session_valid=True,
        html_validation="no_member_price",
        http_status=200,
        latency_ms=1,
        challenge=None,
        error=None,
    )
    row = compute_item_verdict(1, check, Decimal("50.00"))
    assert row["supplier_price_eur"] is None
    assert row["needs_manual_review"] is True
