from src.models.product import Product, ProductVariant
from src.services.cart_variant_resolve import resolve_cart_variant_id
from src.utils.product_availability import (
    pick_buyable_variant_id,
    variant_available_qty,
)


def _variant(
    variant_id: int,
    *,
    inventory: int = 5,
    available: bool = True,
) -> ProductVariant:
    return ProductVariant(
        id=variant_id,
        product_id=1,
        inventory_quantity=inventory,
        available=available,
    )


def _product(*variants: ProductVariant) -> Product:
    product = Product(id=1, title="Demo", brand="Brand", is_active=True)
    product.variants = list(variants)
    return product


def test_resolve_cart_variant_id_returns_explicit_variant() -> None:
    product = _product(_variant(10), _variant(20))

    assert resolve_cart_variant_id(product, 20) == 20


def test_resolve_cart_variant_id_returns_single_variant() -> None:
    product = _product(_variant(7))

    assert resolve_cart_variant_id(product, None) == 7


def test_resolve_cart_variant_id_picks_first_in_stock_variant() -> None:
    product = _product(
        _variant(1, inventory=0, available=False),
        _variant(2, inventory=3),
        _variant(3, inventory=9),
    )

    assert resolve_cart_variant_id(product, None) == 2


def test_resolve_cart_variant_id_returns_none_when_all_out_of_stock() -> None:
    product = _product(
        _variant(1, inventory=0, available=False),
        _variant(2, inventory=0, available=False),
    )

    assert resolve_cart_variant_id(product, None) is None


def test_resolve_cart_variant_id_returns_single_variant_even_when_out_of_stock() -> (
    None
):
    product = _product(_variant(1, inventory=0, available=False))

    assert resolve_cart_variant_id(product, None) == 1


def test_pick_buyable_variant_id_prefers_available_preferred_variant() -> None:
    variants = [_variant(1, inventory=0), _variant(2, inventory=4)]
    reserved = {1: 0, 2: 1}

    assert pick_buyable_variant_id(variants, reserved, preferred_id=2) == 2


def test_pick_buyable_variant_id_falls_back_when_preferred_is_out_of_stock() -> None:
    variants = [_variant(1, inventory=2), _variant(2, inventory=0)]
    reserved = {1: 0, 2: 0}

    assert pick_buyable_variant_id(variants, reserved, preferred_id=2) == 1


def test_pick_buyable_variant_id_returns_none_when_reserved_exceeds_inventory() -> None:
    variants = [_variant(1, inventory=2)]
    reserved = {1: 2}

    assert pick_buyable_variant_id(variants, reserved, None) is None


def test_variant_available_qty_respects_available_flag() -> None:
    assert variant_available_qty(5, 1, available=False) == 0
    assert variant_available_qty(5, 1, available=True) == 4
