from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import (
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    CANCELLATION_REASON_PAYMENT_TIMEOUT,
    AvailabilityConfirmationStatus,
    Order,
    OrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.schemas.order import DeliveryAddressCreate
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)

pytestmark = pytest.mark.integration


async def _seed_order(
    session: AsyncSession,
    user_id: int,
    suffix: int,
    *,
    status: str = OrderStatus.PROCESSING,
    payment_due_at,
    payment_paid_at=None,
    cancellation_reason: str | None = None,
    availability: str = AvailabilityConfirmationStatus.NOT_REQUIRED,
) -> Order:
    order_crud = CrudOrder(session=session, model=Order)
    product_id = await pick_active_product_id(session)
    product_id, variant_id, unit_price, quantity = await resolve_product_line_spec(
        session,
        product_id,
        Decimal("2500"),
        1,
    )
    subtotal = unit_price * quantity
    delivery = Decimal("500")
    order = await order_crud.create_order_with_items(
        user_id=user_id,
        total_amount=subtotal + delivery,
        items_subtotal_amount=subtotal,
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=delivery,
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=None,
        items_payload=[
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "product_title_captured": f"My orders test {suffix}",
            }
        ],
        idempotency_key=f"test-my-orders-{suffix}",
        delivery_payload=DeliveryAddressCreate(
            last_name="My",
            first_name="Orders",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone="+79990000004",
        ).model_dump(),
        availability_confirmation_status=availability,
        payment_due_at=payment_due_at,
    )
    order.status = status
    order.cancellation_reason = cancellation_reason
    order.payment_paid_at = payment_paid_at
    await order_crud.commit_order(order)
    await session.commit()
    return order


@pytest.mark.asyncio
async def test_storefront_orders_my_hides_timeout_cancelled_unpaid(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 100)
        hidden = await _seed_order(
            session,
            user.id,
            merge_unique_suffix + 100,
            status=OrderStatus.CANCELLED,
            payment_due_at=utc_now_naive() - timedelta(hours=2),
            cancellation_reason=CANCELLATION_REASON_PAYMENT_TIMEOUT,
        )
        visible = await _seed_order(
            session,
            user.id,
            merge_unique_suffix + 101,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        service = OrderService(session)
        orders = await service.list_orders(user_id=user.id, page=1, page_size=20)
        ids = {o.id for o in orders}
        assert hidden.id not in ids
        assert visible.id in ids


@pytest.mark.asyncio
async def test_storefront_orders_my_shows_late_paid_cancelled(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 200)
        order = await _seed_order(
            session,
            user.id,
            merge_unique_suffix + 200,
            status=OrderStatus.CANCELLED,
            payment_due_at=utc_now_naive() - timedelta(hours=2),
            payment_paid_at=utc_now_naive(),
            cancellation_reason=CANCELLATION_REASON_PAYMENT_TIMEOUT,
        )
        service = OrderService(session)
        orders = await service.list_orders(user_id=user.id, page=1, page_size=20)
        match = next((o for o in orders if o.id == order.id), None)
        assert match is not None
        assert match.late_payment_after_auto_cancel is True
        assert match.payment_state == "late_paid_after_cancel"
        assert match.payment_label == "Оплачено"


@pytest.mark.asyncio
async def test_storefront_orders_my_shows_late_paid_customer_cancelled(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 250)
        order = await _seed_order(
            session,
            user.id,
            merge_unique_suffix + 250,
            status=OrderStatus.CANCELLED,
            payment_due_at=utc_now_naive() - timedelta(hours=2),
            payment_paid_at=utc_now_naive(),
            cancellation_reason=CANCELLATION_REASON_CUSTOMER_REQUEST,
        )
        service = OrderService(session)
        orders = await service.list_orders(user_id=user.id, page=1, page_size=20)
        match = next((o for o in orders if o.id == order.id), None)
        assert match is not None
        assert match.late_payment_after_auto_cancel is True
        assert match.payment_state == "late_paid_after_cancel"
        assert match.payment_label == "Оплачено"


@pytest.mark.asyncio
async def test_storefront_orders_my_pending_availability_payment_label(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker

    async with async_session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 300)
        order = await _seed_order(
            session,
            user.id,
            merge_unique_suffix + 300,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
            availability=AvailabilityConfirmationStatus.PENDING,
        )
        service = OrderService(session)
        orders = await service.list_orders(user_id=user.id, page=1, page_size=20)
        match = next((o for o in orders if o.id == order.id), None)
        assert match is not None
        assert match.payment_label == "Проверяем наличие"
        assert match.payment_allowed is False
