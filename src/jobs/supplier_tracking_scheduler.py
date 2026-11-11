import argparse
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from src.jobs.queue import get_supplier_tracking_queue
from src.models.order import Order, OrderStatus, Shipment, ShipmentStatus
from src.repositories.session import async_session_maker

logger = logging.getLogger(__name__)


# Ставит sync трекинга заказа в RQ-очередь supplier_tracking.
def enqueue_supplier_tracking(order_id: int):
    queue = get_supplier_tracking_queue()
    job_id = f"supplier-tracking-{order_id}"
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
        "src.jobs.supplier_tracking_job.run_supplier_tracking_job",
        order_id,
        job_id=job_id,
        job_timeout=90,
        result_ttl=86400,
        failure_ttl=604800,
    )


# Due: есть недоставленная Shipment, либо legacy Order без Shipment с next_check.
def tracking_due_filters(now: datetime) -> list[ColumnElement[bool]]:
    undelivered = exists(
        select(Shipment.id).where(
            Shipment.order_id == Order.id,
            Shipment.status != ShipmentStatus.DELIVERED,
        )
    )
    has_shipment = exists(select(Shipment.id).where(Shipment.order_id == Order.id))
    next_due = or_(
        Order.supplier_tracking_next_check_at.is_(None),
        Order.supplier_tracking_next_check_at <= now,
    )
    legacy_no_shipment = (
        ~has_shipment
        & Order.supplier_order_id.is_not(None)
        & Order.supplier_tracking_next_check_at.is_not(None)
        & (Order.supplier_tracking_next_check_at <= now)
    )
    return [
        Order.status.not_in(
            [OrderStatus.CANCELLED, OrderStatus.FAILED, OrderStatus.COMPLETED]
        ),
        or_(undelivered & next_due, legacy_no_shipment),
    ]


# Заказы, которым нужен tracking sync в этом тике.
async def list_due_supplier_tracking_order_ids(
    session: AsyncSession, now: datetime, limit: int = 100
) -> list[int]:
    stmt = (
        select(Order.id)
        .where(*tracking_due_filters(now))
        .order_by(Order.supplier_tracking_next_check_at.asc().nullsfirst())
        .limit(max(1, limit))
    )
    return [int(order_id) for order_id in (await session.scalars(stmt)).all()]


# Находит due-заказы и ставит их sync в очередь.
async def enqueue_due_supplier_tracking(limit: int = 100) -> dict[str, int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    async with async_session_maker() as session:
        order_ids = await list_due_supplier_tracking_order_ids(session, now, limit)

    enqueued = 0
    for order_id in order_ids:
        try:
            enqueue_supplier_tracking(int(order_id))
            enqueued += 1
        except Exception:
            logger.exception("Очередь проверки трекинга поставщика: order=%s", order_id)
    return {"selected": len(order_ids), "enqueued": enqueued}


# CLI: один тик scheduler для cron/make prod-supplier-tracking.
def main() -> None:
    parser = argparse.ArgumentParser(description="Очередь проверки трекинга поставщика")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    result = asyncio.run(enqueue_due_supplier_tracking(args.limit))
    logger.info("Очередь проверки трекинга поставщика: %s", result)


if __name__ == "__main__":
    main()
