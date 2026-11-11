from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.main import app
from src.models.order import Order
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import DeliveryAddressCreate
from src.services.orders.order_service import OrderService
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)

pytestmark = pytest.mark.integration


# GET /orders/my текущего пользователя.
async def _get_my_orders(token: str) -> list[dict[str, Any]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/orders/my?page=1&page_size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    return payload


# Создаёт заказ с одной позицией из payload.
async def _create_order(
    session: AsyncSession,
    suffix: int,
    items_payload: list[dict[str, Any]],
) -> Order:
    buyer = await create_telegram_user(session, suffix)
    subtotal = Decimal("1000")
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.create_order_with_items(
        user_id=buyer.id,
        total_amount=subtotal,
        items_subtotal_amount=subtotal,
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=Decimal("0"),
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=None,
        items_payload=items_payload,
        idempotency_key=f"cat-snap-{suffix}",
        delivery_payload=DeliveryAddressCreate(
            last_name="Cat",
            first_name="Snap",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone="+79990000004",
        ).model_dump(),
    )
    await session.commit()
    return order


# Вернуть Product.category_l2/l3 и проверить в новой сессии.
async def _restore_product_categories(
    product_id: int,
    category_l2: str | None,
    category_l3: str | None,
) -> None:
    async with async_session_maker() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        product.category_l2 = category_l2
        product.category_l3 = category_l3
        await session.commit()

    async with async_session_maker() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        assert product.category_l2 == category_l2
        assert product.category_l3 == category_l3


@pytest.mark.asyncio
# GET /orders/my держит snapshot после смены Product.
async def test_orders_my_keeps_category_snapshot_after_product_change(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    saved: tuple[int, str | None, str | None] | None = None
    try:
        async with async_session_maker() as session:
            product_id = await pick_active_product_id(session)
            product = await session.get(Product, product_id)
            assert product is not None
            saved = (product.id, product.category_l2, product.category_l3)
            product.category_l2 = "Gifts"
            product.category_l3 = "Fun items"
            await session.flush()
            line = await resolve_product_line_spec(
                session, product_id, Decimal("1000"), 1
            )
            payload = OrderService.__new__(OrderService)._build_order_item_payload(
                cart_item=SimpleNamespace(
                    product_id=line[0], variant_id=line[1], quantity=1
                ),
                unit_price=line[2],
                product=product,
                variant=None,
            )
            order = await _create_order(session, suffix, [payload])
            product.category_l2 = "Shorts"
            product.category_l3 = None
            await session.commit()
            token = create_access_token(order.user_id)
            order_id = order.id
            item_id = (
                await CrudOrder(session=session, model=Order).get_order_items(order_id)
            )[0].id

        row = next(r for r in await _get_my_orders(token) if r["id"] == order_id)
        item = row["items"][0]
        assert item["id"] == item_id
        assert item["category_l2"] == "Gifts"
        assert item["category_l3"] == "Fun items"
        assert item["category_l2_label_ru"] == "Подарки"
        assert item["category_l3_label_ru"] == "Развлекательные товары"
        assert item["display_title"]
    finally:
        if saved is not None:
            await _restore_product_categories(*saved)


@pytest.mark.asyncio
# Старый OrderItem без snapshot не отдаёт live категорию.
async def test_orders_my_hides_category_without_snapshot(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix + 1
    saved: tuple[int, str | None, str | None] | None = None
    try:
        async with async_session_maker() as session:
            product_id = await pick_active_product_id(session)
            product = await session.get(Product, product_id)
            assert product is not None
            saved = (product.id, product.category_l2, product.category_l3)
            product.category_l2 = "Gifts"
            await session.flush()
            line = await resolve_product_line_spec(
                session, product_id, Decimal("1000"), 1
            )
            order = await _create_order(
                session,
                suffix,
                [
                    {
                        "product_id": line[0],
                        "variant_id": line[1],
                        "quantity": 1,
                        "unit_price": line[2],
                        "product_title_captured": "Legacy item",
                    }
                ],
            )
            token = create_access_token(order.user_id)
            order_id = order.id
            await session.commit()

        row = next(r for r in await _get_my_orders(token) if r["id"] == order_id)
        item = row["items"][0]
        assert item["category_l2"] is None
        assert item["category_l3"] is None
        assert item["category_l2_label_ru"] is None
        assert item["display_title"]
    finally:
        if saved is not None:
            await _restore_product_categories(*saved)
