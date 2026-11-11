import random
from decimal import Decimal

import pytest

from src.schemas.product import ProductPublicSchema, ProductVariantSchema
from src.utils.labels import FOOTWEAR_CATEGORY_L2
from src.utils.variant_sort import (
    apply_variant_option_sort_keys,
    parse_variant_option_sort_key,
    sort_option_values_from_variants,
)

# Все уникальные option2 обуви из каталога (supplier supplier-demo formats).
SUPPLIER_FOOTWEAR_SIZES: tuple[str, ...] = (
    "26",
    "27",
    "27,5",
    "28",
    "28 1/3",
    "28 2/3",
    "28,5",
    "28-29",
    "29",
    "29 1/3",
    "29 2/3",
    "29,5",
    "29-30",
    "30",
    "30 2/3",
    "30,5",
    "30-31",
    "31",
    "31 1/3",
    "31,5",
    "32",
    "32 2/3",
    "32,5",
    "32-33",
    "33",
    "33 1/3",
    "33,5",
    "33-34",
    "34",
    "34 2/3",
    "34,5",
    "34-35",
    "35",
    "35 1/3",
    "35,5",
    "36",
    "36 1/3",
    "36 2/3",
    "36,5",
    "36-37",
    "37",
    "37 1/3",
    "37,5",
    "37-38",
    "38",
    "38 2/3",
    "38 3/4",
    "38,5",
    "38-39",
    "39",
    "39 1/3",
    "39 2/3",
    "39,5",
    "39-40",
    "40",
    "40 1/3",
    "40 2/3",
    "40 3/4",
    "40,5",
    "41",
    "41 1/3",
    "41,5",
    "41-42",
    "42",
    "42 2/3",
    "42,5",
    "42-43",
    "43",
    "43 1/3",
    "43,5",
    "43-44",
    "44",
    "44 2/3",
    "44,5",
    "45",
    "45 1/3",
    "45 3/4",
    "45,5",
    "45-46",
    "46",
    "46 2/3",
    "46,5",
    "46-47",
    "47",
    "47 1/3",
    "47,5",
    "48",
    "48 2/3",
    "48,5",
    "48-48,5",
    "48-49",
    "49",
    "49 1/3",
    "49,5",
    "50",
    "50 2/3",
    "50,5",
    "51",
    "51 1/3",
    "51,5",
)

EU_SHOE_LADDER: tuple[str, ...] = (
    "36",
    "36 2/3",
    "37 1/3",
    "37,5",
    "38",
    "38 2/3",
    "39 1/3",
    "40",
)

CLOTHING_LETTER_LADDER: tuple[str, ...] = (
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "2XL",
    "3XL",
    "4XL",
)

GRIP_SIZE_LADDER: tuple[str, ...] = ("0", "1", "2", "3", "4")


class _VariantStub:
    def __init__(
        self,
        *,
        option1: str | None = None,
        option2: str | None = None,
        option3: str | None = None,
        option1_sort_key: Decimal | None = None,
        option2_sort_key: Decimal | None = None,
        option3_sort_key: Decimal | None = None,
    ) -> None:
        self.option1 = option1
        self.option2 = option2
        self.option3 = option3
        self.option1_sort_key = option1_sort_key
        self.option2_sort_key = option2_sort_key
        self.option3_sort_key = option3_sort_key


def _build_variants(
    sizes: list[str],
    *,
    category_l2: str,
) -> list[_VariantStub]:
    variants: list[_VariantStub] = []
    for size in sizes:
        variant = _VariantStub(option1="Blue", option2=size)
        apply_variant_option_sort_keys(variant, category_l2)
        variants.append(variant)
    return variants


def _sorted_footwear_sizes(
    sizes: list[str],
    *,
    category_l2: str,
) -> list[str]:
    variants = _build_variants(sizes, category_l2=category_l2)
    return sort_option_values_from_variants(variants, "option2", sizes)


def _build_option2_variants(
    sizes: list[str],
    *,
    category_l2: str,
    option1: str = "Blue",
) -> list[_VariantStub]:
    variants: list[_VariantStub] = []
    for size in sizes:
        variant = _VariantStub(option1=option1, option2=size)
        apply_variant_option_sort_keys(variant, category_l2)
        variants.append(variant)
    return variants


def _sorted_option2_values(
    sizes: list[str],
    *,
    category_l2: str,
    option1: str = "Blue",
) -> list[str]:
    variants = _build_option2_variants(sizes, category_l2=category_l2, option1=option1)
    return sort_option_values_from_variants(variants, "option2", sizes)


def test_parse_fractional_eu_sizes() -> None:
    assert parse_variant_option_sort_key(
        "option2", "36 2/3", category_l2="Tennis shoes"
    ) == Decimal("36.66666666666666666666666667")
    assert parse_variant_option_sort_key(
        "option2", "38", category_l2="Tennis shoes"
    ) == Decimal("38")
    assert parse_variant_option_sort_key(
        "option2", "38,5", category_l2="Tennis shoes"
    ) == Decimal("38.5")


def test_parse_range_and_three_quarter_sizes() -> None:
    assert parse_variant_option_sort_key(
        "option2", "36-37", category_l2="Running shoes"
    ) == Decimal("36")
    assert parse_variant_option_sort_key(
        "option2", "48-48,5", category_l2="Running shoes"
    ) == Decimal("48")
    assert parse_variant_option_sort_key(
        "option2", "38 3/4", category_l2="Running shoes"
    ) == Decimal("38.75")
    assert parse_variant_option_sort_key(
        "option2", "38 1/2", category_l2="Tennis shoes"
    ) == Decimal("38.5")


def test_parse_skips_color_options() -> None:
    assert (
        parse_variant_option_sort_key(
            "option1", "black, white", category_l2="Tennis shoes"
        )
        is None
    )


def test_parse_skips_surface_and_stringing_options() -> None:
    assert (
        parse_variant_option_sort_key(
            "option1", "full-surface", category_l2="Padel rackets"
        )
        is None
    )
    assert (
        parse_variant_option_sort_key("option1", "strung", category_l2="Padel rackets")
        is None
    )


def test_parse_skips_translated_enum_values() -> None:
    assert (
        parse_variant_option_sort_key("option2", "one size", category_l2="Shirts")
        is None
    )


def test_parse_letter_sizes_for_clothing() -> None:
    assert parse_variant_option_sort_key(
        "option2", "S", category_l2="Shirts"
    ) == Decimal("30")
    assert parse_variant_option_sort_key(
        "option2", "XL", category_l2="Shirts"
    ) == Decimal("60")
    assert parse_variant_option_sort_key(
        "option2", "2XL", category_l2="Shirts"
    ) == Decimal("70")


def test_clothing_letter_sizes_sort_ascending_when_shuffled() -> None:
    shuffled = list(CLOTHING_LETTER_LADDER)
    random.Random(1).shuffle(shuffled)
    assert _sorted_option2_values(shuffled, category_l2="Shirts") == list(
        CLOTHING_LETTER_LADDER
    )


def test_parse_grip_sizes_for_racket_option2() -> None:
    assert parse_variant_option_sort_key(
        "option2", "1", category_l2="Padel rackets"
    ) == Decimal("1")
    assert parse_variant_option_sort_key(
        "option2", "4", category_l2="Padel rackets"
    ) == Decimal("4")
    assert parse_variant_option_sort_key(
        "option2", "00", category_l2="Padel rackets"
    ) == Decimal("0")


def test_grip_sizes_sort_ascending_when_shuffled() -> None:
    shuffled = list(GRIP_SIZE_LADDER)
    random.Random(2).shuffle(shuffled)
    assert _sorted_option2_values(shuffled, category_l2="Padel rackets") == list(
        GRIP_SIZE_LADDER
    )


def test_parse_skips_option3_even_for_numeric_values() -> None:
    assert (
        parse_variant_option_sort_key("option3", "38", category_l2="Tennis shoes")
        is None
    )


def test_sort_falls_back_when_any_value_lacks_sort_key() -> None:
    variants = [
        _VariantStub(option2="40", option2_sort_key=Decimal("40")),
        _VariantStub(option2="Blue"),
    ]
    values = ["40", "Blue"]
    assert sort_option_values_from_variants(variants, "option2", values) == values


@pytest.mark.parametrize("size", SUPPLIER_FOOTWEAR_SIZES)
def test_parse_all_supplier_footwear_sizes(size: str) -> None:
    assert (
        parse_variant_option_sort_key("option2", size, category_l2="Tennis shoes")
        is not None
    )


def test_supplier_footwear_sizes_sort_ascending_when_shuffled() -> None:
    shuffled = list(SUPPLIER_FOOTWEAR_SIZES)
    random.Random(0).shuffle(shuffled)
    sorted_sizes = _sorted_footwear_sizes(shuffled, category_l2="Tennis shoes")
    keys = [
        parse_variant_option_sort_key("option2", size, category_l2="Tennis shoes")
        for size in sorted_sizes
    ]
    assert keys == sorted(keys)


@pytest.mark.parametrize("category_l2", sorted(FOOTWEAR_CATEGORY_L2))
def test_footwear_eu_ladder_sorted_for_every_category(category_l2: str) -> None:
    shuffled = list(EU_SHOE_LADDER)
    random.Random(hash(category_l2)).shuffle(shuffled)
    assert _sorted_footwear_sizes(shuffled, category_l2=category_l2) == list(
        EU_SHOE_LADDER
    )


def test_sort_option_values_from_variant_sort_keys() -> None:
    variants = [
        _VariantStub(option2="40", option2_sort_key=Decimal("40")),
        _VariantStub(option2="36", option2_sort_key=Decimal("36")),
        _VariantStub(option2="37 1/3", option2_sort_key=Decimal("37.333")),
        _VariantStub(option2="38 2/3", option2_sort_key=Decimal("38.667")),
    ]
    assert sort_option_values_from_variants(
        variants,
        "option2",
        ["40", "36", "37 1/3", "38 2/3"],
    ) == ["36", "37 1/3", "38 2/3", "40"]


def test_apply_variant_option_sort_keys_on_import() -> None:
    variant = _VariantStub(option2="38 2/3")
    apply_variant_option_sort_keys(variant, "Tennis shoes")
    assert variant.option2_sort_key is not None
    assert variant.option2_sort_key > Decimal("38")
    assert variant.option2_sort_key < Decimal("39")


def _variant(
    variant_id: int, option2: str, option2_sort_key: Decimal
) -> ProductVariantSchema:
    return ProductVariantSchema(
        id=variant_id,
        option1="Blue",
        option2=option2,
        option2_sort_key=option2_sort_key,
        inventory_quantity=1,
        available=True,
    )


def test_product_public_schema_exposes_sorted_size_values() -> None:
    product = ProductPublicSchema(
        id=1,
        title="Shoe",
        brand="Brand",
        sale_price=Decimal("10000"),
        regular_price=Decimal("12000"),
        product_url="https://example.com/shoe",
        is_active=True,
        category_l2="Tennis shoes",
        variants=[
            _variant(1, "40", Decimal("40")),
            _variant(2, "36", Decimal("36")),
            _variant(3, "37.5", Decimal("37.5")),
        ],
    )

    assert list(product.variant_option_values_ru["option2"].keys()) == [
        "36",
        "37.5",
        "40",
    ]


def test_product_public_schema_exposes_ordered_size_list() -> None:
    product = ProductPublicSchema(
        id=1,
        title="Shoe",
        brand="Brand",
        sale_price=Decimal("10000"),
        regular_price=Decimal("12000"),
        product_url="https://example.com/shoe",
        is_active=True,
        category_l2="Tennis shoes",
        variants=[
            _variant(1, "44", Decimal("44")),
            _variant(2, "36", Decimal("36")),
            _variant(3, "37,5", Decimal("37.5")),
            _variant(4, "37", Decimal("37")),
        ],
    )

    assert product.variant_option_values["option2"] == ["36", "37", "37,5", "44"]


def test_product_public_schema_exposes_sorted_clothing_sizes() -> None:
    product = ProductPublicSchema(
        id=2,
        title="Shirt",
        brand="Brand",
        sale_price=Decimal("5000"),
        regular_price=Decimal("6000"),
        product_url="https://example.com/shirt",
        is_active=True,
        category_l2="Shirts",
        variants=[
            ProductVariantSchema(
                id=10,
                option1="White",
                option2="XL",
                option2_sort_key=Decimal("60"),
                inventory_quantity=1,
                available=True,
            ),
            ProductVariantSchema(
                id=11,
                option1="White",
                option2="S",
                option2_sort_key=Decimal("30"),
                inventory_quantity=1,
                available=True,
            ),
            ProductVariantSchema(
                id=12,
                option1="White",
                option2="M",
                option2_sort_key=Decimal("40"),
                inventory_quantity=1,
                available=True,
            ),
        ],
    )

    assert product.variant_option_values["option2"] == ["S", "M", "XL"]
