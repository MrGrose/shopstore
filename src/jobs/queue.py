import os
from datetime import UTC, datetime
from typing import Any

from rq import Queue, Worker
from rq.registry import (
    DeferredJobRegistry,
    FailedJobRegistry,
    ScheduledJobRegistry,
    StartedJobRegistry,
)

from src.core.config import settings
from src.core.redis import sync_redis

# Default chunk size для очереди catalog_import.
_DEFAULT_IMPORT_CHUNK_SIZE = 10


# Возвращает объект Queue для очереди по имени.
def _queue(name: str) -> Queue:
    return Queue(name, connection=sync_redis())


# Возвращает объект Queue для очереди catalog_import.
def get_catalog_import_queue() -> Queue:
    return _queue(settings.CATALOG_IMPORT_QUEUE)


# Возвращает объект Queue для очереди catalog_dom.
def get_catalog_dom_queue() -> Queue:
    return _queue(settings.CATALOG_DOM_QUEUE)


# Возвращает объект Queue для очереди catalog_finalize.
def get_catalog_finalize_queue() -> Queue:
    return _queue(settings.CATALOG_FINALIZE_QUEUE)


# Возвращает объект Queue для очереди notifications (stage 2, опционально).
def get_notification_queue() -> Queue:
    return _queue(settings.NOTIFICATION_QUEUE)


# Возвращает объект Queue для очереди supplier_tracking.
def get_supplier_tracking_queue() -> Queue:
    return _queue(settings.SUPPLIER_TRACKING_QUEUE)


# Возвращает объект Queue для Playwright fallback DHL tracking.
def get_dhl_browser_tracking_queue() -> Queue:
    return _queue(settings.DHL_BROWSER_TRACKING_QUEUE)


# Возвращает объект Queue для retry admin delivered alert (TG).
def get_delivered_alert_retry_queue() -> Queue:
    return _queue(settings.DELIVERED_ALERT_RETRY_QUEUE)


# Возвращает отдельную очередь batch-переоценки.
def get_pricing_queue() -> Queue:
    return _queue(settings.PRICING_QUEUE)


# Возвращает очередь translation (не catalog_dom).
def get_translation_queue() -> Queue:
    return _queue(settings.TRANSLATION_QUEUE)


_TRANSLATION_JOB = "src.jobs.translation_job.run_translate_product"
_TRANSLATION_JOB_TIMEOUT = 600


# Ставит перевод одного SKU; job_id дедупит одинаковый raw hash.
def enqueue_translation_product(product_id: int, raw_hash: str | None = None) -> object:
    queue = get_translation_queue()
    suffix = (raw_hash or "none")[:16]
    job_id = f"translate-{int(product_id)}-{suffix}"
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
        _TRANSLATION_JOB,
        int(product_id),
        job_id=job_id,
        job_timeout=_TRANSLATION_JOB_TIMEOUT,
        result_ttl=3600,
        failure_ttl=86400,
    )


# Алиас на catalog_import-очередь (обратная совместимость).
def get_catalog_queue() -> Queue:
    return get_catalog_import_queue()


# Удаляет failed jobs из одной RQ-очереди каталога.
def clear_failed_jobs(queue: Queue) -> int:
    registry = FailedJobRegistry(queue=queue)
    job_ids = registry.get_job_ids()
    for job_id in job_ids:
        registry.remove(job_id, delete_job=True)
    return len(job_ids)


# Очищает failed jobs во всех catalog-очередях (import, dom, finalize).
def clear_all_catalog_failed_jobs() -> dict[str, int]:
    counts = {
        "import": clear_failed_jobs(get_catalog_import_queue()),
        "dom": clear_failed_jobs(get_catalog_dom_queue()),
        "finalize": clear_failed_jobs(get_catalog_finalize_queue()),
        "translation": clear_failed_jobs(get_translation_queue()),
    }
    counts["total"] = (
        counts["import"] + counts["dom"] + counts["finalize"] + counts["translation"]
    )
    return counts


# Возвращает счётчики очередей RQ catalog (чанки, не отдельные SKU).
def get_catalog_queue_stats() -> dict[str, Any]:
    queue = get_catalog_import_queue()
    dom_queue = get_catalog_dom_queue()
    finalize_queue = get_catalog_finalize_queue()
    translation_queue = get_translation_queue()
    pending_jobs = queue.count
    running_jobs = StartedJobRegistry(queue=queue).count
    failed_jobs = FailedJobRegistry(queue=queue).count
    deferred_jobs = DeferredJobRegistry(queue=queue).count
    scheduled_jobs = ScheduledJobRegistry(queue=queue).count
    chunk_size = int(os.getenv("SCRAPER_IMPORT_CHUNK_SIZE", _DEFAULT_IMPORT_CHUNK_SIZE))
    chunk_size = max(1, chunk_size)
    return {
        "queue_name": settings.CATALOG_IMPORT_QUEUE,
        "pending_jobs": pending_jobs,
        "running_jobs": running_jobs,
        "failed_jobs": failed_jobs,
        "deferred_jobs": deferred_jobs,
        "scheduled_jobs": scheduled_jobs,
        "import_chunk_size": chunk_size,
        "estimated_products_pending": pending_jobs * chunk_size,
        "estimated_products_in_progress": running_jobs * chunk_size,
        "dom_queue_name": settings.CATALOG_DOM_QUEUE,
        "dom_pending_jobs": dom_queue.count,
        "dom_running_jobs": StartedJobRegistry(queue=dom_queue).count,
        "dom_failed_jobs": FailedJobRegistry(queue=dom_queue).count,
        "finalize_queue_name": settings.CATALOG_FINALIZE_QUEUE,
        "finalize_pending_jobs": finalize_queue.count,
        "finalize_running_jobs": StartedJobRegistry(queue=finalize_queue).count,
        "finalize_failed_jobs": FailedJobRegistry(queue=finalize_queue).count,
        "translation_queue_name": settings.TRANSLATION_QUEUE,
        "translation_pending_jobs": translation_queue.count,
        "translation_running_jobs": StartedJobRegistry(queue=translation_queue).count,
        "translation_failed_jobs": FailedJobRegistry(queue=translation_queue).count,
    }


# Возвращает alive-воркеры RQ по ролям import/dom/finalize (с алиасами имён очередей).
def get_rq_workers_by_queue(max_heartbeat_age_seconds: int = 120) -> dict[str, Any]:
    redis = sync_redis()
    role_aliases = {
        "import": {
            settings.CATALOG_IMPORT_QUEUE,
            "catalog_import",
            "catalog",
        },
        "dom": {settings.CATALOG_DOM_QUEUE, "catalog_dom"},
        "finalize": {settings.CATALOG_FINALIZE_QUEUE, "catalog_finalize"},
        "translation": {settings.TRANSLATION_QUEUE, "translation"},
    }
    rows: dict[str, dict[str, Any]] = {
        role: {"alive": False, "count": 0, "names": []} for role in role_aliases
    }
    now = datetime.now(UTC)
    for worker in Worker.all(connection=redis):
        heartbeat = worker.last_heartbeat
        if heartbeat is None:
            continue
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        if (now - heartbeat).total_seconds() > max_heartbeat_age_seconds:
            continue
        for queue_name in worker.queue_names() or []:
            for role, aliases in role_aliases.items():
                if queue_name not in aliases:
                    continue
                rows[role]["alive"] = True
                rows[role]["count"] += 1
                if worker.name not in rows[role]["names"]:
                    rows[role]["names"].append(worker.name)
    return rows


# True, если catalog_dom перегружена и rolling refresh не должен enqueue.
def dom_queue_overloaded(
    env: Any | None = None,
    max_pending: int | None = None,
) -> bool:
    from src.scraper.config.settings import Settings, load_settings

    settings: Settings
    if env is None:
        settings = load_settings()
    elif isinstance(env, Settings):
        settings = env
    else:
        settings = load_settings()

    if max_pending is not None:
        threshold = max_pending
    else:
        threshold = settings.dom_queue_max_pending
    threshold = max(1, threshold)
    stats = get_catalog_queue_stats()
    pending = int(stats.get("dom_pending_jobs") or 0)
    return pending > threshold


# Статус pipeline для admin API: фаза и счётчики очередей RQ.
def get_scraper_run_status() -> dict[str, Any]:
    from src.scraper.config.settings import load_settings

    stats = get_catalog_queue_stats()
    chunk_size = max(1, load_settings().import_chunk_size)
    import_pending = int(stats.get("pending_jobs") or 0)
    import_running = int(stats.get("running_jobs") or 0)
    import_failed = int(stats.get("failed_jobs") or 0)
    dom_pending = int(stats.get("dom_pending_jobs") or 0)
    dom_running = int(stats.get("dom_running_jobs") or 0)
    dom_failed = int(stats.get("dom_failed_jobs") or 0)
    finalize_pending = int(stats.get("finalize_pending_jobs") or 0)
    finalize_running = int(stats.get("finalize_running_jobs") or 0)
    finalize_failed = int(stats.get("finalize_failed_jobs") or 0)
    translation_pending = int(stats.get("translation_pending_jobs") or 0)
    translation_running = int(stats.get("translation_running_jobs") or 0)
    translation_failed = int(stats.get("translation_failed_jobs") or 0)

    if finalize_pending or finalize_running:
        phase = "finalize"
    elif translation_pending or translation_running:
        phase = "translation"
    elif import_pending or import_running:
        phase = "import"
    elif dom_pending or dom_running:
        phase = "dom"
    else:
        phase = "idle"

    dom_chunks_remaining = dom_pending + dom_running
    dom_max_pending = max(1, load_settings().dom_queue_max_pending)

    return {
        "phase": phase,
        "import_chunk_size": chunk_size,
        "dom_queue_max_pending": dom_max_pending,
        "dom_queue_overloaded": dom_pending > dom_max_pending,
        "import_queue_pending": import_pending,
        "import_queue_running": import_running,
        "import_queue_failed": import_failed,
        "finalize_queue_pending": finalize_pending,
        "finalize_queue_running": finalize_running,
        "finalize_queue_failed": finalize_failed,
        "translation_queue_pending": translation_pending,
        "translation_queue_running": translation_running,
        "translation_queue_failed": translation_failed,
        "dom_queue_pending": dom_pending,
        "dom_queue_running": dom_running,
        "dom_queue_failed": dom_failed,
        "dom_chunks_remaining": dom_chunks_remaining,
        "estimated_dom_products_remaining": dom_chunks_remaining * chunk_size,
    }
