import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.jobs.admin_job_snapshots import save_admin_job_snapshot
from src.repositories.session import async_session_maker
from src.services.notifications.outbox_service import process_outbox_batch

logger = logging.getLogger(__name__)

SNAPSHOT_NAME = "notification_outbox"
DEFAULT_LIMIT = 50
LOG_PATH = Path("logs/notification_outbox.log")


# Обрабатывает пачку notification_outbox (claim → deliver → mark).
async def run_notification_outbox(limit: int = DEFAULT_LIMIT) -> dict[str, int]:
    async with async_session_maker() as session:
        stats = await process_outbox_batch(session, limit=limit)
        logger.info(
            "Outbox уведомлений: stuck_reset=%s claimed=%s sent=%s "
            "requeued=%s failed=%s",
            stats.get("stuck_reset"),
            stats.get("claimed"),
            stats.get("sent"),
            stats.get("requeued"),
            stats.get("failed"),
        )
        return stats


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


# Точка входа CLI job outbox-уведомлений.
def main() -> None:
    parser = argparse.ArgumentParser(description="Доставка TG-уведомлений из outbox")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--log-file", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    _configure_logging(args.log_file)
    result = asyncio.run(run_notification_outbox(limit=args.limit))
    save_admin_job_snapshot(SNAPSHOT_NAME, result)


if __name__ == "__main__":
    main()
