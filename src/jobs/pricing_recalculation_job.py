import asyncio

from src.core.config import settings
from src.services.pricing.repricing import run_repricing_job


# Запускает async batch-переоценку из синхронного RQ worker.
def run_pricing_recalculation(job_id: int) -> str:
    return asyncio.run(
        run_repricing_job(job_id, batch_size=settings.PRICING_BATCH_SIZE)
    )
