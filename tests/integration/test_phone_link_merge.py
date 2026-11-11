import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models.auth_identity import AuthIdentity
from src.models.cart import CartItem
from src.models.order import Order
from src.models.product import Product
from src.models.user import User
from src.repositories.auth_identity_repo import PROVIDER_PHONE, PROVIDER_TELEGRAM
from src.repositories.session import async_session_maker
from src.schemas.order import DeliveryAddressCreate
from src.services.auth.phone import PhoneAuthService
from src.services.cart_service import CartService
from src.services.identity_service import IdentityService
from src.services.orders.order_service import OrderService
from src.services.user_service import UserService
from tests.integration.helpers.order_admin import set_product_available_stock


@pytest.mark.asyncio
async def test_link_phone_merges_phone_only_donor_cart_orders_and_login(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    telegram_id = 9_000_000_000 + suffix
    phone_e164 = f"+7999{suffix:07d}"
    tag = f"merge-test-{suffix}"

    user_a_id = 0
    user_b_id = 0
    order_b_id = 0

    async with async_session_maker() as session:
        identity_svc = IdentityService(session)
        user_svc = UserService(session)
        cart_svc = CartService(session)
        order_svc = OrderService(session)

        product_ids = list(
            (
                await session.scalars(
                    select(Product.id).where(Product.is_active.is_(True)).limit(2)
                )
            ).all()
        )
        if len(product_ids) < 2:
            pytest.skip("нужно минимум 2 активных товара в каталоге")
        product_order_id, product_cart_id = product_ids[0], product_ids[1]
        await set_product_available_stock(session, int(product_order_id), stock=100)
        await set_product_available_stock(session, int(product_cart_id), stock=100)

        user_a = await user_svc.upsert_telegram_user(
            telegram_id=telegram_id,
            telegram_username=f"user_a_{suffix}",
            name=f"User A {tag}",
        )
        user_a_id = user_a.id

        user_b = await user_svc.register_user_by_phone(phone_e164)
        user_b_id = user_b.id

        await cart_svc.add_or_update_item(user_b_id, product_order_id, quantity=1)

        delivery = DeliveryAddressCreate(
            last_name="Smoke",
            first_name="B",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone=phone_e164,
        )
        order_b = await order_svc.order_crud.create_order_with_items(
            user_id=user_b_id,
            total_amount=Decimal("100"),
            items_subtotal_amount=Decimal("100"),
            discount_items_amount=Decimal("0"),
            delivery_fee_eur_snapshot=Decimal("0"),
            delivery_fee_amount=Decimal("0"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=None,
            items_payload=[
                {
                    "product_id": product_order_id,
                    "quantity": 1,
                    "unit_price": Decimal("100"),
                }
            ],
            idempotency_key=f"merge-test-{uuid.uuid4()}",
            delivery_payload=delivery.model_dump(),
        )
        await order_svc.order_crud.commit_order(order_b)
        order_b_id = order_b.id

        await cart_svc.add_or_update_item(user_b_id, product_cart_id, quantity=1)

        user_a = await user_svc.get_user(user_a_id)
        assert user_a is not None
        linked = await identity_svc.link_phone_to_user(user_a, phone_e164)
        assert linked.id == user_a_id

    async with async_session_maker() as session:
        assert await session.get(User, user_b_id) is None

        phone_identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == PROVIDER_PHONE,
                AuthIdentity.provider_user_id == phone_e164,
            )
        )
        assert phone_identity is not None
        assert phone_identity.user_id == user_a_id

        tg_identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_a_id,
                AuthIdentity.provider == PROVIDER_TELEGRAM,
            )
        )
        assert tg_identity is not None

        order_row = await session.get(Order, order_b_id)
        assert order_row is not None
        assert order_row.user_id == user_a_id

        cart_items_b = list(
            (
                await session.scalars(
                    select(CartItem).where(CartItem.user_id == user_b_id)
                )
            ).all()
        )
        assert len(cart_items_b) == 0

        cart_items_a = list(
            (
                await session.scalars(
                    select(CartItem).where(CartItem.user_id == user_a_id)
                )
            ).all()
        )
        assert len(cart_items_a) > 0

        orders_a = list(
            (
                await session.scalars(select(Order).where(Order.user_id == user_a_id))
            ).all()
        )
        assert any(o.id == order_b_id for o in orders_a)

    async with async_session_maker() as session:
        login_user, is_new = await PhoneAuthService(session).authenticate_by_phone(
            phone_e164
        )
        assert login_user.id == user_a_id
        assert is_new is False
