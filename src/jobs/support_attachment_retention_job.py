import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.jobs.admin_job_snapshots import save_admin_job_snapshot
from src.repositories.session import async_session_maker
from src.services.support import SupportService

logger = logging.getLogger(__name__)

SNAPSHOT_NAME = "support_attachment_retention"
DEFAULT_LIMIT = 100
LOG_PATH = Path("logs/support_attachment_retention.log")


# Удаляет фото закрытых тикетов старше retention и support/ orphans.
async def run_support_attachment_retention(
    limit: int = DEFAULT_LIMIT,
) -> dict[str, int]:
    async with async_session_maker() as session:
        result = await SupportService(session).purge_expired_attachments(limit=limit)
        logger.info(
            "Retention вложений поддержки: candidates=%s purged=%s orphans=%s",
            result.get("candidates"),
            result.get("purged"),
            result.get("orphans"),
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


# Точка входа CLI job retention вложений поддержки.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Удаление фото поддержки через 180 дней после закрытия тикета"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--log-file", type=Path, default=LOG_PATH)
    args = parser.parse_args()
    _configure_logging(args.log_file)
    result = asyncio.run(run_support_attachment_retention(limit=args.limit))
    save_admin_job_snapshot(SNAPSHOT_NAME, result)


if __name__ == "__main__":
    main()
