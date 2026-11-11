from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.core.config import settings
from src.core.order_limits import (
    SupplierOrderAllocationError,
    calculate_customs_duty_rub,
    calculate_supplier_cost_eur,
    customs_duty_notice,
    estimate_supplier_orders,
    is_supplier_unit_storefront_allowed,
    max_supplier_goods_eur,
    recommend_draft_parcels,
    required_parcel_count,
)
from src.schemas.order import DeliveryAddressCreate, normalize_ru_mobile_phone
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import unpaid_delivery_eur
from src.services.pricing.calculator import calculate_delivery_rub


class _Item:
    def __init__(self, product_id: int, quantity: int) -> None:
        self.product_id = product_id
        self.quantity = quantity


class _Product:
    def __init__(self, supplier_price_eur: float | Decimal) -> None:
        self.supplier_price_eur = supplier_price_eur


def test_calculate_supplier_cost_eur_sums_items() -> None:
    items = [_Item(1, 2), _Item(2, 1)]
    products = {1: _Product("10.5"), 2: _Product("5")}
    assert calculate_supplier_cost_eur(items, products) == Decimal("26.0")


def test_max_supplier_goods_eur(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    assert max_supplier_goods_eur() == Decimal("270.01")


@pytest.mark.parametrize(
    "goods,orders,supplier_shipping,client_shipping",
    [
        (Decimal("0"), 0, Decimal("0.00"), Decimal("0.00")),
        (Decimal("-1"), 0, Decimal("0.00"), Decimal("0.00")),
        (Decimal("100"), 1, Decimal("29.99"), Decimal("34.00")),
        (Decimal("270.01"), 1, Decimal("29.99"), Decimal("34.00")),
        (Decimal("270.02"), 2, Decimal("59.98"), Decimal("68.00")),
        (Decimal("400"), 2, Decimal("59.98"), Decimal("68.00")),
        (Decimal("540.02"), 2, Decimal("59.98"), Decimal("68.00")),
        (Decimal("540.03"), 3, Decimal("89.97"), Decimal("102.00")),
        (Decimal("700"), 3, Decimal("89.97"), Decimal("102.00")),
        (Decimal("1000"), 4, Decimal("119.96"), Decimal("136.00")),
    ],
)
def test_estimate_supplier_orders(
    monkeypatch: pytest.MonkeyPatch,
    goods: Decimal,
    orders: int,
    supplier_shipping: Decimal,
    client_shipping: Decimal,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    estimate = estimate_supplier_orders(goods, Decimal("34"))
    assert estimate.minimum_orders == orders
    assert estimate.supplier_shipping_eur == supplier_shipping
    assert estimate.client_shipping_eur == client_shipping
    assert estimate.max_goods_eur == Decimal("270.01")


def test_supplier_unit_storefront_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    assert is_supplier_unit_storefront_allowed(Decimal("270.00")) is True
    assert is_supplier_unit_storefront_allowed(Decimal("270.01")) is True
    assert is_supplier_unit_storefront_allowed(Decimal("270.02")) is False


def test_customs_duty_formula() -> None:
    assert calculate_customs_duty_rub(Decimal("200"), Decimal("100")) == Decimal("0")
    assert calculate_customs_duty_rub(Decimal("201"), Decimal("100")) == Decimal("15")
    assert calculate_customs_duty_rub(Decimal("300"), Decimal("95.5")) == Decimal(
        "1433"
    )


def test_customs_duty_notice() -> None:
    eur_rate = Decimal("100")
    assert customs_duty_notice(Decimal("0"), eur_rate) is None
    notice = customs_duty_notice(Decimal("4667"), eur_rate)
    assert notice is not None
    assert "4 667 ₽" in notice
    assert "20 000 ₽" in notice
    assert "200€" not in notice


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+79991234567", "+79991234567"),
        ("89991234567", "+79991234567"),
        ("9991234567", "+79991234567"),
    ],
)
def test_normalize_ru_mobile_phone(raw: str, expected: str) -> None:
    assert normalize_ru_mobile_phone(raw) == expected


def test_delivery_phone_validation() -> None:
    payload = DeliveryAddressCreate(
        last_name="Ivanov",
        first_name="Ivan",
        street="Tverskaya",
        house="10",
        city="Moscow",
        postal_code="101000",
        phone="+79991234567",
    )
    assert payload.phone == "+79991234567"


def test_delivery_phone_invalid() -> None:
    with pytest.raises(ValueError):
        DeliveryAddressCreate(
            last_name="Ivanov",
            first_name="Ivan",
            street="Tverskaya",
            house="10",
            city="Moscow",
            postal_code="101000",
            phone="123",
        )


def test_client_delivery_snapshot_for_400_goods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    estimate = estimate_supplier_orders(Decimal("400"), Decimal("34"))
    assert estimate.minimum_orders == 2
    assert estimate.client_shipping_eur == Decimal("68.00")
    assert estimate.supplier_shipping_eur == Decimal("59.98")
    rate = Decimal("100")
    delivery_rub = calculate_delivery_rub(estimate.client_shipping_eur, rate)
    assert delivery_rub == Decimal("6800.00")
    # 29.99×N не входит в клиентскую доставку.
    assert delivery_rub != calculate_delivery_rub(estimate.supplier_shipping_eur, rate)


def test_single_order_client_delivery_matches_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    estimate = estimate_supplier_orders(Decimal("100"), Decimal("34"))
    assert estimate.minimum_orders == 1
    assert estimate.client_shipping_eur == Decimal("34.00")


# Непустая корзина с нулевой закупкой всё равно один заказ TP.
def test_estimate_zero_goods_with_items_counts_one_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    estimate = estimate_supplier_orders(Decimal("0"), Decimal("34"), item_count=1)
    assert estimate.minimum_orders == 1
    assert estimate.client_shipping_eur == Decimal("34.00")
    assert estimate.supplier_shipping_eur == Decimal("29.99")


def test_item_supplier_unit_eur_prefers_captured() -> None:
    item = SimpleNamespace(supplier_price_eur_captured=Decimal("12.50"), product_id=1)
    product = SimpleNamespace(supplier_price_eur=Decimal("99.00"))
    assert OrderService._item_supplier_unit_eur(item, {1: product}) == Decimal("12.50")


def test_item_supplier_unit_eur_falls_back_to_live_price() -> None:
    item = SimpleNamespace(supplier_price_eur_captured=None, product_id=1)
    product = SimpleNamespace(supplier_price_eur=Decimal("40.00"))
    assert OrderService._item_supplier_unit_eur(item, {1: product}) == Decimal("40.00")


def test_supplier_order_estimate_display_uses_items_and_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    tracking = SimpleNamespace(
        supplier_cost_eur_snapshot=Decimal("10.00"),
        delivery_fee_eur_snapshot=Decimal("68.00"),
    )
    item = SimpleNamespace(
        id=7,
        product_id=1,
        quantity=2,
        supplier_price_eur_captured=Decimal("200.00"),
    )
    display = OrderService._supplier_order_estimate_display(tracking, [item], {})
    assert display["minimum_orders"] == 2
    assert display["client_shipping_eur"] == "68.00"
    assert display["goods_cost_eur"] == "400.00"
    assert display["item_eur_by_id"][7] == "400.00"
    assert display["item_eur_by_id"]["7"] == "400.00"


def _cap_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))


# Без линий N остаётся ceil(goods / cap).
def test_estimate_without_lines_keeps_ceil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    omitted = estimate_supplier_orders(Decimal("400"), Decimal("34"))
    explicit_none = estimate_supplier_orders(
        Decimal("400"),
        Decimal("34"),
        supplier_lines=None,
    )
    assert omitted.minimum_orders == 2
    assert explicit_none.minimum_orders == omitted.minimum_orders
    assert omitted.client_shipping_eur == Decimal("68.00")


# Непустые линии дают тот же N, что len(recommend_draft_parcels).
def test_estimate_lines_match_packer(monkeypatch: pytest.MonkeyPatch) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 2, Decimal("200.00"))]
    estimate = estimate_supplier_orders(
        Decimal("400"),
        Decimal("34"),
        supplier_lines=lines,
    )
    assert estimate.minimum_orders == len(recommend_draft_parcels(lines))


# Пустой список не обнуляет N, если goods уже больше нуля.
def test_estimate_empty_lines_keep_ceil_for_positive_goods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    empty = estimate_supplier_orders(
        Decimal("400"),
        Decimal("34"),
        supplier_lines=[],
    )
    omitted = estimate_supplier_orders(Decimal("400"), Decimal("34"))
    assert empty.minimum_orders == omitted.minimum_orders
    assert empty.minimum_orders == 2


# Дорогие единицы: ceil занижает, пакер — источник N.
def test_estimate_lines_use_packer_when_ceil_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [
        (410, 1, Decimal("170.55")),
        (411, 1, Decimal("120.13")),
        (412, 1, Decimal("127.69")),
        (413, 1, Decimal("165.50")),
        (414, 1, Decimal("189.03")),
    ]
    goods = Decimal("772.90")
    by_ceil = estimate_supplier_orders(goods, Decimal("34"))
    by_lines = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines)
    packed = len(recommend_draft_parcels(lines))
    assert by_ceil.minimum_orders == 3
    assert packed == 4
    assert by_lines.minimum_orders == packed
    assert by_lines.client_shipping_eur == Decimal("136.00")


# Единица выше капа по-прежнему ошибка пакера, не тихий ceil.
def test_estimate_over_cap_line_raises_allocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    with pytest.raises(
        SupplierOrderAllocationError, match="дороже лимита одной посылки"
    ):
        estimate_supplier_orders(
            Decimal("270.02"),
            Decimal("34"),
            supplier_lines=[(1, 1, Decimal("270.02"))],
        )


def _forbid_packer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("packer must not run")

    monkeypatch.setattr(
        "src.core.order_limits.recommend_draft_parcels",
        _forbidden,
    )


def _goods(lines: list[tuple[int, int, Decimal]]) -> Decimal:
    return sum(
        (Decimal(qty) * unit for _item_id, qty, unit in lines),
        Decimal("0"),
    )


def _assert_estimate_matches_packer(
    lines: list[tuple[int, int, Decimal]],
    expected_count: int,
) -> None:
    expected = len(recommend_draft_parcels(lines))
    assert expected == expected_count
    assert required_parcel_count(lines) == expected
    estimate = estimate_supplier_orders(
        _goods(lines),
        Decimal("34"),
        supplier_lines=lines,
    )
    assert estimate.minimum_orders == expected


# --- fallback / empty ---


# supplier_lines=None: нулевая корзина и ceil без вызова пакера.
@pytest.mark.parametrize(
    ("goods", "expected_orders"),
    [
        (Decimal("0"), 0),
        (Decimal("540.03"), 3),
    ],
)
def test_estimate_none_lines_uses_ceil_without_packer(
    monkeypatch: pytest.MonkeyPatch,
    goods: Decimal,
    expected_orders: int,
) -> None:
    _cap_settings(monkeypatch)
    _forbid_packer(monkeypatch)
    estimate = estimate_supplier_orders(
        goods,
        Decimal("34"),
        item_count=0,
        supplier_lines=None,
    )
    assert estimate.minimum_orders == expected_orders


# Пустой список при нулевых goods — тот же ноль, пакер не вызывается.
def test_estimate_empty_lines_zero_goods_is_zero_without_packer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    _forbid_packer(monkeypatch)
    estimate = estimate_supplier_orders(
        Decimal("0"),
        Decimal("34"),
        item_count=0,
        supplier_lines=[],
    )
    assert estimate.minimum_orders == 0
    assert estimate.client_shipping_eur == Decimal("0.00")


# Пустой список при goods > 0 равен None-пути и не обнуляет N.
def test_estimate_empty_lines_match_none_without_packer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    _forbid_packer(monkeypatch)
    goods = Decimal("700")
    empty = estimate_supplier_orders(
        goods,
        Decimal("34"),
        item_count=5,
        supplier_lines=[],
    )
    omitted = estimate_supplier_orders(goods, Decimal("34"), item_count=5)
    assert empty.minimum_orders == omitted.minimum_orders
    assert empty.minimum_orders == 3
    assert empty.minimum_orders != 0
    assert empty.client_shipping_eur == omitted.client_shipping_eur


# --- line-based estimate ---


@pytest.mark.parametrize(
    ("units", "expected_count"),
    [
        ([Decimal("100")], 1),
        ([Decimal("270.01")], 1),
        ([Decimal("100"), Decimal("120")], 1),
        ([Decimal("140"), Decimal("140")], 2),
        ([Decimal("100"), Decimal("100"), Decimal("100")], 2),
        ([Decimal("100"), Decimal("80"), Decimal("70")], 1),
    ],
    ids=[
        "100",
        "exact-cap-unit",
        "100-plus-120",
        "two-140",
        "three-100",
        "100-80-70",
    ],
)
def test_estimate_basic_lines_match_packer(
    monkeypatch: pytest.MonkeyPatch,
    units: list[Decimal],
    expected_count: int,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(index, 1, unit) for index, unit in enumerate(units, start=1)]
    _assert_estimate_matches_packer(lines, expected_count)


# --- ceil versus packing ---


# 140+140 > cap, поэтому каждая единица — отдельная посылка, не ceil(700).
def test_five_units_of_140_estimate_follows_packer_not_ceil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(item_id, 1, Decimal("140")) for item_id in range(1, 6)]
    goods = Decimal("700")
    legacy = estimate_supplier_orders(goods, Decimal("34"))
    packed = len(recommend_draft_parcels(lines))
    by_lines = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines)
    assert legacy.minimum_orders == 3
    assert packed == 5
    assert by_lines.minimum_orders == packed
    assert required_parcel_count(lines) == packed


# 200+200 > cap: ceil(1000) = 4, пакер = 5.
def test_five_units_of_200_estimate_follows_packer_not_ceil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(item_id, 1, Decimal("200")) for item_id in range(1, 6)]
    goods = Decimal("1000")
    legacy = estimate_supplier_orders(goods, Decimal("34"))
    packed = len(recommend_draft_parcels(lines))
    by_lines = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines)
    assert legacy.minimum_orders == 4
    assert packed == 5
    assert by_lines.minimum_orders == packed
    assert required_parcel_count(lines) == packed


# --- quantity / split ---


# 3×100: две штуки влезают, третья уходит в следующую посылку.
def test_quantity_three_units_of_100_splits_across_parcels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 3, Decimal("100"))]
    bins = recommend_draft_parcels(lines)
    qtys = sorted(qty for parcel in bins for _item_id, qty, _unit in parcel)
    assert qtys == [1, 2]
    assert all(item_id == 1 for parcel in bins for item_id, _qty, _unit in parcel)
    _assert_estimate_matches_packer(lines, 2)


# 5×140 на одной строке: quantity режется, строка не считается неделимой.
def test_quantity_five_units_of_140_splits_one_per_parcel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 5, Decimal("140"))]
    bins = recommend_draft_parcels(lines)
    assert len(bins) == 5
    assert [(item_id, qty) for parcel in bins for item_id, qty, _unit in parcel] == [
        (1, 1)
    ] * 5
    _assert_estimate_matches_packer(lines, 5)


# --- cap boundaries ---


def test_cap_exact_sum_stays_one_parcel(monkeypatch: pytest.MonkeyPatch) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 1, Decimal("135.00")), (2, 1, Decimal("135.01"))]
    bins = recommend_draft_parcels(lines)
    goods = sum(
        (Decimal(qty) * unit for parcel in bins for _item_id, qty, unit in parcel),
        Decimal("0"),
    )
    assert goods == Decimal("270.01")
    _assert_estimate_matches_packer(lines, 1)


def test_cap_one_cent_over_needs_two_parcels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 1, Decimal("135.01")), (2, 1, Decimal("135.01"))]
    _assert_estimate_matches_packer(lines, 2)


# --- over-cap ---


# Непустые линии с единицей выше cap не падают в legacy ceil.
def test_estimate_over_cap_line_among_others_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(1, 1, Decimal("100.00")), (2, 1, Decimal("270.02"))]
    with pytest.raises(
        SupplierOrderAllocationError, match="Товар дороже лимита одной посылки"
    ):
        estimate_supplier_orders(
            Decimal("370.02"),
            Decimal("34"),
            supplier_lines=lines,
        )


# --- sort / required count ---


# Валидный вход — одна строка на item_id. Callers так и строят линии:
# OrderItem.id либо синтетический уникальный id. item_id в сортировке только
# tie-breaker после цены и суммы строки. Одинаковый id с разными ценами
# контрактом не считается: merge в bin оставляет первую цену.
def test_packer_count_is_independent_of_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines_a = [
        (3, 1, Decimal("100")),
        (1, 2, Decimal("140")),
        (2, 1, Decimal("80")),
    ]
    lines_b = list(reversed(lines_a))
    goods = _goods(lines_a)
    count_a = len(recommend_draft_parcels(lines_a))
    count_b = len(recommend_draft_parcels(lines_b))
    assert count_a == count_b
    assert required_parcel_count(lines_a) == count_a
    assert required_parcel_count(lines_b) == count_b
    estimate_a = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines_a)
    estimate_b = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines_b)
    assert estimate_a.minimum_orders == count_a
    assert estimate_b.minimum_orders == count_b


# --- delivery ---


# 5×140: delivery берёт N=5, не legacy ceil=3.
def test_line_based_delivery_uses_packer_count_not_ceil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cap_settings(monkeypatch)
    lines = [(item_id, 1, Decimal("140")) for item_id in range(1, 6)]
    goods = Decimal("700")
    by_ceil = estimate_supplier_orders(goods, Decimal("34"))
    by_lines = estimate_supplier_orders(goods, Decimal("34"), supplier_lines=lines)
    assert by_ceil.minimum_orders == 3
    assert by_lines.minimum_orders == 5
    assert by_lines.client_shipping_eur == Decimal("170.00")
    assert by_ceil.client_shipping_eur == Decimal("102.00")
    assert unpaid_delivery_eur(0, by_lines.minimum_orders, Decimal("34")) == (
        Decimal("170.00")
    )
    assert unpaid_delivery_eur(1, by_lines.minimum_orders, Decimal("34")) == (
        Decimal("170.00")
    )
