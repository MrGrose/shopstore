import asyncio
import logging

from src.repositories.session import async_session_maker
from src.services.orders.supplier_availability.service import (
    SupplierAvailabilityService,
)

logger = logging.getLogger(__name__)


# Проверка наличия поставщика.
async def run_supplier_availability_check(order_id: int) -> dict:
    async with async_session_maker() as session:
        return await SupplierAvailabilityService(session).check_order(order_id)


# Основная функция для запуска job.
def run_supplier_availability_job(order_id: int) -> dict:
    result = asyncio.run(run_supplier_availability_check(order_id))
    logger.info(
        "Очередь проверки наличия поставщика: order=%s result=%s",
        order_id,
        result,
    )
    return result
