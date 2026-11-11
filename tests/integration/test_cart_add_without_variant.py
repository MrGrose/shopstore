import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.models.product import Product, ProductVariant
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.services.cart_service import CartService
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    set_product_available_stock,
)

pytestmark = pytest.mark.integration


async def _pick_product_with_variants(session) -> Product:
    product = await session.scalar(
        select(Product)
        .options(selectinload(Product.variants))
        .where(Product.is_active.is_(True))
        .where(
            Product.id.in_(
                select(ProductVariant.product_id)
                .group_by(ProductVariant.product_id)
                .having(func.count(ProductVariant.id) >= 2)
            )
        )
        .limit(1)
    )
    if product is None:
        pytest.skip("нужен активный товар с минимум двумя вариантами")
    return product


@pytest.mark.asyncio
async def test_cart_add_without_variant_id_picks_buyable_variant(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 710)
        product = await _pick_product_with_variants(session)
        await set_product_available_stock(session, product.id, stock=5)

        cart = await CartService(session).add_or_update_item(
            user_id=user.id,
            product_id=product.id,
            quantity=1,
            variant_id=None,
        )
        await session.commit()

        assert len(cart.items) == 1
        assert cart.items[0].product_id == product.id
        assert cart.items[0].variant_id is not None
        variant_ids = {int(variant.id) for variant in product.variants}
        assert cart.items[0].variant_id in variant_ids


@pytest.mark.asyncio
async def test_cart_add_with_variant_id_keeps_explicit_choice(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 711)
        product = await _pick_product_with_variants(session)
        await set_product_available_stock(session, product.id, stock=5)
        explicit_variant_id = int(product.variants[0].id)

        cart = await CartService(session).add_or_update_item(
            user_id=user.id,
            product_id=product.id,
            quantity=1,
            variant_id=explicit_variant_id,
        )
        await session.commit()

        assert cart.items[0].variant_id == explicit_variant_id


@pytest.mark.asyncio
async def test_cart_add_without_variant_id_rejects_out_of_stock(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 712)
        product_id = await pick_active_product_id(session)
        product = await CrudProduct(
            session=session, model=Product
        ).get_by_id_with_related(product_id)
        assert product is not None
        await set_product_available_stock(session, product_id, stock=0)

        with pytest.raises(ValueError, match="Недостаточно товара"):
            await CartService(session).add_or_update_item(
                user_id=user.id,
                product_id=product_id,
                quantity=1,
                variant_id=None,
            )
