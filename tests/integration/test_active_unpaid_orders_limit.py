from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.order import Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.schemas.order import DeliveryAddressCreate
from src.services.cart_service import CartService
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    set_product_available_stock,
)
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order

pytestmark = pytest.mark.integration

_DELIVERY = DeliveryAddressCreate(
    last_name="Limit",
    first_name="Test",
    street="Test St",
    house="1",
    city="Moscow",
    postal_code="101000",
    phone="+79990000005",
).model_dump()


async def _add_cart_item(session: AsyncSession, user_id: int) -> None:
    product_id = await pick_active_product_id(session)
    await set_product_available_stock(session, product_id, stock=10)
    await CartService(session).add_or_update_item(
        user_id=user_id,
        product_id=product_id,
        quantity=1,
    )
    await session.commit()


@pytest.mark.asyncio
async def test_active_unpaid_limit_blocks_fourth_create_order(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    limit = settings.ORDER_MAX_ACTIVE_UNPAID_ORDERS_PER_USER
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 500)
        future = utc_now_naive() + timedelta(hours=12)
        for i in range(limit):
            await _create_unpaid_order(
                session,
                user.id,
                merge_unique_suffix + 500 + i,
                payment_due_at=future,
            )
        count = await CrudOrder(
            session=session, model=Order
        ).count_active_unpaid_orders(
            user.id,
            utc_now_naive(),
        )
        assert count == limit

        await _add_cart_item(session, user.id)
        service = OrderService(session)
        with pytest.raises(ValueError, match="активных неоплаченных"):
            await service.create_order(
                user_id=user.id,
                idempotency_key=f"limit-block-{merge_unique_suffix}",
                delivery_payload=_DELIVERY,
                notification_channels=["telegram"],
            )


@pytest.mark.asyncio
async def test_active_unpaid_slot_freed_after_expire_allows_create(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    limit = settings.ORDER_MAX_ACTIVE_UNPAID_ORDERS_PER_USER
    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 600)
        past = utc_now_naive() - timedelta(hours=1)
        future = utc_now_naive() + timedelta(hours=12)
        orders: list[Order] = []
        for i in range(limit):
            order = await _create_unpaid_order(
                session,
                user.id,
                merge_unique_suffix + 600 + i,
                payment_due_at=future if i < limit - 1 else past,
            )
            orders.append(order)

        service = OrderService(session)
        assert await service.expire_unpaid_order(orders[-1].id) == "cancelled"

        count = await service.order_crud.count_active_unpaid_orders(
            user.id,
            utc_now_naive(),
        )
        assert count == limit - 1

        await _add_cart_item(session, user.id)
        created = await service.create_order(
            user_id=user.id,
            idempotency_key=f"limit-free-{merge_unique_suffix}",
            delivery_payload=_DELIVERY,
            notification_channels=["telegram"],
        )
        assert created.id is not None
        assert created.status == OrderStatus.CREATED
