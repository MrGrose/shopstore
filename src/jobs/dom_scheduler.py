import argparse
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from src.jobs.admin_job_snapshots import (
    ROLLING_REFRESH_SNAPSHOT,
    save_admin_job_snapshot,
)
from src.jobs.dom_enqueue_lock import (
    release_dom_enqueue_lock,
    try_acquire_dom_enqueue_lock,
)
from src.jobs.dom_processing_claim import claim_dom_processing_products
from src.jobs.dom_product_payload import enqueue_dom_product_chunks, product_payload
from src.jobs.queue import dom_queue_overloaded, get_catalog_queue_stats
from src.models.product import Product
from src.repositories.session import async_session_maker
from src.scraper.config.settings import (
    Settings,
    load_settings,
    resolved_dom_enqueue_lock_ttl_seconds,
)
from src.services.catalog.importing.dom_mode import dom_enrichment_mode
from src.services.catalog.importing.product_complete import (
    is_product_complete,
    product_incomplete_sql_criterion,
    recoverable_imprint_sql_criterion,
)

logger = logging.getLogger(__name__)


# SKU без активного DB claim или с истёкшим TTL.
def _processing_claim_available_filter(now: datetime):
    return or_(
        Product.dom_processing_at.is_(None),
        Product.dom_processing_expires_at < now,
    )


# Базовые фильтры retry/eligibility для DOM scheduler.
def _base_dom_filters(env: Settings, now: datetime) -> list:
    retry_before = now - timedelta(seconds=max(0, env.dom_retry_cooldown_seconds))
    max_attempts = max(1, env.dom_max_attempts)
    return [
        Product.is_active.is_(True),
        Product.product_url.is_not(None),
        Product.dom_attempts < max_attempts,
        or_(
            Product.dom_last_attempt_at.is_(None),
            Product.dom_last_attempt_at <= retry_before,
        ),
        _processing_claim_available_filter(now),
    ]


# Сколько imprint-recovery SKU можно взять, не забивая обычный batch.
def _priority_recovery_cap(batch_size: int, env: Settings) -> int:
    configured = max(0, int(getattr(env, "dom_priority_recovery_limit", 20) or 0))
    return min(configured, max(0, batch_size) // 2)


# Dedup: priority FULL → stock_zero FULL → window FULL → LITE.
def _merge_dom_candidate_groups(
    priority: list[dict[str, Any]],
    stock_zero: list[dict[str, Any]],
    window_full: list[dict[str, Any]],
    window_lite: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for row in (*priority, *stock_zero, *window_full, *window_lite):
        product_id = row.get("id")
        if product_id in seen:
            continue
        seen.add(product_id)
        merged.append(row)
    return merged


# Загружает active SKU с relations для is_product_complete().
async def _load_scheduler_products(
    env: Settings,
    limit: int,
) -> list[Product]:
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = (
        select(Product)
        .where(*_base_dom_filters(env, now))
        .options(
            selectinload(Product.variants),
            selectinload(Product.images),
            selectinload(Product.features),
        )
        .order_by(Product.catalog_synced_at.asc().nullsfirst(), Product.id.asc())
        .limit(max(1, limit))
    )
    async with async_session_maker() as session:
        return list((await session.scalars(stmt)).all())


# Загружает INCOMPLETE SKU с stock=0 (backfill priority).
async def _load_stock_zero_incomplete(
    env: Settings,
    limit: int,
) -> list[dict[str, Any]]:
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = (
        select(Product)
        .where(
            *_base_dom_filters(env, now),
            Product.stock == 0,
            product_incomplete_sql_criterion(),
        )
        .options(
            selectinload(Product.variants),
            selectinload(Product.images),
            selectinload(Product.features),
        )
        .order_by(Product.dom_attempts.asc(), Product.id.asc())
        .limit(max(1, limit))
    )
    async with async_session_maker() as session:
        rows = list((await session.scalars(stmt)).all())
    payloads: list[dict[str, Any]] = []
    for product in rows:
        if is_product_complete(product):
            continue
        payload = product_payload(product)
        payload["dom_mode"] = "FULL"
        payloads.append(payload)
    return payloads


# Узкий recovery: imprint + dom_full_at + image, вне обычного fetch window.
async def _load_priority_recoverable_incomplete(
    env: Settings,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = (
        select(Product)
        .where(
            *_base_dom_filters(env, now),
            recoverable_imprint_sql_criterion(),
        )
        .options(
            selectinload(Product.variants),
            selectinload(Product.images),
            selectinload(Product.features),
        )
        .order_by(
            Product.dom_last_attempt_at.asc().nullsfirst(),
            Product.catalog_synced_at.asc(),
            Product.id.asc(),
        )
        .limit(limit)
    )
    async with async_session_maker() as session:
        rows = list((await session.scalars(stmt)).all())
    payloads: list[dict[str, Any]] = []
    for product in rows:
        if is_product_complete(product):
            continue
        payload = product_payload(product)
        payload["dom_mode"] = "FULL"
        payloads.append(payload)
    return payloads


# Делит SKU на INCOMPLETE (FULL) и COMPLETE stale (LITE).
def _split_scheduler_candidates(
    products: list[Product],
    env: Settings,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stale_before = now - timedelta(hours=max(0, env.dom_refresh_stale_hours))
    full_rows: list[tuple[datetime | None, int, dict[str, Any]]] = []
    lite_rows: list[tuple[datetime | None, int, dict[str, Any]]] = []

    for product in products:
        payload = product_payload(product)
        synced = product.catalog_synced_at
        if is_product_complete(product):
            if synced is not None and synced >= stale_before:
                continue
            payload["dom_mode"] = "LITE"
            lite_rows.append((synced, int(product.id), payload))
        else:
            payload["dom_mode"] = dom_enrichment_mode(product)
            full_rows.append((synced, int(product.id), payload))

    full_rows.sort(key=lambda row: (row[0] is not None, row[0] or datetime.min, row[1]))
    lite_rows.sort(key=lambda row: (row[0] is not None, row[0] or datetime.min, row[1]))
    return (
        [row[2] for row in full_rows],
        [row[2] for row in lite_rows],
    )


# Резервирует товары с Redis dedup lock до batch_size.
def reserve_products_with_dedup(
    candidates: list[dict[str, Any]],
    env: Settings,
    batch_size: int,
    owner_token: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    reserved: list[dict[str, Any]] = []
    skipped_locked = 0
    for product in candidates:
        if len(reserved) >= batch_size:
            break
        if try_acquire_dom_enqueue_lock(
            product,
            resolved_dom_enqueue_lock_ttl_seconds(env),
            owner_token,
        ):
            reserved.append(product)
        else:
            skipped_locked += 1
    return reserved, skipped_locked


# Один cron-тик: recovery FULL, INCOMPLETE → FULL, COMPLETE stale → LITE.
async def enqueue_dom_scheduler(
    limit: int | None = None,
    env: Settings | None = None,
) -> dict[str, Any]:
    settings = env or load_settings()
    batch_size = max(1, limit or settings.dom_rolling_batch_size)
    fetch_limit = batch_size * max(3, settings.dom_rolling_fetch_multiplier)
    priority_cap = _priority_recovery_cap(batch_size, settings)

    stats = get_catalog_queue_stats()
    dom_pending = int(stats.get("dom_pending_jobs") or 0)
    dom_running = int(stats.get("dom_running_jobs") or 0)

    base_result: dict[str, Any] = {
        "batch_size": batch_size,
        "dom_pending_jobs": dom_pending,
        "dom_running_jobs": dom_running,
        "skipped_locked": 0,
        "skipped_not_claimed": 0,
        "selected_candidates": 0,
        "enqueued_jobs": 0,
        "enqueued_products": 0,
        "full_enqueued": 0,
        "lite_enqueued": 0,
        "priority_eligible": 0,
        "priority_enqueued": 0,
        "skipped": False,
        "reason": None,
    }

    if dom_queue_overloaded(settings):
        logger.info(
            "DOM scheduler: пропуск — очередь перегружена, pending=%s порог=%s",
            dom_pending,
            settings.dom_queue_max_pending,
        )
        return {**base_result, "skipped": True, "reason": "dom_queue_overloaded"}

    now = datetime.now(UTC).replace(tzinfo=None)
    priority = await _load_priority_recoverable_incomplete(settings, priority_cap)
    priority_ids = {row.get("id") for row in priority}
    base_result["priority_eligible"] = len(priority)

    loaded = await _load_scheduler_products(settings, fetch_limit)
    full_candidates, lite_candidates = _split_scheduler_candidates(
        loaded, settings, now
    )
    stock_zero = await _load_stock_zero_incomplete(settings, min(batch_size, 50))
    merged = _merge_dom_candidate_groups(
        priority, stock_zero, full_candidates, lite_candidates
    )
    base_result["selected_candidates"] = len(merged)

    # Rollout D2 owner token (SCRAPER_DOM_OWNER_TOKEN_ENQUEUE_ENABLED):
    # 1) migration  2) deploy workers, flag=false  3) drain catalog_dom queue
    # 4) flag=true  5) restart scheduler  6) verify RQ jobs carry owner_token
    owner_token: str | None = None
    if settings.dom_owner_token_enqueue_enabled:
        owner_token = uuid.uuid4().hex
    reserved, skipped_locked = reserve_products_with_dedup(
        merged, settings, batch_size, owner_token
    )
    base_result["skipped_locked"] = skipped_locked
    base_result["full_enqueued"] = sum(
        1 for row in reserved if row.get("dom_mode") == "FULL"
    )
    base_result["lite_enqueued"] = sum(
        1 for row in reserved if row.get("dom_mode") == "LITE"
    )
    base_result["priority_enqueued"] = sum(
        1 for row in reserved if row.get("id") in priority_ids
    )

    if not reserved:
        return {**base_result, "reason": "empty_selection"}

    claimed, skipped_not_claimed = await claim_dom_processing_products(
        reserved, settings, owner_token
    )
    base_result["skipped_not_claimed"] = skipped_not_claimed
    if skipped_not_claimed:
        claimed_ids = {p.get("id") for p in claimed}
        for product in reserved:
            if product.get("id") not in claimed_ids:
                release_dom_enqueue_lock(product, owner_token)

    if not claimed:
        return {**base_result, "reason": "empty_claim"}

    jobs = enqueue_dom_product_chunks(claimed, settings, owner_token)
    logger.info(
        "DOM scheduler: поставлено SKU=%s jobs=%s FULL=%s LITE=%s "
        "priority_eligible=%s priority_enqueued=%s",
        len(claimed),
        jobs,
        base_result["full_enqueued"],
        base_result["lite_enqueued"],
        base_result["priority_eligible"],
        base_result["priority_enqueued"],
    )
    return {
        **base_result,
        "enqueued_jobs": jobs,
        "enqueued_products": len(claimed),
    }


# CLI entry (замена rolling refresh).
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="DOM scheduler: один тик (INCOMPLETE→FULL, stale→LITE)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = asyncio.run(enqueue_dom_scheduler(limit=args.limit))
    save_admin_job_snapshot(ROLLING_REFRESH_SNAPSHOT, result)
    logger.info("DOM scheduler: итог %s", result)


if __name__ == "__main__":
    main()
