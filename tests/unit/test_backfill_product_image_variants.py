import importlib.util
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.storage.dual import DualStorage
from src.storage.local import LocalStorage
from src.storage.s3 import S3Storage
from tests.unit.test_s3_storage import FakeS3Client

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "media"
    / "backfill_product_image_variants.py"
)
_spec = importlib.util.spec_from_file_location(
    "backfill_product_image_variants", _SCRIPT
)
assert _spec is not None and _spec.loader is not None
_backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backfill)


# JPEG original для backfill.
def _jpeg_bytes(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    image = Image.new("RGB", (640, 480), color)
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


# LocalStorage с одним original.
def _local_with_original(tmp_path: Path) -> LocalStorage:
    storage = LocalStorage(root=tmp_path)
    storage.put("products/hero.jpg", _jpeg_bytes(), "image/jpeg")
    return storage


def test_backfill_dry_run_does_not_write(tmp_path: Path) -> None:
    storage = _local_with_original(tmp_path)
    report = _backfill.run_backfill(storage, apply=False)
    assert report["dry_run"] is True
    assert report["missing"] == 3
    assert report["created"] == 0
    assert report["failed"] == 0
    assert not storage.exists("products/hero_300.jpg")
    assert storage.exists("products/hero.jpg")


def test_backfill_apply_creates_missing_and_is_idempotent(tmp_path: Path) -> None:
    storage = _local_with_original(tmp_path)
    original = storage.read("products/hero.jpg")
    first = _backfill.run_backfill(storage, apply=True)
    assert first["created"] == 3
    assert first["failed"] == 0
    assert storage.exists("products/hero_300.jpg")
    assert storage.exists("products/hero_600.jpg")
    assert storage.exists("products/hero_900.jpg")
    second = _backfill.run_backfill(storage, apply=True)
    assert second["created"] == 0
    assert second["already_exists"] == 3
    assert second["missing"] == 0
    dry = _backfill.run_backfill(storage, apply=False)
    assert dry["missing"] == 0
    assert dry["already_exists"] == 3
    assert storage.read("products/hero.jpg") == original


def test_backfill_does_not_overwrite_existing_variant(tmp_path: Path) -> None:
    storage = _local_with_original(tmp_path)
    marker = b"keep-me"
    storage.put("products/hero_600.jpg", marker, "image/jpeg")
    report = _backfill.run_backfill(storage, apply=True)
    assert report["created"] == 2
    assert report["already_exists"] == 1
    assert storage.read("products/hero_600.jpg") == marker


def test_backfill_one_failure_does_not_stop_batch(tmp_path: Path) -> None:
    storage = LocalStorage(root=tmp_path)
    storage.put("products/ok.jpg", _jpeg_bytes(), "image/jpeg")
    storage.put("products/bad.jpg", b"not-an-image", "image/jpeg")
    report = _backfill.run_backfill(storage, apply=True)
    assert report["failed"] == 1
    assert report["created"] == 3
    assert storage.exists("products/ok_300.jpg")
    assert not storage.exists("products/bad_300.jpg")
    assert storage.exists("products/bad.jpg")
    assert report["failed_keys"][0]["key"] == "products/bad.jpg"


def test_backfill_s3_backend() -> None:
    fake = FakeS3Client()
    storage = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    storage.put("products/hero.jpg", _jpeg_bytes(), "image/jpeg")
    dry = _backfill.run_backfill(storage, apply=False)
    assert dry["missing"] == 3
    assert not storage.exists("products/hero_300.jpg")
    applied = _backfill.run_backfill(storage, apply=True)
    assert applied["created"] == 3
    assert applied["failed"] == 0
    assert storage.exists("products/hero_300.jpg")
    assert storage.exists("products/hero.jpg")


def test_backfill_dual_backend(tmp_path: Path) -> None:
    local = LocalStorage(root=tmp_path)
    fake = FakeS3Client()
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    dual = DualStorage(s3, local)
    dual.put("products/hero.jpg", _jpeg_bytes(), "image/jpeg")
    report = _backfill.run_backfill(dual, apply=True)
    assert report["created"] == 3
    assert report["failed"] == 0
    assert local.exists("products/hero_600.jpg")
    assert s3.exists("products/hero_600.jpg")


class _BoomStorage:
    def iter_keys(self, prefix: str = "") -> list[str]:
        _ = prefix
        return [f"products/x{i}.jpg" for i in range(40)]

    def exists(self, key: str) -> bool:
        raise RuntimeError("s3 down")

    def read(self, key: str) -> bytes:
        raise RuntimeError(key)

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        raise RuntimeError(key)


def test_backfill_stops_after_consecutive_failures() -> None:
    report = _backfill.run_backfill(_BoomStorage(), apply=True)
    assert report["stopped_early"] is True
    assert report["failed"] == 25
    assert report["created"] == 0
