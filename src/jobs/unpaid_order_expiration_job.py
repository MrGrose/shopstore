import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.jobs.admin_job_snapshots import save_admin_job_snapshot
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService

logger = logging.getLogger(__name__)

SNAPSHOT_NAME = "unpaid_order_expiration"
DEFAULT_LIMIT = 50
LOG_PATH = Path("logs/unpaid_order_expiration.log")


# Запускает автоотмену просроченных неоплаченных заказов.
async def run_unpaid_order_expiration(limit: int = DEFAULT_LIMIT) -> dict[str, int]:
    async with async_session_maker() as session:
        service = OrderService(session)
        result = await service.expire_unpaid_orders(limit=limit)
        logger.info(
            "Автоотмена неоплаченных: candidates=%s cancelled=%s skipped=%s",
            result.get("candidates"),
            result.get("cancelled"),
            result.get("skipped"),
        )
        return result


# Настраивает логирование job.
def _configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


# Точка входа CLI job автоотмены неоплаченных заказов.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Автоотмена неоплаченных заказов по истечению срока оплаты"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--log-file", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    _configure_logging(args.log_file)
    result = asyncio.run(run_unpaid_order_expiration(limit=args.limit))
    save_admin_job_snapshot(SNAPSHOT_NAME, result)


if __name__ == "__main__":
    main()
