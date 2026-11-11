import argparse
import asyncio
import logging

from src.repositories.session import async_session_maker
from src.services.pricing_service import PricingService

logger = logging.getLogger(__name__)


async def run_refresh_eur_rate() -> None:
    async with async_session_maker() as session:
        service = PricingService(session)
        await service.refresh_eur_rate()
    logger.info("Курс EUR обновлён")


async def run_recalculate_prices() -> int:
    async with async_session_maker() as session:
        service = PricingService(session)
        updated = await service.recalculate_all_products()
    logger.info("Цены пересчитаны, товаров: %s", updated)
    return updated


async def _run(task: str) -> None:
    if task == "rate":
        await run_refresh_eur_rate()
        return
    if task == "prices":
        await run_recalculate_prices()
        return
    raise ValueError(f"Неизвестная задача: {task}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Обновление курса EUR и пересчёт цен (cron/job)",
    )
    parser.add_argument(
        "--task",
        choices=("rate", "prices"),
        required=True,
        help="rate — курс EUR; prices — пересчёт цен всех товаров",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = _parse_args()
    try:
        asyncio.run(_run(args.task))
    except Exception:
        logger.exception("Задача eur_pricing (%s) завершилась с ошибкой", args.task)
        raise


if __name__ == "__main__":
    main()
