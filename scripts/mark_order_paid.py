import argparse
import asyncio
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from src.core.config import settings
from src.models.order import Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.customer_notification_service import CustomerNotificationService
from src.services.orders.supplier_orders import SupplierOrderService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import PAYMENT_ACCEPTED_STATUS

MANUAL_PAYMENT_EVENT = "payment_manual_received"


# Prod: без совпадающего --confirm-order-id ничего не меняем.
def require_prod_confirmation(order_id: int, confirm_order_id: int | None) -> None:
    if settings.is_dev:
        return
    if confirm_order_id != order_id:
        raise SystemExit(
            "На production укажи CONFIRM=<order_id>, совпадающий с ORDER_ID "
            f"(сейчас ORDER_ID={order_id}, CONFIRM={confirm_order_id})"
        )


# Ручная оплата: freeze paid_n + попытка + mark paid (как локальный make order-paid).
async def mark_order_paid(
    order_id: int,
    confirm_order_id: int | None = None,
) -> None:
    require_prod_confirmation(order_id, confirm_order_id)

    async with async_session_maker() as session:
        orders = CrudOrder(session=session, model=Order)
        order = await orders.get_by_id_for_update(order_id)
        if order is None:
            raise SystemExit(f"Заказ #{order_id} не найден")

        supplier_svc = SupplierOrderService(session)

        if order.payment_paid_at is not None:
            if order.paid_supplier_order_count is None:
                paid_n = await supplier_svc.freeze_paid_supplier_order_count(order)
                await session.commit()
                print(
                    f"Заказ #{order_id} уже оплачен; "
                    f"дополнил paid_supplier_order_count={paid_n}"
                )
                return
            print(
                f"Заказ #{order_id} уже оплачен: "
                f"{order.payment_paid_at} "
                f"(paid_supplier_order_count={order.paid_supplier_order_count})"
            )
            return

        if str(order.status or "").lower() == OrderStatus.CANCELLED:
            raise SystemExit(
                f"Заказ #{order_id} отменён. "
                "Для late payment используй "
                "tests/manual/order_test_fixture.py paid --late"
            )

        now = utc_now_naive()
        paid_n = await supplier_svc.freeze_paid_supplier_order_count(order)

        attempt_number = await orders.count_payment_attempts(order.id) + 1
        token = uuid4().hex
        attempt = await orders.create_payment_attempt(
            order_id=order.id,
            attempt_number=attempt_number,
            provider="manual",
            merchant_order_id=f"manual-{order.id}-{attempt_number}",
            x_req_id_order=f"manual-order-{token}",
            x_req_id_qr=f"manual-qr-{token}",
            payment_amount_minor=int(Decimal(str(order.total_amount)) * 100),
            payment_currency="RUB",
            init_state="ready",
        )
        attempt.provider_order_id = f"manual-{order.id}-{attempt.id}"

        accepted_attempt_id = await orders.mark_payment_attempt_paid_if_unpaid(
            attempt.id,
            paid_at=now,
            provider_status=PAYMENT_ACCEPTED_STATUS,
            last_callback_at=now,
        )
        if accepted_attempt_id is None:
            raise SystemExit(f"Не удалось подтвердить payment attempt #{attempt.id}")

        attempt.provider_status = PAYMENT_ACCEPTED_STATUS
        attempt.paid_at = now
        attempt.last_callback_at = now

        order_accepted_id = await orders.mark_payment_accepted_if_unpaid(
            order.id,
            payment_status=PAYMENT_ACCEPTED_STATUS,
            payment_paid_at=now,
            payment_last_callback_at=now,
            paid_supplier_order_count=paid_n,
        )
        if order_accepted_id is None:
            raise SystemExit(f"Не удалось подтвердить оплату заказа #{order_id}")

        order.payment_paid_at = now
        order.payment_status = PAYMENT_ACCEPTED_STATUS
        order.paid_supplier_order_count = paid_n

        await orders.sync_order_payment_aggregate(
            order,
            attempt,
            is_latest_attempt=True,
        )
        await orders.create_order_event(
            order_id=order.id,
            event_type=MANUAL_PAYMENT_EVENT,
            event_message="Оплата подтверждена вручную",
            created_by="scripts/mark_order_paid.py",
            payload_json={
                "payment_status": PAYMENT_ACCEPTED_STATUS,
                "payment_attempt_id": attempt.id,
                "payment_provider": "manual",
                "paid_supplier_order_count": paid_n,
            },
        )
        await CustomerNotificationService(session).notify_payment_received(order.id)
        await session.commit()

        print(
            f"Заказ #{order.id} отмечен оплаченным: "
            f"{datetime.isoformat(now, sep=' ', timespec='seconds')} "
            f"(attempt_id={attempt.id}, paid_supplier_order_count={paid_n})"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ручная фиксация оплаты заказа")
    parser.add_argument("--order-id", type=int, required=True)
    parser.add_argument(
        "--confirm-order-id",
        type=int,
        default=None,
        help="На production обязателен и должен совпадать с --order-id",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(mark_order_paid(args.order_id, confirm_order_id=args.confirm_order_id))


if __name__ == "__main__":
    main()
