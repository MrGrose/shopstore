import os
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from src.core.config import settings
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderItem,
    OrderPaymentAttempt,
    OrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import DeliveryAddressCreate
from src.services.identity_service import IdentityService
from src.services.payment_service import (
    INIT_STATE_CREATING,
    INIT_STATE_READY,
    merchant_order_id_for,
    x_req_id_for_order,
    x_req_id_for_qr,
)
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    pick_active_product_id,
    resolve_product_line_spec,
)

# Manual seed/cleanup для проверки UI оплаты в dev.
#
# Seed (SBP_ENABLED должен быть false):
#   ALLOW_PAYMENT_UI_DEMO_SEED=1 PAYMENT_UI_DEMO_ACTION=seed \
#     pytest -s tests/manual/test_payment_ui_demo.py
# Cleanup:
#   ALLOW_PAYMENT_UI_DEMO_SEED=1 PAYMENT_UI_DEMO_ACTION=cleanup \
#     pytest -s tests/manual/test_payment_ui_demo.py

DEMO_KEY_PREFIX = "payment-ui-demo:"

DELIVERY_PAYLOAD = DeliveryAddressCreate(
    last_name="Demo",
    first_name="PaymentUI",
    street="Demo St",
    house="1",
    city="Moscow",
    postal_code="101000",
    phone="+79990000001",
).model_dump()


def _demo_idempotency_key(state: str, admin_tg_id: int) -> str:
    return f"{DEMO_KEY_PREFIX}{state}:{admin_tg_id}"


def _demo_idempotency_pattern(admin_tg_id: int) -> str:
    return f"{DEMO_KEY_PREFIX}%:{admin_tg_id}"


# Проверяет guard-условия manual seed/cleanup.
def _resolve_demo_action() -> str:
    action = os.environ.get("PAYMENT_UI_DEMO_ACTION", "").strip().lower()
    if not action:
        pytest.skip("Задайте PAYMENT_UI_DEMO_ACTION=seed или cleanup")
    if action not in {"seed", "cleanup"}:
        pytest.fail(f"Неизвестное PAYMENT_UI_DEMO_ACTION={action!r}")
    if not settings.is_dev:
        pytest.fail("payment-ui-demo запрещён вне dev (APP_ENV != dev)")
    if os.environ.get("ALLOW_PAYMENT_UI_DEMO_SEED") != "1":
        pytest.skip("Задайте ALLOW_PAYMENT_UI_DEMO_SEED=1")
    if action == "seed" and settings.SBP_ENABLED:
        pytest.fail(
            "payment-ui-demo seed запрещён при SBP_ENABLED=true: "
            "«Продолжить оплату» вызовет SBP. "
            "Отключите SBP_ENABLED в .env."
        )
    return action


# Возвращает admin-пользователя по TG_ADMIN_ID из .env.
async def _resolve_admin_user(session):
    admin_tg_id = settings.TG_ADMIN_ID
    if admin_tg_id <= 0:
        pytest.fail("TG_ADMIN_ID должен быть задан в .env")
    identity_svc = IdentityService(session)
    user = await identity_svc.resolve_user_by_telegram_id(admin_tg_id)
    if user is None:
        pytest.fail(f"Пользователь с Telegram ID {admin_tg_id} не найден")
    linked_tg_id = await identity_svc.get_telegram_id_for_user(user)
    if linked_tg_id != admin_tg_id:
        pytest.fail(
            f"Найден user_id={user.id}, но telegram_id={linked_tg_id} != TG_ADMIN_ID"
        )
    return user, admin_tg_id


# Конфигурация демо-заказов по состояниям оплаты.
def _demo_cases(admin_tg_id: int) -> list[dict[str, object]]:
    now = utc_now_naive()
    paid_at = now - timedelta(hours=2)
    provider_suffix = str(admin_tg_id)
    return [
        {
            "state": "paid",
            "order_status": OrderStatus.PROCESSING,
            "attempt_status": "IPS_ACCEPTED",
            "attempt_paid_at": paid_at,
            "provider_order_id": f"demo-paid-{provider_suffix}",
        },
        {
            "state": "waiting",
            "order_status": OrderStatus.PROCESSING,
            "attempt_status": "IN_PROCESS",
            "provider_order_id": f"demo-waiting-{provider_suffix}",
            "qr_expires_at": now + timedelta(minutes=10),
        },
        {
            "state": "initializing",
            "order_status": OrderStatus.PROCESSING,
            "attempt_status": "CREATED",
            "init_state": INIT_STATE_CREATING,
            "provider_order_id": f"demo-init-{provider_suffix}",
        },
        {
            "state": "declined",
            "order_status": OrderStatus.PROCESSING,
            "attempt_status": "DECLINED",
            "provider_order_id": f"demo-declined-{provider_suffix}",
        },
        {
            "state": "expired",
            "order_status": OrderStatus.PROCESSING,
            "attempt_status": "DECLINED",
            "provider_order_id": f"demo-expired-{provider_suffix}",
            "qr_expires_at": now - timedelta(minutes=5),
        },
        {
            "state": "not_started",
            "order_status": OrderStatus.PROCESSING,
        },
        {
            "state": "completed_unpaid",
            "order_status": OrderStatus.COMPLETED,
        },
        {
            "state": "paid_in_delivery",
            "order_status": OrderStatus.DELIVERY,
            "attempt_status": "IPS_ACCEPTED",
            "attempt_paid_at": paid_at - timedelta(days=1),
            "provider_order_id": f"demo-delivery-{provider_suffix}",
        },
    ]


# Сбрасывает payment-поля заказа и применяет агрегат из attempt.
def _apply_demo_order_payment(order: Order, case: dict[str, object]) -> None:
    order.status = str(case["order_status"])
    order.availability_confirmation_status = AvailabilityConfirmationStatus.NOT_REQUIRED
    order.payment_provider = None
    order.payment_order_id = None
    order.payment_external_order_id = None
    order.payment_status = None
    order.payment_qr_id = None
    order.payment_qr_payload = None
    order.payment_meta_json = None
    order.payment_paid_at = None
    order.payment_last_callback_at = None
    if case.get("attempt_status"):
        order.payment_provider = "sbp"
        order.payment_order_id = case.get("provider_order_id")  # type: ignore
        order.payment_status = case.get("attempt_status")  # type: ignore
        order.payment_paid_at = case.get("attempt_paid_at")  # type: ignore


# Создаёт или обновляет demo-attempt для заказа.
async def _upsert_demo_attempt(
    session,
    order: Order,
    case: dict[str, object],
) -> OrderPaymentAttempt | None:
    await session.execute(
        delete(OrderPaymentAttempt).where(OrderPaymentAttempt.order_id == order.id)
    )
    if not case.get("attempt_status"):
        return None
    qr_expires_at = case.get("qr_expires_at")
    qr_created_at = None
    if qr_expires_at is not None:
        qr_created_at = qr_expires_at - timedelta(minutes=15)  # type: ignore[operator]
    attempt = OrderPaymentAttempt(
        order_id=order.id,
        attempt_number=1,
        provider="sbp",
        merchant_order_id=merchant_order_id_for(order.id, 1),
        x_req_id_order=x_req_id_for_order(order.id, 1),
        x_req_id_qr=x_req_id_for_qr(order.id, 1),
        payment_amount_minor=int(order.total_amount * 100),
        payment_currency="RUB",
        init_state=str(case.get("init_state") or INIT_STATE_READY),
        provider_order_id=case.get("provider_order_id"),  # type: ignore[arg-type]
        provider_status=str(case.get("attempt_status")),
        qr_created_at=qr_created_at,
        qr_expires_at=qr_expires_at,  # type: ignore[arg-type]
        paid_at=case.get("attempt_paid_at"),  # type: ignore[arg-type]
    )
    session.add(attempt)
    await session.flush()
    return attempt


# Создаёт или обновляет demo-заказ по idempotency_key.
async def _upsert_demo_order(
    session,
    user_id: int,
    admin_tg_id: int,
    case: dict[str, object],
    product_line: tuple[int, int | None, Decimal, int],
) -> Order:
    state = str(case["state"])
    idempotency_key = _demo_idempotency_key(state, admin_tg_id)
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.get_by_idempotency_key(idempotency_key)
    product_id, variant_id, unit_price, quantity = product_line
    if order is None:
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
                    "product_title_captured": f"Payment UI demo ({state})",
                }
            ],
            idempotency_key=idempotency_key,
            delivery_payload=DELIVERY_PAYLOAD,
            availability_confirmation_status=(
                AvailabilityConfirmationStatus.NOT_REQUIRED
            ),
        )
    elif order.user_id != user_id:
        pytest.fail(
            f"Demo-заказ {idempotency_key!r} принадлежит user_id={order.user_id}, "
            f"ожидался {user_id}"
        )
    _apply_demo_order_payment(order, case)
    session.add(order)
    await session.flush()
    await _upsert_demo_attempt(session, order, case)
    return order


# Удаляет demo-заказы admin-пользователя (payment-ui-demo:*:TG_ADMIN_ID).
async def _cleanup_demo_orders(session, user_id: int, admin_tg_id: int) -> int:
    order_ids = list(
        await session.scalars(
            select(Order.id).where(
                Order.user_id == user_id,
                Order.idempotency_key.like(_demo_idempotency_pattern(admin_tg_id)),
            )
        )
    )
    if not order_ids:
        await session.commit()
        return 0
    await session.execute(
        delete(OrderPaymentAttempt).where(OrderPaymentAttempt.order_id.in_(order_ids))
    )
    await session.execute(delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids)))
    await session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    result = await session.execute(delete(Order).where(Order.id.in_(order_ids)))
    await session.commit()
    return int(result.rowcount or 0)


@pytest.mark.asyncio
async def test_payment_ui_demo() -> None:
    action = _resolve_demo_action()
    async with async_session_maker() as session:
        user, admin_tg_id = await _resolve_admin_user(session)
        if action == "cleanup":
            removed = await _cleanup_demo_orders(session, user.id, admin_tg_id)
            print(
                f"payment-ui-demo cleanup: user_id={user.id} "
                f"telegram_id={admin_tg_id} удалено заказов {removed}"
            )
            return

        product_id = await pick_active_product_id(session)
        product_line = await resolve_product_line_spec(
            session,
            product_id,
            Decimal("1500"),
            1,
        )
        created: list[tuple[str, int]] = []
        for case in _demo_cases(admin_tg_id):
            order = await _upsert_demo_order(
                session,
                user.id,
                admin_tg_id,
                case,
                product_line,
            )
            created.append((str(case["state"]), order.id))
        await session.commit()
        for state, order_id in created:
            print(f"payment-ui-demo seed: {state} -> order #{order_id}")
        print(f"payment-ui-demo seed: user_id={user.id} telegram_id={admin_tg_id}")
