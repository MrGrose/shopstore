from collections import defaultdict

import pytest
from sqlalchemy import select

from src.models.product import Product, ProductVariant
from src.repositories.session import async_session_maker
from src.utils.labels import FOOTWEAR_CATEGORY_L2
from src.utils.variant_sort import (
    apply_variant_option_sort_keys,
    parse_variant_option_sort_key,
    sort_option_values_from_variants,
)

pytestmark = pytest.mark.integration


class _VariantStub:
    def __init__(self, option2: str) -> None:
        self.option1 = "color"
        self.option2 = option2
        self.option3 = None
        self.option1_sort_key = None
        self.option2_sort_key = None
        self.option3_sort_key = None


@pytest.mark.asyncio
async def test_all_footwear_products_expose_ascending_sizes() -> None:
    async with async_session_maker() as session:
        products = (
            await session.execute(
                select(Product.id, Product.category_l2).where(
                    Product.category_l2.in_(FOOTWEAR_CATEGORY_L2)
                )
            )
        ).all()
        product_ids = [row[0] for row in products]
        category_by_id = {row[0]: row[1] for row in products}
        variant_rows = (
            await session.execute(
                select(ProductVariant.product_id, ProductVariant.option2).where(
                    ProductVariant.product_id.in_(product_ids),
                    ProductVariant.option2.isnot(None),
                )
            )
        ).all()

    sizes_by_product: dict[int, list[str]] = defaultdict(list)
    for product_id, option2 in variant_rows:
        text = str(option2 or "").strip()
        if text:
            sizes_by_product[product_id].append(text)

    offenders: list[str] = []
    for product_id, sizes in sizes_by_product.items():
        unique = list(dict.fromkeys(sizes))
        if len(unique) <= 1:
            continue
        category_l2 = category_by_id[product_id]
        sort_keys = {
            size: parse_variant_option_sort_key(
                "option2", size, category_l2=category_l2
            )
            for size in unique
        }
        if any(key is None for key in sort_keys.values()):
            offenders.append(f"product={product_id} unparsed sizes")
            continue
        stubs = []
        for size in unique:
            stub = _VariantStub(size)
            apply_variant_option_sort_keys(stub, category_l2)
            stubs.append(stub)
        sorted_sizes = sort_option_values_from_variants(stubs, "option2", unique)
        ordered_keys = [sort_keys[size] for size in sorted_sizes]
        if ordered_keys != sorted(ordered_keys):
            offenders.append(
                f"product={product_id} order={sorted_sizes} keys={ordered_keys}"
            )

    assert not offenders, "; ".join(offenders[:5])
