from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order, OrderPaymentAttempt
from src.repositories.order_repo import CrudOrder
from src.services.payment_service import (
    INIT_STATE_READY,
    merchant_order_id_for,
    x_req_id_for_order,
    x_req_id_for_qr,
)
from src.utils.payment import PAYMENT_ACCEPTED_STATUS


def build_sbp_accepted_payload(
    provider_order_id: str,
    attempt: OrderPaymentAttempt,
) -> dict[str, object]:
    return {
        "order": {
            "id": provider_order_id,
            "status": PAYMENT_ACCEPTED_STATUS,
            "merchantOrderId": attempt.merchant_order_id,
            "paymentAmount": attempt.payment_amount_minor,
            "paymentCurrency": str(attempt.payment_currency or "RUB"),
        }
    }


def demo_provider_order_id(order_id: int, attempt_number: int) -> str:
    return f"dev-sbp-{order_id}-{attempt_number}"


async def ensure_sbp_payment_attempt(
    session: AsyncSession,
    order: Order,
    *,
    provider_order_id: str | None = None,
) -> tuple[OrderPaymentAttempt, str]:
    order_crud = CrudOrder(session=session, model=Order)
    latest = await order_crud.get_latest_payment_attempt(order.id)
    if latest is not None and latest.provider_order_id and latest.merchant_order_id:
        provider_id = str(latest.provider_order_id)
        return latest, provider_id

    if latest is not None:
        attempt_number = latest.attempt_number
        attempt = latest
    else:
        attempt_number = await order_crud.count_payment_attempts(order.id) + 1
        attempt = await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=attempt_number,
            provider="sbp",
            merchant_order_id=merchant_order_id_for(order.id, attempt_number),
            x_req_id_order=x_req_id_for_order(order.id, attempt_number),
            x_req_id_qr=x_req_id_for_qr(order.id, attempt_number),
            payment_amount_minor=int(order.total_amount * 100),
            payment_currency="RUB",
            init_state=INIT_STATE_READY,
        )

    provider_id = provider_order_id or demo_provider_order_id(order.id, attempt_number)
    if not attempt.provider_order_id:
        attempt.provider_order_id = provider_id
    if not attempt.provider_status:
        attempt.provider_status = "QRCDATA_CREATED"
    if attempt.init_state != INIT_STATE_READY:
        attempt.init_state = INIT_STATE_READY

    order.payment_provider = order.payment_provider or "sbp"
    order.payment_order_id = provider_id
    order.payment_status = attempt.provider_status
    await session.flush()
    return attempt, str(attempt.provider_order_id)
