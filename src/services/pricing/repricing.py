import logging

from rq import Retry

from src.jobs.queue import get_pricing_queue
from src.models.pricing import PricingRecalculationJob
from src.repositories.pricing_repo import PricingRepository
from src.repositories.session import async_session_maker
from src.services.catalog.read.caches import invalidate_catalog_read_caches
from src.services.pricing.service import PricingService
from src.utils.datetime_fmt import utc_now_naive

logger = logging.getLogger(__name__)


# Ставит pricing job в отдельную RQ-очередь с безопасным retry.
def enqueue_repricing_job(job_id: int) -> str:
    rq_job = get_pricing_queue().enqueue(
        "src.jobs.pricing_recalculation_job.run_pricing_recalculation",
        job_id,
        retry=Retry(max=3, interval=[30, 120, 300]),
        job_timeout="4h",
    )
    return rq_job.id


# Проверяет, что job всё ещё соответствует правилу и settings.
def _job_versions_match(
    job: PricingRecalculationJob,
    rule,
    settings,
) -> bool:
    return (
        rule is not None
        and rule.updated_at == job.rule_version
        and settings.updated_at == job.settings_version
        and rule.margin_percent == job.margin_percent
    )


# Ставит финальный статус job и время завершения.
def _finish_job(job: PricingRecalculationJob, status: str) -> None:
    job.status = status
    job.finished_at = utc_now_naive()


# Обрабатывает товары через SAVEPOINT, не останавливая batch на одной ошибке.
async def _process_products(
    session,
    repo: PricingRepository,
    service: PricingService,
    job: PricingRecalculationJob,
    settings,
    rules,
    products,
) -> tuple[int, int]:
    batch_updated = 0
    batch_errors = 0
    for product in products:
        try:
            async with session.begin_nested():
                changed = service.verify_loaded_storefront_price(
                    product,
                    settings,
                    rules,
                    job.rule_version,
                )
                await session.flush()
            if changed:
                batch_updated += 1
        except Exception as exc:
            batch_errors += 1
            await repo.save_recalculation_error(
                job.id,
                product.id,
                str(exc),
            )
            logger.warning(
                "Ошибка pricing job %s для товара %s: %s",
                job.id,
                product.id,
                exc,
            )
    return batch_updated, batch_errors


# Выполняет идемпотентную batch-переоценку одного правила.
async def run_repricing_job(job_id: int, batch_size: int) -> str:
    async with async_session_maker() as session:
        repo = PricingRepository(session)
        job = await repo.get_recalculation_job(job_id, for_update=True)
        if job is None:
            raise ValueError(f"Pricing job {job_id} не найден")
        if job.status in ("succeeded", "superseded"):
            return job.status
        job.status = "running"
        job.started_at = job.started_at or utc_now_naive()
        await session.commit()

        try:
            while True:
                job = await repo.get_recalculation_job(job_id, for_update=True)
                if job is None:
                    raise ValueError(f"Pricing job {job_id} не найден")
                settings = await repo.get_settings_for_update()
                rules = await repo.get_margin_rules_for_update()
                rule = next(
                    (item for item in rules if item.id == job.margin_rule_id), None
                )
                if not _job_versions_match(job, rule, settings):
                    _finish_job(job, "superseded")
                    await session.commit()
                    return job.status

                if rule is None:
                    _finish_job(job, "superseded")
                    await session.commit()
                    return job.status
                products = await repo.load_repricing_batch(
                    rule,
                    rules,
                    job.cursor_product_id,
                    batch_size,
                )
                if not products:
                    _finish_job(job, "succeeded")
                    await session.commit()
                    if job.updated_count:
                        invalidate_catalog_read_caches(
                            reason="pricing_recalculation_job"
                        )
                    return job.status

                service = PricingService(session)
                batch_updated, batch_errors = await _process_products(
                    session,
                    repo,
                    service,
                    job,
                    settings,
                    rules,
                    products,
                )
                job.cursor_product_id = products[-1].id
                job.processed_count += len(products)
                job.updated_count += batch_updated
                job.error_count += batch_errors
                job.updated_at = utc_now_naive()
                await session.commit()
        except Exception:
            await session.rollback()
            failed_job = await repo.get_recalculation_job(job_id, for_update=True)
            if failed_job is not None:
                _finish_job(failed_job, "failed")
                await session.commit()
            logger.exception("Pricing job %s завершился с ошибкой", job_id)
            raise
