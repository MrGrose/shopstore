import asyncio
import logging

from src.core.config import settings
from src.jobs.queue import get_dhl_browser_tracking_queue
from src.services.orders.dhl_browser_tracking import (
    fetch_dhl_tracking_payload_via_browser,
)
from src.services.orders.dhl_tracking import (
    DhlTrackingFetchError,
    normalize_fetched_dhl_payload,
)

logger = logging.getLogger(__name__)


# Ставит browser-fetch DHL в очередь worker-dhl.
def enqueue_dhl_browser_fetch(piececode: str, language: str = "ru"):
    queue = get_dhl_browser_tracking_queue()
    normalized = piececode.strip().upper()
    job_id = f"dhl-browser-{normalized}"
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
        "src.jobs.dhl_browser_tracking_job.run_dhl_browser_fetch_job",
        piececode,
        language,
        job_id=job_id,
        job_timeout=90,
        result_ttl=300,
        failure_ttl=3600,
    )


# RQ entrypoint: Playwright fetch JSON DHL на worker-dhl.
def run_dhl_browser_fetch_job(piececode: str, language: str = "ru") -> dict:
    payload = asyncio.run(
        fetch_dhl_tracking_payload_via_browser(
            piececode,
            language=language,
            proxy_url=settings.DHL_TRACKING_PROXY_URL or None,
        )
    )
    logger.info("DHL browser fetch: piececode=%s ok", piececode.strip())
    return payload


# Ждёт RQ browser job и возвращает нормализованный carrier payload.
async def fetch_dhl_tracking_via_browser_queue(
    piececode: str,
    language: str = "ru",
) -> dict:
    timeout = settings.DHL_BROWSER_FETCH_TIMEOUT_SECONDS

    def _wait_for_payload() -> dict:
        job = enqueue_dhl_browser_fetch(piececode, language)
        return job.result(timeout=timeout)

    try:
        payload = await asyncio.to_thread(_wait_for_payload)
    except Exception as exc:
        raise DhlTrackingFetchError(
            "blocked",
            "DHL заблокировал проверку (browser fallback не удался)",
            True,
        ) from exc
    if not isinstance(payload, dict):
        raise DhlTrackingFetchError(
            "invalid_json", "DHL вернул ответ неизвестного формата"
        )
    return normalize_fetched_dhl_payload(payload, piececode)
