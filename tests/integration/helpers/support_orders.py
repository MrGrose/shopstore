from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import AvailabilityConfirmationStatus, Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.schemas.order import DeliveryAddressCreate
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    pick_active_product_id,
    resolve_product_line_spec,
)


# Создаёт заказ для support-тестов с нужным статусом и оплатой.
async def seed_support_order(
    session: AsyncSession,
    user_id: int,
    suffix: int,
    *,
    status: str = OrderStatus.PROCESSING,
    payment_paid_at=None,
    payment_due_at=None,
    created_at: datetime | None = None,
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
    due = payment_due_at or (utc_now_naive() + timedelta(hours=5))
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
                "product_title_captured": f"Support test {suffix}",
            }
        ],
        idempotency_key=f"test-support-order-{suffix}",
        delivery_payload=DeliveryAddressCreate(
            last_name="Support",
            first_name="Test",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone="+79990000005",
        ).model_dump(),
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        payment_due_at=due,
    )
    order.status = status
    order.payment_paid_at = payment_paid_at
    if created_at is not None:
        order.created_at = created_at
    await order_crud.commit_order(order)
    await session.commit()
    return order
