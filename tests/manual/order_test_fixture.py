import argparse
import asyncio

from sqlalchemy import select

from src.core.config import settings
from src.models.order import (
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    CANCELLATION_REASON_PAYMENT_TIMEOUT,
    ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
    ORDER_EVENT_CANCELLED_BY_CUSTOMER,
    Order,
    OrderStatus,
)
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService
from src.services.payment_service import PaymentService
from tests.fixtures.sbp_callback import (
    build_sbp_accepted_payload,
    ensure_sbp_payment_attempt,
)

CANCEL_REASONS = {
    "timeout": (
        CANCELLATION_REASON_PAYMENT_TIMEOUT,
        ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
        "Заказ автоматически отменён: срок оплаты истёк (local test)",
        "local-test",
    ),
    "customer": (
        CANCELLATION_REASON_CUSTOMER_REQUEST,
        ORDER_EVENT_CANCELLED_BY_CUSTOMER,
        "Заказ отменён клиентом (local test)",
        "local-test",
    ),
}


def require_dev_environment() -> None:
    if not settings.is_dev:
        raise SystemExit(
            "order_test_fixture разрешён только при APP_ENV=dev "
            f"(сейчас APP_ENV={settings.APP_ENV!r})"
        )


# Отменяет неоплаченный заказ через OrderService (событие + остатки).
async def cancel_order(order_id: int, reason: str) -> None:
    cancellation_reason, event_type, event_message, created_by = CANCEL_REASONS[reason]

    async with async_session_maker() as session:
        service = OrderService(session)
        order = await service.order_crud.get_by_id_for_update(order_id)
        if order is None:
            raise SystemExit(f"Заказ #{order_id} не найден")
        if order.payment_paid_at is not None:
            raise SystemExit(f"Заказ #{order_id} уже оплачен")
        if str(order.status or "").lower() == OrderStatus.CANCELLED:
            print(f"Заказ #{order_id} уже отменён ({order.cancellation_reason})")
            return

        await service._apply_order_cancellation(
            order,
            cancellation_reason=cancellation_reason,
            event_type=event_type,
            event_message=event_message,
            created_by=created_by,
        )
        await session.commit()
        print(f"Заказ #{order_id} отменён ({cancellation_reason})")


# Проставляет оплату через synthetic SBP callback (production flow).
async def mark_order_paid(order_id: int, *, late: bool) -> None:
    async with async_session_maker() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            raise SystemExit(f"Заказ #{order_id} не найден")
        if order.payment_paid_at is not None:
            print(
                f"Заказ #{order_id} уже оплачен "
                f"({order.payment_paid_at}, {order.payment_status})"
            )
            return

        if late:
            if str(order.status or "").lower() != OrderStatus.CANCELLED:
                raise SystemExit(
                    "Для late payment заказ должен быть отменён "
                    "(make order-cancel ORDER_ID=...)"
                )
            if order.cancellation_reason != CANCELLATION_REASON_PAYMENT_TIMEOUT:
                raise SystemExit(
                    "Для late payment нужна отмена по payment_timeout "
                    "(make order-cancel ORDER_ID=...)"
                )

        attempt, provider_order_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await session.refresh(order)
        await session.refresh(attempt)

        payment_service = PaymentService(session)
        await payment_service.handle_sbp_callback(
            build_sbp_accepted_payload(provider_order_id, attempt)
        )

        await session.refresh(order)
        await session.refresh(attempt)
        if order.payment_paid_at is None:
            raise SystemExit(
                f"Callback не подтвердил оплату заказа #{order_id} "
                f"(attempt_id={attempt.id})"
            )

        suffix = " · late payment" if late else ""
        print(
            f"Заказ #{order_id} оплачен через synthetic SBP callback"
            f"{suffix} (attempt_id={attempt.id})"
        )


# Печатает краткий статус заказа.
async def show_order(order_id: int) -> None:
    async with async_session_maker() as session:
        order = await session.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            raise SystemExit(f"Заказ #{order_id} не найден")
        print(
            f"#{order.id} status={order.status} paid_at={order.payment_paid_at} "
            f"cancel_reason={order.cancellation_reason} "
            f"payment_status={order.payment_status}"
        )


async def main() -> None:
    require_dev_environment()

    parser = argparse.ArgumentParser(
        description="Dev-фикстуры статуса заказа (отмена / synthetic payment callback)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cancel_parser = sub.add_parser("cancel", help="Отменить неоплаченный заказ")
    cancel_parser.add_argument("--order-id", type=int, required=True)
    cancel_parser.add_argument(
        "--reason",
        choices=sorted(CANCEL_REASONS),
        default="timeout",
        help="Причина отмены (default: timeout)",
    )

    paid_parser = sub.add_parser("paid", help="Synthetic SBP callback IPS_ACCEPTED")
    paid_parser.add_argument("--order-id", type=int, required=True)
    paid_parser.add_argument(
        "--late",
        action="store_true",
        help="Проверить preconditions для late payment после auto-cancel",
    )

    show_parser = sub.add_parser("show", help="Показать статус заказа")
    show_parser.add_argument("--order-id", type=int, required=True)

    args = parser.parse_args()
    if args.command == "cancel":
        await cancel_order(args.order_id, args.reason)
    elif args.command == "paid":
        await mark_order_paid(args.order_id, late=args.late)
    else:
        await show_order(args.order_id)


if __name__ == "__main__":
    asyncio.run(main())
