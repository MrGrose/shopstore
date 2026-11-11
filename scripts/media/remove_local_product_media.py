import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import settings  # noqa: E402
from src.storage.local import LocalStorage  # noqa: E402
from src.storage.s3 import S3Storage  # noqa: E402
from src.utils.images import (  # noqa: E402
    KNOWN_CORRUPT_ORIGINAL_NAMES,
    is_product_original_filename,
    is_product_variant_filename,
)

_SKIP_REASONS = {
    "not_product_media": "not product original/variant",
    "corrupt": "известный битый original",
    "missing_s3": "S3 object missing",
    "mismatch": "size/hash mismatch",
}


# SHA256 hex от bytes.
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# LocalStorage с root = родитель MEDIA_ROOT.
def build_local() -> LocalStorage:
    return LocalStorage(root=Path(settings.MEDIA_ROOT).parent)


# S3Storage из env.
def build_s3() -> S3Storage:
    endpoint = settings.S3_ENDPOINT.strip()
    if not endpoint:
        raise RuntimeError("S3_ENDPOINT обязателен")
    return S3Storage(
        endpoint,
        settings.S3_ACCESS_KEY,
        settings.S3_SECRET_KEY,
        settings.S3_BUCKET,
        settings.S3_REGION,
    )


# original / variant / other по имени файла.
def media_kind(name: str) -> str:
    if is_product_original_filename(name):
        return "original"
    if is_product_variant_filename(name):
        return "variant"
    return "other"


# Почему local файл нельзя удалять; None = verified match.
def skip_reason(local: LocalStorage, s3: S3Storage, key: str) -> str | None:
    name = Path(key).name
    if media_kind(name) == "other":
        return "not_product_media"
    if name in KNOWN_CORRUPT_ORIGINAL_NAMES:
        return "corrupt"
    if not s3.exists(key):
        return "missing_s3"
    local_data = local.read(key)
    s3_data = s3.read(key)
    if len(local_data) != len(s3_data) or sha256_bytes(local_data) != sha256_bytes(
        s3_data
    ):
        return "mismatch"
    return None


# Считает eligible/skipped; при apply удаляет только verified local files.
def plan_removal(local: LocalStorage, s3: S3Storage, apply: bool) -> dict[str, object]:
    report: dict[str, object] = {
        "dry_run": not apply,
        "eligible": 0,
        "deleted": 0,
        "skipped": 0,
        "bytes_eligible": 0,
        "errors": 0,
        "skipped_by_reason": {key: 0 for key in _SKIP_REASONS},
        "error_keys": [],
        "skipped_samples": [],
    }
    skipped_by_reason = report["skipped_by_reason"]
    assert isinstance(skipped_by_reason, dict)
    skipped_samples = report["skipped_samples"]
    assert isinstance(skipped_samples, list)
    error_keys = report["error_keys"]
    assert isinstance(error_keys, list)
    for key in sorted(local.iter_keys("products/")):
        try:
            reason = skip_reason(local, s3, key)
            if reason is not None:
                report["skipped"] = int(report["skipped"]) + 1
                skipped_by_reason[reason] = int(skipped_by_reason[reason]) + 1
                if len(skipped_samples) < 20:
                    skipped_samples.append(
                        {"key": key, "reason": _SKIP_REASONS[reason]}
                    )
                continue
            size = len(local.read(key))
            report["eligible"] = int(report["eligible"]) + 1
            report["bytes_eligible"] = int(report["bytes_eligible"]) + size
            if apply:
                local.delete(key)
                report["deleted"] = int(report["deleted"]) + 1
        except Exception as exc:
            report["errors"] = int(report["errors"]) + 1
            error_keys.append({"key": key, "error": str(exc)})
    return report


# CLI: dry-run по умолчанию, --apply удаляет verified local product media.
def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Удалить локальные медиа файлы только когда S3 size+SHA256 совпадают. "
            "Сухой запуск по умолчанию. Пропускает известные повреждённые оригиналы. "
            "Локальный только — не запускать против production."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Удалить verified локальные файлы. Без этого флага только отчёт.",
    )
    args = parser.parse_args()
    report = plan_removal(build_local(), build_s3(), args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if int(report["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
