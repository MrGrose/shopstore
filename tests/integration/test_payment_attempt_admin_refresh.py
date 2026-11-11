import re
from datetime import timedelta
from decimal import Decimal
from os import environ
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderPaymentAttempt,
    OrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import DeliveryAddressCreate
from src.services.payment_service import (
    INIT_STATE_READY,
    merchant_order_id_for,
    x_req_id_for_order,
    x_req_id_for_qr,
)
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import PAYMENT_ACCEPTED_STATUS
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)


# Создаёт заказ с двумя попытками: №1 DECLINED, №2 QRCDATA_CREATED.
async def _create_admin_refresh_scenario(
    session: AsyncSession,
    user_id: int,
    suffix: int,
) -> tuple[Order, OrderPaymentAttempt, OrderPaymentAttempt]:
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
                "product_title_captured": f"Admin refresh test {suffix}",
            }
        ],
        idempotency_key=f"test-admin-refresh-{suffix}",
        delivery_payload=DeliveryAddressCreate(
            last_name="Refresh",
            first_name="Test",
            street="Test St",
            house="1",
            city="Moscow",
            postal_code="101000",
            phone="+79990000002",
        ).model_dump(),
        availability_confirmation_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
    )
    order.status = OrderStatus.PROCESSING
    await order_crud.commit_order(order)

    now = utc_now_naive()
    amount_minor = int(order.total_amount * 100)
    declined_provider_id = f"test-declined-{suffix}"
    active_provider_id = f"test-active-{suffix}"

    declined = await order_crud.create_payment_attempt(
        order_id=order.id,
        attempt_number=1,
        provider="sbp",
        merchant_order_id=merchant_order_id_for(order.id, 1),
        x_req_id_order=x_req_id_for_order(order.id, 1),
        x_req_id_qr=x_req_id_for_qr(order.id, 1),
        payment_amount_minor=amount_minor,
        payment_currency="RUB",
        init_state=INIT_STATE_READY,
    )
    declined.provider_order_id = declined_provider_id
    declined.provider_status = "DECLINED"
    declined.qr_created_at = now - timedelta(minutes=20)
    declined.qr_expires_at = now - timedelta(minutes=5)

    active = await order_crud.create_payment_attempt(
        order_id=order.id,
        attempt_number=2,
        provider="sbp",
        merchant_order_id=merchant_order_id_for(order.id, 2),
        x_req_id_order=x_req_id_for_order(order.id, 2),
        x_req_id_qr=x_req_id_for_qr(order.id, 2),
        payment_amount_minor=amount_minor,
        payment_currency="RUB",
        init_state=INIT_STATE_READY,
    )
    active.provider_order_id = active_provider_id
    active.provider_status = "QRCDATA_CREATED"
    active.qr_created_at = now - timedelta(minutes=2)
    active.qr_expires_at = now + timedelta(minutes=13)

    order.payment_provider = "sbp"
    order.payment_order_id = active_provider_id
    order.payment_status = "QRCDATA_CREATED"
    await session.commit()
    await session.refresh(order)
    await session.refresh(declined)
    await session.refresh(active)
    return order, declined, active


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.integrations.sbp.client.SBPClient.get_order",
    new_callable=AsyncMock,
)
async def test_admin_payment_attempt_refresh_full_scenario(
    mock_get_order: AsyncMock,
    mock_settings,
    merge_unique_suffix: int,
) -> None:
    mock_settings.SBP_ENABLED = True
    suffix = merge_unique_suffix
    order_id = 0
    declined_id = 0
    active_id = 0
    declined_provider_id = f"test-declined-{suffix}"
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, declined, active = await _create_admin_refresh_scenario(
            session,
            buyer.id,
            suffix,
        )
        order_id = order.id
        declined_id = declined.id
        active_id = active.id
        _, admin_token = await create_admin_access_token(session, suffix + 50_000)

    async def get_order_side_effect(provider_order_id: str, x_req_id=None):
        assert provider_order_id == declined_provider_id
        return {"id": provider_order_id, "status": PAYMENT_ACCEPTED_STATUS}

    mock_get_order.side_effect = get_order_side_effect

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        page = await client.get(
            f"/internal/admin/orders?id={order_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert page.status_code == 200
        html = page.text
        assert "Попытки оплаты (2)" in html
        assert "Проверить статус в SBP" in html
        assert (
            f"/internal/admin/orders/{order_id}/payment-attempts/{declined_id}/refresh"
            in html
        )
        refresh_buttons = len(re.findall(r"Проверить статус в SBP", html))
        assert refresh_buttons == 1

        response = await client.post(
            f"/internal/admin/orders/{order_id}/payment-attempts/{declined_id}/refresh",
            data={},
            headers={"Authorization": f"Bearer {admin_token}"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "success=" in response.headers.get("location", "")
    assert "#order-payment" in response.headers.get("location", "")
    mock_get_order.assert_called_once()
    assert mock_get_order.call_args.args[0] == declined_provider_id

    async with async_session_maker() as session:
        refreshed_declined = await session.get(OrderPaymentAttempt, declined_id)
        refreshed_active = await session.get(OrderPaymentAttempt, active_id)
        refreshed_order = await session.get(Order, order_id)
        assert refreshed_declined is not None
        assert refreshed_active is not None
        assert refreshed_order is not None
        assert refreshed_declined.provider_status == PAYMENT_ACCEPTED_STATUS
        assert refreshed_declined.paid_at is not None
        assert refreshed_active.provider_status == "QRCDATA_CREATED"
        assert refreshed_active.paid_at is None
        assert refreshed_order.payment_paid_at is not None
        assert refreshed_order.payment_status == PAYMENT_ACCEPTED_STATUS

    print(
        f"admin-refresh-scenario: order_id={order_id} "
        f"declined_attempt_id={declined_id} "
        f"admin_url=/internal/admin/orders?id={order_id}#order-payment"
    )


@pytest.mark.asyncio
async def test_admin_payment_attempt_refresh_demo_seed(
    merge_unique_suffix: int,
) -> None:
    if environ.get("ALLOW_PAYMENT_ADMIN_REFRESH_DEMO") != "1":
        pytest.skip("Задайте ALLOW_PAYMENT_ADMIN_REFRESH_DEMO=1 для seed в БД")
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, declined, _active = await _create_admin_refresh_scenario(
            session,
            buyer.id,
            suffix,
        )
        await session.commit()
    print(
        "payment-admin-refresh-demo seed:\n"
        f"  order_id={order.id}\n"
        f"  declined_attempt_id={declined.id}\n"
        f"  admin: /internal/admin/orders?id={order.id}#order-payment\n"
        "  кнопка «Проверить статус в SBP» у попытки №1 (DECLINED)\n"
        "  cleanup: DELETE FROM order_payment_attempts WHERE order_id="
        f"{order.id}; DELETE FROM orders WHERE id={order.id};"
    )


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.integrations.sbp.client.SBPClient.get_order",
    new_callable=AsyncMock,
)
async def test_admin_refresh_sbp_error_shows_flash_not_500(
    mock_get_order: AsyncMock,
    mock_settings,
    merge_unique_suffix: int,
) -> None:
    from src.integrations.sbp.errors import SBPApiError

    mock_settings.SBP_ENABLED = True
    mock_get_order.side_effect = SBPApiError("SBP: HTTP 500")
    suffix = merge_unique_suffix
    order_id = 0
    declined_id = 0
    admin_token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, declined, _active = await _create_admin_refresh_scenario(
            session,
            buyer.id,
            suffix,
        )
        order_id = order.id
        declined_id = declined.id
        _, admin_token = await create_admin_access_token(session, suffix + 60_000)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        response = await client.post(
            f"/internal/admin/orders/{order_id}/payment-attempts/{declined_id}/refresh",
            data={},
            headers={"Authorization": f"Bearer {admin_token}"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    location = response.headers.get("location", "")
    assert "error=" in location
    assert "#order-payment" in location

    async with async_session_maker() as session:
        attempt = await session.get(OrderPaymentAttempt, declined_id)
        assert attempt is not None
        assert attempt.provider_status == "DECLINED"
