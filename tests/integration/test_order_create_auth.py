import httpx
import pytest
from sqlalchemy import select

from src.core.security import create_access_token
from src.main import app
from src.models.product import Product
from src.repositories.session import async_session_maker
from src.services.cart_service import CartService
from src.services.user_service import UserService

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
async def test_post_orders_legacy_returns_410_anonymous() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post("/orders", json={})
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_post_orders_legacy_returns_410_with_body_user_id() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post("/orders", json={"user_id": 999999})
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_post_orders_checkout_anonymous_returns_401() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post("/orders/checkout", json=_CHECKOUT_PAYLOAD)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_post_orders_checkout_phone_only_without_telegram_returns_409(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    phone_e164 = f"+7998{suffix:07d}"
    user_id = 0
    product_id = 0

    async with async_session_maker() as session:
        product_id = await session.scalar(
            select(Product.id).where(Product.is_active.is_(True)).limit(1)
        )
        if product_id is None:
            pytest.skip("нужен хотя бы один активный товар в каталоге")

        user = await UserService(session).register_user_by_phone(phone_e164)
        user_id = user.id
        await CartService(session).add_or_update_item(
            user_id=user_id,
            product_id=int(product_id),
            quantity=1,
        )

    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        **_CHECKOUT_PAYLOAD,
        "delivery": {**_CHECKOUT_PAYLOAD["delivery"], "phone": phone_e164},
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        checkout = await client.post(
            "/orders/checkout",
            json=payload,
            headers=headers,
        )
        cart = await client.get("/cart/me", headers=headers)

    assert checkout.status_code == 409
    detail = checkout.json()["detail"]
    assert detail["code"] == "telegram_required"
    assert "Telegram" in detail["message"]
    assert cart.status_code == 200
    assert len(cart.json().get("items") or []) == 1
    assert cart.json()["items"][0]["product_id"] == product_id
