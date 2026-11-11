import argparse
import asyncio
import logging
from datetime import datetime

from sqlalchemy import DateTime, cast, select
from sqlalchemy.dialects.postgresql import JSONB

from src.core.config import settings
from src.jobs.queue import get_delivered_alert_retry_queue
from src.models.order import Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.admin_notification_service import (
    ADMIN_DELIVERED_ALERT_KEY,
    delivered_alert_retry_is_due,
    shipment_delivered_alert_retry_is_due,
)
from src.utils.datetime_fmt import utc_now_naive

logger = logging.getLogger(__name__)


# Ставит PLACED shipment retry job в очередь.
def enqueue_shipment_delivered_alert_retry(
    shipment_id: int,
    delay_minutes: int | None = None,
):
    if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
        return None
    delay = max(0, int(delay_minutes or 0))
    if delay > 0:
        logger.info(
            "Повторная отправка оповещения о доставке посылки отложена на %s мин "
            "(shipment_id=%s); ждёт scheduler",
            delay,
            shipment_id,
        )
        return None
    queue = get_delivered_alert_retry_queue()
    job_id = f"delivered-alert-retry-shipment-{shipment_id}"
    existing = queue.fetch_job(job_id)
    if existing is not None:
        if existing.get_status(refresh=True) in {
            "queued",
            "started",
            "deferred",
            "scheduled",
        }:
            return existing
        existing.delete()
    return queue.enqueue(
        "src.jobs.orders.delivered_alert_retry_job."
        "run_shipment_delivered_alert_retry_job",
        shipment_id,
        job_id=job_id,
        job_timeout=120,
        result_ttl=86400,
        failure_ttl=604800,
    )


# Ставит retry job в очередь. Отложенный запуск — через cron scheduler.
def enqueue_delivered_alert_retry(
    order_id: int,
    delay_minutes: int | None = None,
):
    if settings.TG_ORDERS_CHAT_ID == 0 or not settings.TG_BOT_SHOP:
        return None
    delay = max(0, int(delay_minutes or 0))
    if delay > 0:
        logger.info(
            "Повторная отправка оповещения о доставке отложена на %s мин "
            "(order_id=%s); ждёт scheduler",
            delay,
            order_id,
        )
        return None
    queue = get_delivered_alert_retry_queue()
    job_id = f"delivered-alert-retry-{order_id}"
    existing = queue.fetch_job(job_id)
    if existing is not None:
        if existing.get_status(refresh=True) in {
            "queued",
            "started",
            "deferred",
            "scheduled",
        }:
            return existing
        existing.delete()
    return queue.enqueue(
        "src.jobs.orders.delivered_alert_retry_job.run_delivered_alert_retry_job",
        order_id,
        job_id=job_id,
        job_timeout=120,
        result_ttl=86400,
        failure_ttl=604800,
    )


async def enqueue_due_delivered_alert_retries(
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, int]:
    current = now or utc_now_naive()
    async with async_session_maker() as session:
        tracking_json = cast(Order.supplier_tracking_json, JSONB)
        alert_json = tracking_json[ADMIN_DELIVERED_ALERT_KEY]
        stmt = (
            select(Order.id, Order.supplier_tracking_json)
            .where(
                Order.supplier_tracking_json.is_not(None),
                # Legacy A: только delivery. Completed больше не ретраит A как C.
                Order.status == OrderStatus.DELIVERY,
                alert_json["pending_retry"].astext == "true",
                alert_json["next_retry_at"].astext.is_not(None),
                cast(alert_json["next_retry_at"].astext, DateTime) <= current,
            )
            .order_by(cast(alert_json["next_retry_at"].astext, DateTime).asc())
            .limit(max(1, limit))
        )
        rows = (await session.execute(stmt)).all()
        crud = CrudOrder(session=session, model=Order)
        shipments = await crud.list_shipments_pending_delivered_alert_retry(
            current, max(1, limit)
        )
        shipment_order_ids: set[int] = set()
        for order_id, _tracking in rows:
            if await crud.list_shipments_for_order(int(order_id)):
                shipment_order_ids.add(int(order_id))

    enqueued = 0
    for order_id, tracking_json in rows:
        if int(order_id) in shipment_order_ids:
            continue
        order = Order(id=int(order_id), supplier_tracking_json=tracking_json)
        if not delivered_alert_retry_is_due(order, now=current):
            continue
        try:
            job = enqueue_delivered_alert_retry(int(order_id), delay_minutes=0)
            if job is not None:
                enqueued += 1
        except Exception:
            logger.exception(
                "Очередь повторов оповещений о доставке заказа: "
                "ошибка при добавлении в очередь (заказ=%s)",
                order_id,
            )
    for row in shipments:
        if not shipment_delivered_alert_retry_is_due(row, now=current):
            continue
        try:
            job = enqueue_shipment_delivered_alert_retry(int(row.id), delay_minutes=0)
            if job is not None:
                enqueued += 1
        except Exception:
            logger.exception(
                "Очередь повторов оповещений о доставке посылки: "
                "ошибка при добавлении в очередь (shipment_id=%s)",
                row.id,
            )
    return {
        "selected": len(rows) + len(shipments),
        "enqueued": enqueued,
    }


# Основная функция для запуска scheduler.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Очередь повторов оповещений о доставке заказа",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--order-id", type=int, default=None)
    parser.add_argument("--shipment-id", type=int, default=None)
    args = parser.parse_args()
    if args.shipment_id is not None:
        job = enqueue_shipment_delivered_alert_retry(args.shipment_id, delay_minutes=0)
        logger.info(
            "Очередь повторов оповещений о доставке посылки: shipment_id=%s job=%s",
            args.shipment_id,
            job,
        )
        return
    if args.order_id is not None:
        job = enqueue_delivered_alert_retry(args.order_id, delay_minutes=0)
        logger.info(
            "Очередь повторов оповещений о доставке заказа: заказ=%s job=%s",
            args.order_id,
            job,
        )
        return
    result = asyncio.run(enqueue_due_delivered_alert_retries(args.limit))
    logger.info("Очередь повторов оповещений о доставке заказа: %s", result)


if __name__ == "__main__":
    main()
