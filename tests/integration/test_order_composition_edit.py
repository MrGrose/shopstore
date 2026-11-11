from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.security import create_access_token
from src.main import app
from src.models.order import Order, OrderEvent
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import (
    AdminOrderItemAdd,
    AdminOrderItemsUpdate,
    AdminOrderItemUpdate,
)
from src.services.cart_service import CartService
from src.services.orders.order_service import OrderService
from tests.integration.helpers.order_admin import (
    attach_promo_usage,
    create_percent_promo,
    create_telegram_user,
    pick_active_product_id,
    pick_two_product_line_specs,
    resolve_product_line_spec,
    set_product_available_stock,
)

_CHECKOUT_PAYLOAD = {
    "notification_channels": ["telegram"],
    "delivery": {
        "last_name": "Ivanov",
        "first_name": "Ivan",
        "street": "Test St",
        "house": "1",
        "city": "Moscow",
        "postal_code": "101000",
        "phone": "+79991234567",
    },
}


@pytest.mark.asyncio
async def test_edit_order_composition_recalculates_promo_percent(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        await set_product_available_stock(session, product_id, 100)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("200"), 2
        )
        promo = await create_percent_promo(session, suffix, Decimal("10"))
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=buyer.id,
            total_amount=Decimal("950"),
            items_subtotal_amount=Decimal("400"),
            discount_items_amount=Decimal("40"),
            delivery_fee_eur_snapshot=Decimal("0"),
            delivery_fee_amount=Decimal("500"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=promo.code,
            items_payload=[
                {
                    "product_id": line_spec[0],
                    "variant_id": line_spec[1],
                    "quantity": line_spec[3],
                    "unit_price": line_spec[2],
                }
            ],
            idempotency_key=f"promo-edit-{suffix}",
        )
        await attach_promo_usage(session, promo, order.id, buyer.id)
        items = await order_crud.get_order_items(order.id)
        service = OrderService(session)
        order_schema, _warning = await service.edit_order_composition(
            order_id=order.id,
            payload=AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=1,
                        unit_price=Decimal("200"),
                    )
                ],
            ),
            actor=buyer,
        )
        await session.refresh(order)

    assert order_schema.items_subtotal_amount == Decimal("200")
    assert order_schema.discount_items_amount == Decimal("20")
    assert order_schema.total_amount == (
        Decimal("200") - Decimal("20") + Decimal(order.delivery_fee_amount or 0)
    )
    assert order_schema.promo_code_applied == promo.code


@pytest.mark.asyncio
async def test_edit_order_composition_rejects_paid_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=buyer.id,
            total_amount=Decimal("600"),
            items_subtotal_amount=Decimal("100"),
            discount_items_amount=Decimal("0"),
            delivery_fee_eur_snapshot=Decimal("0"),
            delivery_fee_amount=Decimal("500"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=None,
            items_payload=[
                {
                    "product_id": product_id,
                    "quantity": 1,
                    "unit_price": Decimal("100"),
                }
            ],
            idempotency_key=f"paid-guard-{suffix}",
        )
        order.payment_paid_at = datetime.utcnow()
        await order_crud.commit_order(order)
        items = await order_crud.get_order_items(order.id)
        service = OrderService(session)
        with pytest.raises(ValueError, match="оплаченный"):
            await service.edit_order_composition(
                order_id=order.id,
                payload=AdminOrderItemsUpdate(
                    items=[
                        AdminOrderItemUpdate(
                            id=items[0].id,
                            quantity=2,
                            unit_price=Decimal("100"),
                        )
                    ],
                ),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_edit_order_composition_keeps_changes_when_telegram_notify_fails(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = merge_unique_suffix
    monkeypatch.setattr(settings, "TG_BOT_SHOP", "")

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        await set_product_available_stock(session, product_id, 100)
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=buyer.id,
            total_amount=Decimal("600"),
            items_subtotal_amount=Decimal("100"),
            discount_items_amount=Decimal("0"),
            delivery_fee_eur_snapshot=Decimal("0"),
            delivery_fee_amount=Decimal("500"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=None,
            items_payload=[
                {
                    "product_id": product_id,
                    "quantity": 1,
                    "unit_price": Decimal("100"),
                }
            ],
            idempotency_key=f"notify-fail-{suffix}",
        )
        items = await order_crud.get_order_items(order.id)
        service = OrderService(session)
        order_schema, warning = await service.edit_order_composition(
            order_id=order.id,
            payload=AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=2,
                        unit_price=Decimal("100"),
                    )
                ],
            ),
            actor=buyer,
        )
        order_id = order.id

    assert order_schema.items[0].quantity == 2
    assert order_schema.items_subtotal_amount == Decimal("200")
    assert warning is not None
    assert "Telegram" in warning

    async with async_session_maker() as session:
        events = list(
            (
                await session.scalars(
                    select(OrderEvent)
                    .where(OrderEvent.order_id == order_id)
                    .order_by(OrderEvent.id.desc())
                )
            ).all()
        )
        assert any(event.event_type == "customer_notify_failed" for event in events)


@pytest.mark.asyncio
async def test_post_orders_checkout_telegram_user_returns_201(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    user_id = 0
    product_id = 0

    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        user_id = user.id
        product_id = await pick_active_product_id(session)
        await CartService(session).add_or_update_item(
            user_id=user_id,
            product_id=product_id,
            quantity=1,
        )

    token = create_access_token(user_id)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/orders/checkout",
            json=_CHECKOUT_PAYLOAD,
            headers={"Authorization": f"Bearer {token}"},
        )
        cart = await client.get(
            "/cart/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body.get("id")
    assert cart.status_code == 200
    assert not cart.json().get("items")


# Добавление позиции в неоплаченный заказ пересчитывает snapshot закупки.
@pytest.mark.asyncio
async def test_add_item_updates_supplier_cost_eur_snapshot(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        first, second = await pick_two_product_line_specs(session)
        await set_product_available_stock(session, first[0], 20)
        await set_product_available_stock(session, second[0], 20)
        product_a = await session.get(Product, first[0])
        product_b = await session.get(Product, second[0])
        assert product_a is not None and product_b is not None
        cost_a = Decimal(str(product_a.supplier_price_eur or 0))
        cost_b = Decimal(str(product_b.supplier_price_eur or 0))
        if cost_a <= 0 or cost_b <= 0:
            pytest.skip("нужны два товара с закупочной EUR")
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=buyer.id,
            total_amount=Decimal("300"),
            items_subtotal_amount=Decimal("200"),
            discount_items_amount=Decimal("0"),
            delivery_fee_eur_snapshot=Decimal("34"),
            delivery_fee_amount=Decimal("100"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=None,
            supplier_cost_eur_snapshot=cost_a,
            items_payload=[
                {
                    "product_id": first[0],
                    "variant_id": first[1],
                    "quantity": 1,
                    "unit_price": first[2],
                    "supplier_price_eur_captured": cost_a,
                }
            ],
            idempotency_key=f"cost-add-{suffix}",
        )
        await OrderService(session).edit_order_composition(
            order_id=order.id,
            payload=AdminOrderItemsUpdate(
                add_items=[
                    AdminOrderItemAdd(
                        product_id=second[0],
                        variant_id=second[1],
                        quantity=1,
                    )
                ],
                notify_customer=False,
            ),
            actor=buyer,
        )
        await session.refresh(order)
        expected = (cost_a + cost_b).quantize(Decimal("0.01"))
        assert order.supplier_cost_eur_snapshot == expected
