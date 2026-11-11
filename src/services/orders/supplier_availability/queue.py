from rq import Queue

from src.core.config import settings
from src.core.redis import sync_redis


# Возвращает объект Queue для очереди supplier_availability.
def _supplier_availability_queue() -> Queue:
    return Queue(settings.SUPPLIER_AVAILABILITY_QUEUE, connection=sync_redis())


# Ставит задачу проверки наличия заказа в очередь.
def enqueue_supplier_availability(order_id: int):
    if not settings.SUPPLIER_AVAILABILITY_ENABLED:
        return None
    queue = _supplier_availability_queue()
    job_id = f"supplier-availability-{order_id}"
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
        "src.jobs.orders.supplier_availability_job.run_supplier_availability_job",
        order_id,
        job_id=job_id,
        job_timeout=180,
        result_ttl=86400,
        failure_ttl=604800,
    )
