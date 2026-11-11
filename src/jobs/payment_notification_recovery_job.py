import argparse
import asyncio
import logging
import sys

from src.jobs.admin_job_snapshots import save_admin_job_snapshot
from src.repositories.session import async_session_maker
from src.services.payment_service import PaymentService

logger = logging.getLogger(__name__)

SNAPSHOT_NAME = "payment_notification_recovery"
DEFAULT_LIMIT = 500


async def run_payment_notification_recovery(
    limit: int = DEFAULT_LIMIT,
) -> dict[str, int]:
    async with async_session_maker() as session:
        stats = await PaymentService(session).recover_missing_payment_notifications(
            limit=limit
        )
        logger.info(
            "Payment notification recovery: candidates=%s recovered=%s skipped=%s",
            stats.get("candidates"),
            stats.get("recovered"),
            stats.get("skipped"),
        )
        return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enqueue missing payment notifications from payment_accepted events"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    result = asyncio.run(run_payment_notification_recovery(limit=args.limit))
    save_admin_job_snapshot(SNAPSHOT_NAME, result)


if __name__ == "__main__":
    main()
