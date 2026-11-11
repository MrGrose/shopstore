import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from rq import Queue, Worker
from rq.job import Job
from rq.registry import FailedJobRegistry, StartedJobRegistry

from src.core.config import settings
from src.core.redis import sync_redis
from src.jobs.admin_job_snapshots import DOM_WATCHDOG_SNAPSHOT, save_admin_job_snapshot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WatchdogResult:
    checked: int = 0
    requeued: int = 0
    skipped_active: int = 0
    skipped_fresh: int = 0
    missing: int = 0


# Возвращает возраст job в секундах.
def _job_age_seconds(job: Job) -> float | None:
    if job.started_at is None:
        return None
    started_at = job.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - started_at).total_seconds()


# Переотправляет job в очередь failed.
def _requeue_job(
    queue: Queue,
    failed_registry: FailedJobRegistry,
    job: Job,
) -> Job:
    if job.id in failed_registry.get_job_ids():
        failed_registry.remove(job, delete_job=False)
    return queue.enqueue_call(
        func=job.func_name,
        args=job.args,
        kwargs=job.kwargs,
        timeout=job.timeout,
        result_ttl=job.result_ttl,
        failure_ttl=job.failure_ttl,
        at_front=True,
    )


# True если RQ worker мёртв или не указан — живой job не requeue по возрасту.
def job_needs_requeue(worker_name: str | None, active_workers: set[str]) -> bool:
    return not bool(worker_name and worker_name in active_workers)


# Переотправляет только jobs с мёртвым worker, не по возрасту живого job.
def run_dom_watchdog(
    stale_seconds: int | None = None,
    apply: bool = False,
) -> WatchdogResult:
    if stale_seconds is not None:
        logger.info(
            "DOM watchdog: --stale-seconds=%s игнорируется, "
            "requeue только при мёртвом worker",
            stale_seconds,
        )
    redis = sync_redis()
    queue = Queue(settings.CATALOG_DOM_QUEUE, connection=redis)
    started_registry = StartedJobRegistry(queue=queue)
    failed_registry = FailedJobRegistry(queue=queue)
    active_workers = {worker.name for worker in Worker.all(connection=redis)}
    result = WatchdogResult()

    for job_id in started_registry.get_job_ids():
        result.checked += 1
        job = queue.fetch_job(job_id)
        if job is None:
            result.missing += 1
            if apply:
                redis.zrem(started_registry.key, job_id)
            logger.warning("DOM watchdog: job %s не найден", job_id)
            continue

        age = _job_age_seconds(job)
        worker_alive = not job_needs_requeue(job.worker_name, active_workers)
        if worker_alive:
            result.skipped_active += 1
            logger.info(
                "DOM watchdog: job %s живой, worker=%s, age=%ss",
                job_id,
                job.worker_name,
                round(age or 0),
            )
            continue

        logger.warning(
            "DOM watchdog: мёртвый worker у job %s, worker=%s, возраст=%ss",
            job_id,
            job.worker_name,
            round(age or 0),
        )
        if apply:
            redis.zrem(started_registry.key, job_id)
            new_job = _requeue_job(queue, failed_registry, job)
            logger.warning("DOM watchdog: переотправлен %s -> %s", job_id, new_job.id)
        result.requeued += 1

    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DOM watchdog: переотправить зависшие catalog_dom jobs",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stale-seconds", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = _parse_args()
    result = run_dom_watchdog(
        stale_seconds=args.stale_seconds,
        apply=args.apply,
    )
    save_admin_job_snapshot(
        DOM_WATCHDOG_SNAPSHOT,
        {
            "ok": True,
            "apply": args.apply,
            "checked": result.checked,
            "requeued": result.requeued,
            "skipped_active": result.skipped_active,
            "skipped_fresh": result.skipped_fresh,
            "missing": result.missing,
        },
    )
    logger.info(
        "DOM watchdog итог: checked=%s requeued=%s skipped_active=%s "
        "skipped_fresh=%s missing=%s apply=%s",
        result.checked,
        result.requeued,
        result.skipped_active,
        result.skipped_fresh,
        result.missing,
        args.apply,
    )


if __name__ == "__main__":
    main()
