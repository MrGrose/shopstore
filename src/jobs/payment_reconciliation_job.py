import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.jobs.admin_job_snapshots import save_admin_job_snapshot
from src.repositories.session import async_session_maker
from src.services.payment_service import PaymentService

logger = logging.getLogger(__name__)

# Имя снимка для админки.
SNAPSHOT_NAME = "payment_reconciliation"
# Максимальное количество попыток для сверки.
DEFAULT_LIMIT = 50
# Путь к файлу логов.
LOG_PATH = Path("logs/payment_reconciliation.log")


# Запускает reconciliation истёкших QR-попыток.
async def run_payment_reconciliation(limit: int = DEFAULT_LIMIT) -> dict[str, int]:
    async with async_session_maker() as session:
        service = PaymentService(session)
        result = await service.reconcile_expired_attempts(limit=limit)
        logger.info(
            "Сверка оплат: candidates=%s processed=%s errors=%s",
            result.get("candidates"),
            result.get("processed"),
            result.get("errors"),
        )
        return result


# Настраивает логирование.
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Сверка просроченных попыток оплаты")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--log-file", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    _configure_logging(args.log_file)
    result = asyncio.run(run_payment_reconciliation(limit=args.limit))
    save_admin_job_snapshot(SNAPSHOT_NAME, result)


if __name__ == "__main__":
    main()
