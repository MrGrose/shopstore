import json
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.redis import sync_redis
from src.jobs.dom_telemetry_store import (
    empty_telemetry_dashboard,
    load_dom_telemetry_dashboard,
)
from src.jobs.queue import get_catalog_queue_stats, get_rq_workers_by_queue
from src.models.product import Product
from src.scraper.config.settings import Settings

_CHALLENGE_ERROR_FILTER = or_(
    Product.dom_last_error.ilike("%captcha%"),
    Product.dom_last_error.ilike("%turnstile%"),
    Product.dom_last_error.ilike("%challenge%"),
    Product.dom_last_error.ilike("%cloudflare%"),
    Product.dom_last_error.ilike("%blocked%"),
    Product.dom_last_error.ilike("%429%"),
    Product.dom_last_error.ilike("%rate_limit%"),
)


# Считает товары, исчерпавшие лимит DOM-попыток.
async def count_dom_exhausted(db: AsyncSession, max_attempts: int) -> int:
    return int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.product_url.is_not(None),
                Product.dom_last_error.isnot(None),
                Product.dom_attempts >= max(1, max_attempts),
            )
        )
        or 0
    )


# Считает товары в cooldown между DOM-попытками.
async def count_dom_cooldown(
    db: AsyncSession,
    env: Settings,
    now: datetime,
) -> int:
    retry_before = now - timedelta(seconds=max(0, env.dom_retry_cooldown_seconds))
    max_attempts = max(1, env.dom_max_attempts)
    return int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.product_url.is_not(None),
                Product.dom_attempts < max_attempts,
                Product.dom_last_attempt_at.isnot(None),
                Product.dom_last_attempt_at > retry_before,
            )
        )
        or 0
    )


# Считает SKU, подходящие под ручной тик DOM scheduler.
async def count_backfill_eligible(
    db: AsyncSession,
    env: Settings,
    now: datetime,
) -> int:
    retry_before = now - timedelta(seconds=max(0, env.dom_retry_cooldown_seconds))
    max_attempts = max(1, env.dom_max_attempts)
    return int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.is_active.is_(True),
                Product.stock == 0,
                Product.product_url.isnot(None),
                Product.dom_attempts < max_attempts,
                or_(
                    Product.dom_last_attempt_at.is_(None),
                    Product.dom_last_attempt_at <= retry_before,
                ),
            )
        )
        or 0
    )


# Считает challenge-rate по dom_last_error за 1ч и 24ч.
async def build_challenge_stats(db: AsyncSession, now: datetime) -> dict[str, Any]:
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)
    base = Product.dom_last_error.isnot(None)

    async def _window(since: datetime) -> tuple[int, int]:
        failures = int(
            await db.scalar(
                select(func.count(Product.id)).where(
                    base,
                    Product.dom_last_attempt_at.isnot(None),
                    Product.dom_last_attempt_at >= since,
                )
            )
            or 0
        )
        challenges = int(
            await db.scalar(
                select(func.count(Product.id)).where(
                    base,
                    Product.dom_last_attempt_at.isnot(None),
                    Product.dom_last_attempt_at >= since,
                    _CHALLENGE_ERROR_FILTER,
                )
            )
            or 0
        )
        return failures, challenges

    failures_1h, challenges_1h = await _window(since_1h)
    failures_24h, challenges_24h = await _window(since_24h)

    # Доля challenge среди DOM-ошибок за окно, в процентах.
    def _rate(challenges: int, failures: int) -> int:
        if failures <= 0:
            return 0
        return round(challenges * 100 / failures)

    return {
        "failures_1h": failures_1h,
        "challenges_1h": challenges_1h,
        "rate_1h": _rate(challenges_1h, failures_1h),
        "failures_24h": failures_24h,
        "challenges_24h": challenges_24h,
        "rate_24h": _rate(challenges_24h, failures_24h),
    }


# Считает active SKU и derived COMPLETE/INCOMPLETE (зеркало is_product_complete).
async def count_catalog_enrichment_state(db: AsyncSession) -> dict[str, int]:
    from src.models.product import ProductFeature, ProductImage

    base = Product.is_active.is_(True)
    has_image = (
        select(ProductImage.id)
        .where(ProductImage.product_id == Product.id)
        .correlate(Product)
        .exists()
    )
    has_feature = (
        select(ProductFeature.id)
        .where(ProductFeature.product_id == Product.id)
        .correlate(Product)
        .exists()
    )
    complete_filter = (
        base,
        Product.external_id.isnot(None),
        Product.product_url.isnot(None),
        Product.description_raw.isnot(None),
        has_image,
        or_(has_feature, Product.dom_full_at.isnot(None)),
    )
    active = int(await db.scalar(select(func.count(Product.id)).where(base)) or 0)
    complete = int(
        await db.scalar(select(func.count(Product.id)).where(*complete_filter)) or 0
    )
    with_snapshot = int(
        await db.scalar(
            select(func.count(Product.id)).where(
                base, Product.supplier_snapshot_json.isnot(None)
            )
        )
        or 0
    )
    return {
        "active": active,
        "complete": complete,
        "incomplete": max(0, active - complete),
        "with_snapshot": with_snapshot,
    }


_QUEUE_SNAPSHOT_KEY = "shopstore:admin:queue_snapshot"
_QUEUE_STALL_MINUTES = 15


# Детектирует застой очереди: pending+running не меняется N минут
# при ненулевой нагрузке.
def detect_queue_stall(stats: dict[str, Any]) -> dict[str, Any]:
    redis = sync_redis()
    now = time.time()
    stages = ("import", "dom", "finalize")
    values = {
        "import": int(stats.get("pending_jobs") or 0)
        + int(stats.get("running_jobs") or 0),
        "dom": int(stats.get("dom_pending_jobs") or 0)
        + int(stats.get("dom_running_jobs") or 0),
        "finalize": int(stats.get("finalize_pending_jobs") or 0)
        + int(stats.get("finalize_running_jobs") or 0),
    }
    raw = redis.get(_QUEUE_SNAPSHOT_KEY)
    unchanged_since: dict[str, float] = {stage: now for stage in stages}
    stall: dict[str, Any] = {"is_stalled": False, "stage": None, "idle_minutes": 0}

    if raw:
        try:
            prev = json.loads(raw)
        except json.JSONDecodeError:
            prev = {}
        prev_values = prev.get("values") or {}
        prev_unchanged = prev.get("unchanged_since") or {}
        for stage in stages:
            if values[stage] == int(prev_values.get(stage) or -1):
                unchanged_since[stage] = float(prev_unchanged.get(stage) or now)
            else:
                unchanged_since[stage] = now
        for stage in stages:
            if values[stage] <= 0:
                continue
            idle_min = int((now - unchanged_since[stage]) / 60)
            if idle_min >= _QUEUE_STALL_MINUTES:
                stall = {
                    "is_stalled": True,
                    "stage": stage,
                    "idle_minutes": idle_min,
                    "queue_depth": values[stage],
                }
                break

    redis.set(
        _QUEUE_SNAPSHOT_KEY,
        json.dumps({"values": values, "unchanged_since": unchanged_since, "ts": now}),
        ex=86400,
    )
    return stall


# Дефолтный ops-контекст, если метрики недоступны.
def default_parsing_ops() -> dict[str, Any]:
    dead_worker = {"alive": False, "count": 0, "names": []}
    return {
        "workers": {
            "import": dict(dead_worker),
            "dom": dict(dead_worker),
            "finalize": dict(dead_worker),
            "translation": dict(dead_worker),
        },
        "exhausted": 0,
        "cooldown": 0,
        "backfill_eligible": 0,
        "catalog_active": 0,
        "catalog_complete": 0,
        "catalog_incomplete": 0,
        "catalog_with_snapshot": 0,
        "max_attempts": 1,
        "challenge": {
            "failures_1h": 0,
            "challenges_1h": 0,
            "rate_1h": 0,
            "failures_24h": 0,
            "challenges_24h": 0,
            "rate_24h": 0,
        },
        "dom_telemetry": empty_telemetry_dashboard(),
        "queue_stall": {"is_stalled": False, "stage": None, "idle_minutes": 0},
    }


# Собирает ops-метрики парсинга: воркеры, backfill, challenge.
async def build_parsing_ops_metrics(
    db: AsyncSession,
    env: Settings,
    now: datetime,
) -> dict[str, Any]:
    try:
        dom_telemetry = load_dom_telemetry_dashboard()
    except Exception:
        dom_telemetry = empty_telemetry_dashboard()
    catalog_state = await count_catalog_enrichment_state(db)
    stats = get_catalog_queue_stats()
    return {
        **default_parsing_ops(),
        "workers": get_rq_workers_by_queue(),
        "exhausted": await count_dom_exhausted(db, env.dom_max_attempts),
        "cooldown": await count_dom_cooldown(db, env, now),
        "backfill_eligible": await count_backfill_eligible(db, env, now),
        "catalog_active": catalog_state["active"],
        "catalog_complete": catalog_state["complete"],
        "catalog_incomplete": catalog_state["incomplete"],
        "catalog_with_snapshot": catalog_state["with_snapshot"],
        "challenge": await build_challenge_stats(db, now),
        "dom_telemetry": dom_telemetry,
        "max_attempts": max(1, env.dom_max_attempts),
        "queue_stall": detect_queue_stall(stats),
    }
