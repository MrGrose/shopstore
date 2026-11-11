from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import (
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
    pick_active_product_id,
    resolve_product_line_spec,
)

pytestmark = pytest.mark.integration


async def _create_unpaid_order(
    session: AsyncSession,
    user_id: int,
    suffix: int,
    *,
    payment_due_at,
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
                "product_title_captured": f"Expire test {suffix}",
            }
        ],
        idempotency_key=f"test-expire-{suffix}",
        delivery_payload=DeliveryAddressCreate(
            last_name="Expire",
            first_name="Test",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone="+79990000003",
        ).model_dump(),
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        payment_due_at=payment_due_at,
        notification_channels=["telegram"],
    )
    await session.commit()
    return order


@pytest.mark.asyncio
async def test_expire_unpaid_order_cancels_past_due(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker as session_maker
    from tests.integration.helpers.order_admin import create_telegram_user

    async with session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix)
        past = utc_now_naive() - timedelta(hours=1)
        order = await _create_unpaid_order(
            session, user.id, merge_unique_suffix, payment_due_at=past
        )
        service = OrderService(session)
        result = await service.expire_unpaid_order(order.id)
        assert result == "cancelled"
        refreshed = await service.order_crud.get_by_id(order.id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CANCELLED
        assert refreshed.cancellation_reason == CANCELLATION_REASON_PAYMENT_TIMEOUT


@pytest.mark.asyncio
async def test_expire_skips_when_alive_qr_extends_window(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker as session_maker
    from tests.integration.helpers.order_admin import create_telegram_user

    async with session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 1)
        past = utc_now_naive() - timedelta(minutes=5)
        order = await _create_unpaid_order(
            session, user.id, merge_unique_suffix + 1, payment_due_at=past
        )
        order_crud = CrudOrder(session=session, model=Order)
        now = utc_now_naive()
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=300000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        attempt.qr_expires_at = now + timedelta(minutes=10)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()

        service = OrderService(session)
        result = await service.expire_unpaid_order(order.id)
        assert result == "skipped"
        refreshed = await service.order_crud.get_by_id(order.id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CREATED


@pytest.mark.asyncio
async def test_expire_skips_when_order_already_paid(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker as session_maker
    from tests.integration.helpers.order_admin import create_telegram_user

    async with session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 2)
        past = utc_now_naive() - timedelta(hours=1)
        order = await _create_unpaid_order(
            session, user.id, merge_unique_suffix + 2, payment_due_at=past
        )
        order.payment_paid_at = utc_now_naive()
        await session.commit()

        service = OrderService(session)
        result = await service.expire_unpaid_order(order.id)
        assert result == "skipped"
        refreshed = await service.order_crud.get_by_id(order.id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CREATED


@pytest.mark.asyncio
async def test_expire_skips_when_incomplete_init_resumable(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker as session_maker
    from tests.integration.helpers.order_admin import create_telegram_user

    async with session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 3)
        past = utc_now_naive() - timedelta(hours=1)
        order = await _create_unpaid_order(
            session, user.id, merge_unique_suffix + 3, payment_due_at=past
        )
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=300000,
            payment_currency="RUB",
            init_state="creating",
        )
        await session.commit()

        service = OrderService(session)
        result = await service.expire_unpaid_order(order.id)
        assert result == "skipped"
        refreshed = await service.order_crud.get_by_id(order.id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CREATED


@pytest.mark.asyncio
async def test_expire_unpaid_orders_idempotent_second_run(
    merge_unique_suffix: int,
) -> None:
    from src.repositories.session import async_session_maker as session_maker
    from tests.integration.helpers.order_admin import create_telegram_user

    async with session_maker() as session:
        user = await create_telegram_user(session, merge_unique_suffix + 4)
        past = utc_now_naive() - timedelta(hours=1)
        order = await _create_unpaid_order(
            session, user.id, merge_unique_suffix + 4, payment_due_at=past
        )
        service = OrderService(session)
        first = await service.expire_unpaid_orders(limit=10)
        assert first["cancelled"] >= 1
        second = await service.expire_unpaid_orders(limit=10)
        assert second["cancelled"] == 0
        refreshed = await service.order_crud.get_by_id(order.id)
        assert refreshed is not None
        assert refreshed.status == OrderStatus.CANCELLED
