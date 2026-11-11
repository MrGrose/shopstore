import argparse
import logging
from collections.abc import Sequence

from src.services.orders.supplier_availability.queue import (
    enqueue_supplier_availability,
)

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Поставить ручную проверку наличия заказа в RQ",
    )
    parser.add_argument("--order-id", type=int, required=True)
    args = parser.parse_args(argv)

    job = enqueue_supplier_availability(args.order_id)
    if job is None:
        parser.error("SUPPLIER_AVAILABILITY_ENABLED=false")
    print(f"Enqueued {job.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
