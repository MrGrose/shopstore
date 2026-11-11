import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select

from src.jobs.dom_scheduler import _load_stock_zero_incomplete
from src.models.product import Product, ProductFeature, ProductImage
from src.repositories.session import async_session_maker


def _scheduler_env() -> MagicMock:
    return MagicMock(
        dom_retry_cooldown_seconds=0,
        dom_max_attempts=100,
    )


def _product_base(prefix: str, index: int, dom_attempts: int = 0) -> Product:
    return Product(
        title=f"DOM sched {prefix} {index}",
        brand="TestBrand",
        sale_price=100,
        regular_price=100,
        supplier_price_eur=50,
        stock=0,
        is_active=True,
        external_id=f"{prefix}-ext-{index}",
        product_url=f"https://example.com/{prefix}/{index}",
        description_raw=f"Description {index}",
        dom_attempts=dom_attempts,
    )


def _attach_complete_relations(product: Product, index: int) -> None:
    product.images = [
        ProductImage(url=f"https://example.com/{index}.jpg", position=0),
    ]
    product.features = [
        ProductFeature(name="Weight", value="365g", position=0),
    ]


def _complete_stock_zero(prefix: str, index: int, dom_attempts: int = 0) -> Product:
    product = _product_base(prefix, index, dom_attempts=dom_attempts)
    _attach_complete_relations(product, index)
    return product


def _incomplete_stock_zero(prefix: str, index: int, dom_attempts: int = 0) -> Product:
    product = _product_base(prefix, index, dom_attempts=dom_attempts)
    product.description_raw = None
    product.images = [
        ProductImage(url=f"https://example.com/{index}-inc.jpg", position=0),
    ]
    product.features = []
    return product


async def _insert_products(products: list[Product]) -> list[int]:
    async with async_session_maker() as session:
        session.add_all(products)
        await session.commit()
        for product in products:
            await session.refresh(product)
        return [int(product.id) for product in products]


async def _delete_products(product_ids: list[int]) -> None:
    if not product_ids:
        return
    async with async_session_maker() as session:
        await session.execute(
            delete(ProductFeature).where(ProductFeature.product_id.in_(product_ids))
        )
        await session.execute(
            delete(ProductImage).where(ProductImage.product_id.in_(product_ids))
        )
        await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.commit()


@pytest.fixture
def test_prefix() -> str:
    return f"dom-sched-{uuid.uuid4().hex[:12]}"


@pytest.mark.asyncio
async def test_stock_zero_incomplete_regression_limit_after_filter(
    test_prefix: str,
) -> None:
    complete = [
        _complete_stock_zero(test_prefix, index, dom_attempts=0) for index in range(60)
    ]
    incomplete = _incomplete_stock_zero(test_prefix, 999, dom_attempts=0)
    product_ids = await _insert_products(complete + [incomplete])
    try:
        payloads = await _load_stock_zero_incomplete(_scheduler_env(), 50)
        matched = [row for row in payloads if row.get("id") == incomplete.id]
        assert len(matched) == 1
        assert matched[0].get("dom_mode") == "FULL"
    finally:
        await _delete_products(product_ids)


@pytest.mark.asyncio
async def test_stock_zero_incomplete_excludes_complete(test_prefix: str) -> None:
    products = [
        _complete_stock_zero(test_prefix, 1),
        _complete_stock_zero(test_prefix, 2),
        _complete_stock_zero(test_prefix, 3),
        _incomplete_stock_zero(test_prefix, 4),
        _incomplete_stock_zero(test_prefix, 5),
    ]
    product_ids = await _insert_products(products)
    expected_ids = {products[3].id, products[4].id}
    try:
        payloads = await _load_stock_zero_incomplete(_scheduler_env(), 500)
        returned_ids = {
            row.get("id") for row in payloads if row.get("id") in expected_ids
        }
        assert returned_ids == expected_ids
        for row in payloads:
            if row.get("id") in returned_ids:
                assert row.get("dom_mode") == "FULL"
    finally:
        await _delete_products(product_ids)


@pytest.mark.asyncio
async def test_stock_zero_incomplete_orders_by_attempts_then_id(
    test_prefix: str,
) -> None:
    first = _incomplete_stock_zero(test_prefix, 1, dom_attempts=2)
    second = _incomplete_stock_zero(test_prefix, 2, dom_attempts=0)
    third = _incomplete_stock_zero(test_prefix, 3, dom_attempts=1)
    product_ids = await _insert_products([first, second, third])
    expected_ids = [second.id, third.id, first.id]
    try:
        payloads = await _load_stock_zero_incomplete(_scheduler_env(), 500)
        returned_ids = [
            row.get("id") for row in payloads if row.get("id") in expected_ids
        ]
        assert returned_ids == expected_ids
    finally:
        await _delete_products(product_ids)


@pytest.mark.asyncio
async def test_stock_zero_incomplete_cleanup_deletes_related_rows(
    test_prefix: str,
) -> None:
    product = _incomplete_stock_zero(test_prefix, 42)
    product_ids = await _insert_products([product])
    try:
        async with async_session_maker() as session:
            image_count = int(
                await session.scalar(
                    select(ProductImage.id)
                    .where(ProductImage.product_id == product.id)
                    .limit(1)
                )
                or 0
            )
            feature_count = int(
                await session.scalar(
                    select(ProductFeature.id)
                    .where(ProductFeature.product_id == product.id)
                    .limit(1)
                )
                or 0
            )
            assert image_count > 0
            assert feature_count == 0
    finally:
        await _delete_products(product_ids)

    async with async_session_maker() as session:
        remaining = int(
            await session.scalar(select(Product.id).where(Product.id == product.id))
            or 0
        )
        assert remaining == 0
