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


# SHA256 hex от bytes.
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# LocalStorage с root = родитель MEDIA_ROOT.
def build_local() -> LocalStorage:
    return LocalStorage(root=Path(settings.MEDIA_ROOT).parent)


# S3Storage из env (тот же factory, без get_storage).
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


# Сводка local vs S3 без удаления.
def compare_product_media(local: LocalStorage, s3: S3Storage) -> dict[str, object]:
    local_keys = set(local.iter_keys("products/"))
    s3_keys = set(s3.iter_keys("products/"))
    empty = {
        "local": 0,
        "s3": 0,
        "matched": 0,
        "missing_local": 0,
        "missing_s3": 0,
        "mismatch": 0,
        "corrupt_skipped": 0,
    }
    originals = dict(empty)
    variants = dict(empty)
    unexpected_s3: list[str] = []
    mismatch_keys: list[dict[str, str]] = []
    corrupt_local: list[str] = []

    # Счётчик originals или variants; other → None.
    def bucket_for(name: str) -> dict[str, int] | None:
        kind = media_kind(name)
        if kind == "original":
            return originals
        if kind == "variant":
            return variants
        return None

    for key in local_keys:
        name = Path(key).name
        bucket = bucket_for(name)
        if bucket is None:
            continue
        bucket["local"] += 1
        if name in KNOWN_CORRUPT_ORIGINAL_NAMES:
            bucket["corrupt_skipped"] += 1
            corrupt_local.append(key)
            continue
        if key not in s3_keys:
            bucket["missing_s3"] += 1
            continue
        local_data = local.read(key)
        s3_data = s3.read(key)
        if len(local_data) == len(s3_data) and sha256_bytes(local_data) == sha256_bytes(
            s3_data
        ):
            bucket["matched"] += 1
        else:
            bucket["mismatch"] += 1
            mismatch_keys.append({"key": key, "error": "size/hash mismatch"})

    for key in s3_keys:
        name = Path(key).name
        bucket = bucket_for(name)
        if bucket is None:
            unexpected_s3.append(key)
            continue
        bucket["s3"] += 1
        if key not in local_keys and name not in KNOWN_CORRUPT_ORIGINAL_NAMES:
            bucket["missing_local"] += 1

    return {
        "originals": originals,
        "variants": variants,
        "unexpected_s3": sorted(unexpected_s3),
        "unexpected_s3_count": len(unexpected_s3),
        "mismatch_keys": mismatch_keys,
        "known_corrupt": sorted(corrupt_local),
        "known_corrupt_names": sorted(KNOWN_CORRUPT_ORIGINAL_NAMES),
    }


# CLI: JSON inventory local vs S3. Ничего не удаляет.
def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Сравнить локальные медиа файлы с S3. Сухой инвентарь только. "
            "Локальный только — не запускать против production."
        )
    )
    parser.parse_args()
    report = compare_product_media(build_local(), build_s3())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    originals = report["originals"]
    assert isinstance(originals, dict)
    variants = report["variants"]
    assert isinstance(variants, dict)
    mismatch = int(originals["mismatch"]) + int(variants["mismatch"])
    return 1 if mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
