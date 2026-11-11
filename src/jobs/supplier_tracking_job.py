import asyncio
import logging

from src.jobs.dhl_browser_tracking_job import fetch_dhl_tracking_via_browser_queue
from src.services.orders.supplier_tracking import SupplierTrackingService

logger = logging.getLogger(__name__)


# Синхронизирует трекинг одного заказа в async-контексте job.
async def sync_supplier_tracking(order_id: int) -> dict:
    return await SupplierTrackingService(
        dhl_browser_fetch=fetch_dhl_tracking_via_browser_queue,
    ).sync_order(order_id)


# RQ entrypoint: sync трекинга заказа.
def run_supplier_tracking_job(order_id: int) -> dict:
    result = asyncio.run(sync_supplier_tracking(order_id))
    logger.info(
        "Очередь проверки трекинга поставщика: order=%s result=%s", order_id, result
    )
    return result
