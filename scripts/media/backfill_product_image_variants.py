import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage import get_storage  # noqa: E402
from src.storage.base import Storage  # noqa: E402
from src.utils.images import (  # noqa: E402
    ensure_product_preview_variants,
    is_product_original_filename,
)

logger = logging.getLogger(__name__)


# Собирает ключи originals в Storage (не variant, не legacy w*).
def _original_keys(storage: Storage, limit: int) -> list[str]:
    keys = [
        key
        for key in storage.iter_keys("products/")
        if is_product_original_filename(Path(key).name)
    ]
    keys.sort()
    if limit:
        return keys[:limit]
    return keys


# Dry-run или apply missing _300/_600/_900 через Storage.
def run_backfill(storage: Storage, apply: bool, limit: int = 0) -> dict[str, object]:
    report: dict[str, object] = {
        "dry_run": not apply,
        "originals": 0,
        "created": 0,
        "already_exists": 0,
        "missing": 0,
        "failed": 0,
        "failed_keys": [],
        "stopped_early": False,
    }
    keys = _original_keys(storage, limit)
    report["originals"] = len(keys)
    total = len(keys)
    failed_keys: list[dict[str, str]] = []
    consecutive_fail = 0
    for i, key in enumerate(keys, 1):
        try:
            result = ensure_product_preview_variants(storage, key, apply)
            report["already_exists"] = int(report["already_exists"]) + int(
                result["already_exists"]
            )
            report["missing"] = int(report["missing"]) + int(result["missing"])
            report["created"] = int(report["created"]) + int(result["created"])
            consecutive_fail = 0
        except Exception as exc:
            report["failed"] = int(report["failed"]) + 1
            failed_keys.append({"key": key, "error": str(exc)})
            consecutive_fail += 1
            logger.exception("Backfill variant не удался: %s", key)
            if consecutive_fail >= 25:
                logger.error("Backfill остановлен: 25 ошибок подряд, ключ %s", key)
                report["stopped_early"] = True
                break
        if total and (i % 200 == 0 or i == total):
            print(
                f"progress {i}/{total} failed={report['failed']}",
                file=sys.stderr,
            )
    report["failed_keys"] = failed_keys
    return report


# CLI: dry-run по умолчанию, --apply пишет missing variants.
def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Создаёт недостающие превью _300/_600/_900 через Storage. "
            "По умолчанию dry-run. Originals не удаляет, существующие variants "
            "не перезаписывает. Только локально — не для production."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Записать missing variants. Без флага только отчёт.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Максимум originals (0 = все).",
    )
    args = parser.parse_args()
    report = run_backfill(get_storage(), args.apply, args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if int(report["failed"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
