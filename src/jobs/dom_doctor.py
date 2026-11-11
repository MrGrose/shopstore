import argparse
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import selectinload

from src.jobs.admin_job_snapshots import DOM_DOCTOR_SNAPSHOT, save_admin_job_snapshot
from src.jobs.dom_enqueue_lock import release_dom_enqueue_lock
from src.jobs.dom_processing_claim import claim_dom_processing_products
from src.jobs.dom_product_payload import enqueue_dom_product_chunks, product_payload
from src.jobs.dom_scheduler import reserve_products_with_dedup
from src.jobs.queue import dom_queue_overloaded, get_catalog_queue_stats
from src.models.product import Product
from src.repositories.session import async_session_maker
from src.scraper.config.settings import Settings, load_settings
from src.services.catalog.importing.product_complete import (
    enrichment_hold_sql_criterion,
)

logger = logging.getLogger(__name__)


# SKU без активного DB claim или с истёкшим TTL.
def _processing_claim_available_filter(now: datetime):
    return or_(
        Product.dom_processing_at.is_(None),
        Product.dom_processing_expires_at < now,
    )


# HOLD + cooldown + free claim + active URL: кандидаты Doctor.
def _doctor_filters(env: Settings, now: datetime) -> list:
    retry_before = now - timedelta(seconds=max(0, env.dom_retry_cooldown_seconds))
    max_attempts = max(1, env.dom_max_attempts)
    return [
        enrichment_hold_sql_criterion(max_attempts),
        Product.is_active.is_(True),
        Product.product_url.is_not(None),
        Product.product_url != "",
        or_(
            Product.dom_last_attempt_at.is_(None),
            Product.dom_last_attempt_at <= retry_before,
        ),
        _processing_claim_available_filter(now),
    ]


# Загружает exhausted HOLD SKU и ставит payload.dom_mode=FULL.
async def _load_doctor_candidates(
    env: Settings,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = (
        select(Product)
        .where(*_doctor_filters(env, now))
        .options(
            selectinload(Product.variants),
            selectinload(Product.images),
            selectinload(Product.features),
        )
        .order_by(
            Product.dom_last_attempt_at.asc().nullsfirst(),
            Product.id.asc(),
        )
        .limit(limit)
    )
    async with async_session_maker() as session:
        rows = list((await session.scalars(stmt)).all())
    payloads: list[dict[str, Any]] = []
    for product in rows:
        payload = product_payload(product)
        payload["dom_mode"] = "FULL"
        payloads.append(payload)
    return payloads


# Сбрасывает attempts только у уже claimed SKU. last_error не трогает.
async def _reset_claimed_attempts(claimed: list[dict[str, Any]]) -> int:
    product_ids = sorted(int(p["id"]) for p in claimed if p.get("id") is not None)
    if not product_ids:
        return 0
    async with async_session_maker() as session:
        result = await session.execute(
            update(Product)
            .where(
                Product.id.in_(product_ids),
                Product.dom_processing_at.is_not(None),
            )
            .values(dom_attempts=0)
        )
        await session.commit()
    return int(result.rowcount or 0)


# Базовый result Doctor (enqueue-only, без парсинга).
def _base_result(
    batch_size: int,
    dom_pending: int,
    dom_running: int,
) -> dict[str, Any]:
    return {
        "batch_size": batch_size,
        "dom_pending_jobs": dom_pending,
        "dom_running_jobs": dom_running,
        "eligible": 0,
        "claimed": 0,
        "enqueued": 0,
        "enqueued_jobs": 0,
        "enqueued_products": 0,
        "skipped_locked": 0,
        "skipped_not_claimed": 0,
        "skipped": False,
        "errors": 0,
        "reason": None,
    }


# Один cron-тик: HOLD → claim → reset attempts → enqueue FULL в catalog_dom.
async def enqueue_dom_doctor(
    limit: int | None = None,
    env: Settings | None = None,
) -> dict[str, Any]:
    settings = env or load_settings()
    batch_size = max(1, limit or settings.dom_doctor_batch_size)
    stats = get_catalog_queue_stats()
    dom_pending = int(stats.get("dom_pending_jobs") or 0)
    dom_running = int(stats.get("dom_running_jobs") or 0)
    result = _base_result(batch_size, dom_pending, dom_running)

    if dom_queue_overloaded(settings):
        logger.info(
            "DOM doctor: пропуск — очередь перегружена, pending=%s порог=%s",
            dom_pending,
            settings.dom_queue_max_pending,
        )
        return {**result, "skipped": True, "reason": "dom_queue_overloaded"}

    candidates = await _load_doctor_candidates(settings, batch_size)
    result["eligible"] = len(candidates)
    if not candidates:
        return {**result, "skipped": True, "reason": "empty_selection"}

    owner_token: str | None = None
    if settings.dom_owner_token_enqueue_enabled:
        owner_token = uuid.uuid4().hex
    reserved, skipped_locked = reserve_products_with_dedup(
        candidates, settings, batch_size, owner_token
    )
    result["skipped_locked"] = skipped_locked
    if not reserved:
        return {**result, "skipped": True, "reason": "empty_claim"}

    claimed, skipped_not_claimed = await claim_dom_processing_products(
        reserved, settings, owner_token
    )
    result["skipped_not_claimed"] = skipped_not_claimed
    if skipped_not_claimed:
        claimed_ids = {p.get("id") for p in claimed}
        for product in reserved:
            if product.get("id") not in claimed_ids:
                release_dom_enqueue_lock(product, owner_token)
    if not claimed:
        return {**result, "skipped": True, "reason": "empty_claim"}

    result["claimed"] = len(claimed)
    await _reset_claimed_attempts(claimed)

    try:
        jobs = enqueue_dom_product_chunks(claimed, settings, owner_token)
    except Exception:
        logger.exception(
            "DOM doctor: enqueue не удался после claim, SKU=%s; "
            "повтор через существующий claim TTL",
            [p.get("id") for p in claimed],
        )
        return {
            **result,
            "errors": 1,
            "reason": "enqueue_failed",
        }

    logger.info(
        "DOM doctor: eligible=%s claimed=%s jobs=%s products=%s",
        result["eligible"],
        result["claimed"],
        jobs,
        len(claimed),
    )
    return {
        **result,
        "enqueued": jobs,
        "enqueued_jobs": jobs,
        "enqueued_products": len(claimed),
    }


# CLI entry: HOLD → FULL recovery cycle, без парсинга.
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="DOM doctor: HOLD → enqueue FULL recovery cycle",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = asyncio.run(enqueue_dom_doctor(limit=args.limit))
    save_admin_job_snapshot(DOM_DOCTOR_SNAPSHOT, result)
    logger.info("DOM doctor: итог %s", result)


if __name__ == "__main__":
    main()
