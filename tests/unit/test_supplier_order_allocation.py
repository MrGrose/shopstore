from decimal import Decimal

import pytest

from src.core.config import settings
from src.services.orders.supplier_orders import (
    OrderItemAllocationView,
    SupplierOrderAllocationError,
    item_allocations_from_rows,
    packing_next_action_hint,
    paid_supplier_order_count_from_snapshot,
    parcel_goods_fill_display,
    parcel_line_qty_control,
    recommend_draft_parcels,
    validate_actual_count_against_paid_snapshot,
    validate_allocation_lines,
    validate_proposed_supplier_order,
    validate_supplier_order_goods_eur,
    validate_unique_supplier_order_item_lines,
)

_ITEM = 123


# Case 1: без allocation remaining = ordered.
def test_allocation_none_remaining_equals_ordered() -> None:
    views = validate_allocation_lines({_ITEM: 5}, [])
    assert views == [
        OrderItemAllocationView(
            order_item_id=_ITEM, ordered_qty=5, allocated_qty=0, remaining_qty=5
        )
    ]


# Case 2: частичный leftover.
def test_allocation_partial_leftover() -> None:
    views = validate_allocation_lines({_ITEM: 5}, [(_ITEM, 2)])
    assert views[0].allocated_qty == 2
    assert views[0].remaining_qty == 3


# Case 3 / split: 2+3 = 5, remaining 0.
def test_allocation_split_fully_allocated() -> None:
    views = validate_allocation_lines({_ITEM: 5}, [(_ITEM, 2), (_ITEM, 3)])
    assert views[0].allocated_qty == 5
    assert views[0].remaining_qty == 0


# Case 4: 3+3 > 5.
def test_allocation_over_split_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="больше штук"):
        validate_allocation_lines({_ITEM: 5}, [(_ITEM, 3), (_ITEM, 3)])


# Case 5: одна line на весь qty.
def test_allocation_single_full_line() -> None:
    views = validate_allocation_lines({_ITEM: 5}, [(_ITEM, 5)])
    assert views[0].remaining_qty == 0


# Case 6: одна line больше qty.
def test_allocation_single_over_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="больше штук"):
        validate_allocation_lines({_ITEM: 5}, [(_ITEM, 6)])


# Case 7: qty 0.
def test_allocation_zero_qty_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="больше нуля"):
        validate_allocation_lines({_ITEM: 5}, [(_ITEM, 0)])


# Case 8: qty отрицательный.
def test_allocation_negative_qty_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="больше нуля"):
        validate_allocation_lines({_ITEM: 5}, [(_ITEM, -1)])


# Split reject: 2+4 > 5.
def test_allocation_split_over_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="больше штук"):
        validate_allocation_lines({_ITEM: 5}, [(_ITEM, 2), (_ITEM, 4)])


# Read-path helper не бросает на leftover.
def test_item_allocations_from_rows_reports_remaining() -> None:
    views = item_allocations_from_rows([(_ITEM, 5)], [(_ITEM, 2)])
    assert views[0].remaining_qty == 3


# Unique (so, item): вторая line на ту же пару запрещена.
def test_unique_so_item_duplicate_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="один раз"):
        validate_unique_supplier_order_item_lines([(10, _ITEM), (10, _ITEM)])


def test_unique_so_item_split_across_orders_allowed() -> None:
    validate_unique_supplier_order_item_lines([(10, _ITEM), (11, _ITEM)])


# Case 9–12: cap Phase 1, не новая формула.
@pytest.mark.parametrize(
    "goods,ok",
    [
        (Decimal("270.00"), True),
        (Decimal("270.01"), True),
        (Decimal("270.02"), False),
        (Decimal("300.00"), False),
    ],
)
def test_supplier_order_goods_cap(
    monkeypatch: pytest.MonkeyPatch, goods: Decimal, ok: bool
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    if ok:
        validate_supplier_order_goods_eur(goods)
        return
    with pytest.raises(SupplierOrderAllocationError, match="превышает лимит"):
        validate_supplier_order_goods_eur(goods)


# Proposed SO: unique item внутри SO + leftover + cap.
def test_proposed_supplier_order_split_with_existing() -> None:
    views = validate_proposed_supplier_order(
        {_ITEM: 5},
        [(_ITEM, 2)],
        [(_ITEM, 3, Decimal("50.00"))],
    )
    assert views[0].allocated_qty == 5
    assert views[0].remaining_qty == 0


def test_proposed_supplier_order_duplicate_item_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="один раз"):
        validate_proposed_supplier_order(
            {_ITEM: 5},
            [],
            [(_ITEM, 2, Decimal("10")), (_ITEM, 3, Decimal("10"))],
        )


def test_proposed_supplier_order_goods_over_cap_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    with pytest.raises(SupplierOrderAllocationError, match="превышает лимит"):
        validate_proposed_supplier_order(
            {_ITEM: 2},
            [],
            [(_ITEM, 2, Decimal("140.00"))],
        )


# Paid N из snapshot 3×34=102, не из ceil(500/270.01)=2.
def test_paid_count_from_snapshot_not_live_ceil() -> None:
    assert (
        paid_supplier_order_count_from_snapshot(Decimal("102.00"), Decimal("34.00"))
        == 3
    )
    assert (
        paid_supplier_order_count_from_snapshot(Decimal("68.00"), Decimal("34.00")) == 2
    )


def test_unpaid_actual_above_minimum_allowed() -> None:
    validate_actual_count_against_paid_snapshot(
        3, Decimal("68.00"), Decimal("34.00"), is_paid=False
    )


def test_paid_actual_above_snapshot_n_rejected() -> None:
    with pytest.raises(SupplierOrderAllocationError, match="После оплаты"):
        validate_actual_count_against_paid_snapshot(
            4, Decimal("102.00"), Decimal("34.00"), is_paid=True
        )


def test_paid_actual_equal_snapshot_n_allowed() -> None:
    validate_actual_count_against_paid_snapshot(
        3, Decimal("102.00"), Decimal("34.00"), is_paid=True
    )


# Display-only: cap 270.01 и остаток, без смены инварианта.
def test_parcel_goods_fill_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    cap, remaining, percent = parcel_goods_fill_display(Decimal("64.62"))
    assert cap == Decimal("270.01")
    assert remaining == Decimal("205.39")
    assert percent == 24


def test_packing_next_action_hint_create_when_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    hint = packing_next_action_hint(
        leftover_qty=1,
        min_leftover_unit=Decimal("80.00"),
        draft_goods=[Decimal("200.00")],
        can_create=True,
        block=None,
    )
    assert hint is not None
    assert "следующую" in hint


def test_packing_next_action_hint_fill_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    hint = packing_next_action_hint(
        leftover_qty=1,
        min_leftover_unit=Decimal("64.62"),
        draft_goods=[Decimal("64.62")],
        can_create=True,
        block=None,
    )
    assert hint is not None
    assert "текущую посылку" in hint


def test_parcel_line_qty_control_blocks_unit_above_remaining_eur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    max_qty, plus_disabled, minus_disabled, hint = parcel_line_qty_control(
        1, 1, Decimal("150.00"), Decimal("55.39")
    )
    assert max_qty == 1
    assert plus_disabled is True
    assert minus_disabled is False
    assert hint == "Не помещается в эту посылку"


def test_parcel_line_qty_control_allows_exact_cap_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    max_qty, plus_disabled, minus_disabled, hint = parcel_line_qty_control(
        1, 1, Decimal("64.62"), Decimal("64.62")
    )
    assert max_qty == 2
    assert plus_disabled is False
    assert minus_disabled is False
    assert hint is None


def test_recommend_draft_parcels_splits_expensive_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    bins = recommend_draft_parcels(
        [
            (1, 5, Decimal("100.00")),
        ]
    )
    assert [[(item, qty) for item, qty, _unit in parcel] for parcel in bins] == [
        [(1, 2)],
        [(1, 2)],
        [(1, 1)],
    ]
    bins_again = recommend_draft_parcels([(1, 5, Decimal("100.00"))])
    assert bins_again == bins


def test_recommend_draft_parcels_fills_current_then_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    bins = recommend_draft_parcels(
        [
            (10, 1, Decimal("200.00")),
            (11, 2, Decimal("80.00")),
        ]
    )
    goods = [
        sum((Decimal(qty) * unit for _id, qty, unit in parcel), Decimal("0.00"))
        for parcel in bins
    ]
    assert len(bins) == 2
    assert goods[0] == Decimal("200.00")
    assert goods[1] == Decimal("160.00")
    assert all(g <= Decimal("270.01") for g in goods)


def test_recommend_draft_parcels_empty() -> None:
    assert recommend_draft_parcels([]) == []


def test_recommend_merges_small_remainder_into_earlier_bin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    leftover = [
        (1, 1, Decimal("44.50")),
        (2, 1, Decimal("243.61")),
        (3, 1, Decimal("255.33")),
        (4, 1, Decimal("259.36")),
        (5, 1, Decimal("11.34")),
    ]
    bins = recommend_draft_parcels(leftover)
    goods = [
        sum((Decimal(count) * unit for _id, count, unit in lines), Decimal("0.00"))
        for lines in bins
    ]
    assert len(bins) == 4
    assert Decimal("11.34") not in goods
    assert max(goods) <= Decimal("270.01")
    assert sum(goods) == Decimal("814.14")
    qty = {}
    for lines in bins:
        for item_id, count, _unit in lines:
            qty[item_id] = qty.get(item_id, 0) + count
    assert qty == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}
    assert bins == recommend_draft_parcels(leftover)
    assert Decimal("266.67") in goods or Decimal("254.95") in goods
