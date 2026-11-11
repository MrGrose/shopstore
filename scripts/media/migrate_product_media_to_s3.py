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
    is_product_variant_filename,
)

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_SKIP_STEM_SUFFIXES = ("_300", "_600", "_900", "_w160", "_w560", "_w1400")
_LEGACY_VARIANT_SUFFIXES = ("_w160", "_w560", "_w1400")
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


# True если имя — original, не legacy preview и не I7 variant.
def _is_original_name(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return False
    return not any(path.stem.endswith(tag) for tag in _SKIP_STEM_SUFFIXES)


# True если имя — legacy variant _w160/_w560/_w1400.
def _is_legacy_variant_name(name: str) -> bool:
    path = Path(name)
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return False
    return any(path.stem.endswith(tag) for tag in _LEGACY_VARIANT_SUFFIXES)


# True если имя — current или legacy variant.
def _is_variant_name(name: str) -> bool:
    return is_product_variant_filename(name) or _is_legacy_variant_name(name)


# True если local path — original image.
def _is_original(path: Path) -> bool:
    return path.is_file() and _is_original_name(path.name)


# True если local path — variant image.
def _is_variant(path: Path) -> bool:
    return path.is_file() and _is_variant_name(path.name)


# SHA256 hex от bytes.
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Content-Type по расширению; иначе jpeg.
def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "image/jpeg")


# Ожидаемые missing variants у documented corrupt originals.
def _documented_missing_variant_keys() -> list[str]:
    keys: list[str] = []
    for name in sorted(KNOWN_CORRUPT_ORIGINAL_NAMES):
        stem = Path(name).stem
        suffix = Path(name).suffix
        for size in settings.PREVIEW_SIZES:
            keys.append(f"products/{stem}_{size}{suffix}")
    return keys


# Копирует originals или variants local ↔ S3. Dry-run по умолчанию.
def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy product originals or variants between LocalStorage and S3. "
            "Dry-run default. Does not delete local files or change DB URLs."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Upload (or reverse-download). Without this flag only report.",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="S3 → local rollback copy. Still dry-run unless --apply.",
    )
    parser.add_argument(
        "--variants-only",
        action="store_true",
        help="Process only local variants (_300/_600/_900 and legacy w*).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max files to process (0 = all). Useful for POC.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace destination when size/hash differs. Default: report as failed.",
    )
    args = parser.parse_args()

    media_root = Path(settings.MEDIA_ROOT)
    if args.reverse:
        media_root.mkdir(parents=True, exist_ok=True)
    elif not media_root.is_dir():
        print(f"MEDIA_ROOT отсутствует: {media_root}", file=sys.stderr)
        return 1

    local = LocalStorage(root=media_root.parent)
    s3 = S3Storage(
        settings.S3_ENDPOINT,
        settings.S3_ACCESS_KEY,
        settings.S3_SECRET_KEY,
        settings.S3_BUCKET,
        settings.S3_REGION,
    )

    report: dict[str, object] = {
        "mode": "variants-only" if args.variants_only else "originals",
        "total": 0,
        "uploaded": 0,
        "already_exists": 0,
        "verified": 0,
        "failed": 0,
        "skipped": 0,
        "failed_keys": [],
        "total_source_bytes": 0,
        "dry_run": not args.apply,
        "reverse": args.reverse,
    }
    if args.variants_only:
        report["documented_missing_variant_keys"] = _documented_missing_variant_keys()
        report["documented_missing_variant_count"] = len(
            report["documented_missing_variant_keys"]
        )
        report["originals_excluded"] = sum(
            1 for path in media_root.iterdir() if _is_original(path)
        )

    items = _iter_items(media_root, s3, args.reverse, args.variants_only)
    if args.limit:
        items = items[: args.limit]
    report["total"] = len(items)

    total = len(items)
    for i, (path, key) in enumerate(items, 1):
        try:
            _process_one(
                path, key, local, s3, args.apply, args.reverse, args.overwrite, report
            )
        except Exception as exc:
            report["failed"] = int(report["failed"]) + 1
            failed_keys = report["failed_keys"]
            assert isinstance(failed_keys, list)
            failed_keys.append({"key": key, "error": str(exc)})
        if total and (i % 200 == 0 or i == total):
            print(
                f"progress {i}/{total} failed={report['failed']}",
                file=sys.stderr,
            )

    report["upload_candidates"] = (
        int(report["skipped"]) if not args.apply else int(report["uploaded"])
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if int(report["failed"]) else 0


# Список (local path, storage key) для forward или reverse.
def _iter_items(
    media_root: Path,
    s3: S3Storage,
    reverse: bool,
    variants_only: bool = False,
) -> list[tuple[Path, str]]:
    if not reverse:
        pick = _is_variant if variants_only else _is_original
        return [
            (path, f"products/{path.name}")
            for path in sorted(media_root.iterdir())
            if pick(path)
        ]
    name_filter = _is_variant_name if variants_only else _is_original_name
    items: list[tuple[Path, str]] = []
    paginator = s3._client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3._bucket, Prefix="products/"):
        for obj in page.get("Contents") or []:
            key = str(obj["Key"])
            name = Path(key).name
            if name_filter(name):
                items.append((media_root / name, key))
    return items


# Один файл: skip / upload / verify size+sha256.
def _process_one(
    path: Path,
    key: str,
    local: LocalStorage,
    s3: S3Storage,
    apply: bool,
    reverse: bool,
    overwrite: bool,
    report: dict[str, object],
) -> None:
    dst = local if reverse else s3
    if reverse:
        if not s3.exists(key):
            report["skipped"] = int(report["skipped"]) + 1
            return
        src_bytes = s3.read(key)
    else:
        src_bytes = path.read_bytes()
    report["total_source_bytes"] = int(report["total_source_bytes"]) + len(src_bytes)
    src_hash = _sha256_bytes(src_bytes)
    src_size = len(src_bytes)
    ctype = _content_type(path)

    if dst.exists(key):
        dest = dst.read(key)
        if len(dest) == src_size and _sha256_bytes(dest) == src_hash:
            report["already_exists"] = int(report["already_exists"]) + 1
            report["verified"] = int(report["verified"]) + 1
            return
        if not apply or not overwrite:
            report["failed"] = int(report["failed"]) + 1
            failed_keys = report["failed_keys"]
            assert isinstance(failed_keys, list)
            failed_keys.append({"key": key, "error": "exists but size/hash mismatch"})
            return
        dst.put(key, src_bytes, ctype)
        _verify(dst, key, src_size, src_hash)
        report["uploaded"] = int(report["uploaded"]) + 1
        report["verified"] = int(report["verified"]) + 1
        return

    if not apply:
        report["skipped"] = int(report["skipped"]) + 1
        return

    dst.put(key, src_bytes, ctype)
    _verify(dst, key, src_size, src_hash)
    report["uploaded"] = int(report["uploaded"]) + 1
    report["verified"] = int(report["verified"]) + 1


# Проверяет size и sha256 после put.
def _verify(
    storage: LocalStorage | S3Storage, key: str, size: int, digest: str
) -> None:
    dest = storage.read(key)
    if len(dest) != size or _sha256_bytes(dest) != digest:
        raise RuntimeError(f"verify failed for {key}")


if __name__ == "__main__":
    raise SystemExit(main())
