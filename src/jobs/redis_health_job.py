import argparse
import logging

from src.core.redis.health import evaluate_redis_health
from src.jobs.admin_job_snapshots import REDIS_HEALTH_SNAPSHOT, save_admin_job_snapshot

logger = logging.getLogger(__name__)


# Один cron-тик: ping Redis и alert при длительном outage.
def run_redis_health_check() -> dict:
    result = evaluate_redis_health()
    save_admin_job_snapshot(REDIS_HEALTH_SNAPSHOT, result)
    if not result["ok"]:
        logger.warning(
            "Redis health check failed sync_ok=%s async_ok=%s outage_seconds=%s",
            result["sync_ok"],
            result["async_ok"],
            result["outage_seconds"],
        )
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Redis health check")
    parser.parse_args()
    result = run_redis_health_check()
    logger.info("Redis health: %s", result)


if __name__ == "__main__":
    main()
