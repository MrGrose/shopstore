import importlib.util
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.core.config import settings
from src.main import _product_media_response
from src.storage.local import LocalStorage
from src.storage.s3 import S3Storage
from src.utils.images import (
    KNOWN_CORRUPT_ORIGINAL_NAMES,
    _store_product_bytes,
    is_product_variant_filename,
)
from tests.unit.test_s3_storage import FakeS3Client

_VERIFY = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "media"
    / "verify_local_vs_s3_product_media.py"
)
_REMOVE = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "media"
    / "remove_local_product_media.py"
)


# Загружает CLI-скрипт как модуль.
def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_verify = _load(_VERIFY, "verify_local_vs_s3_product_media")
_remove = _load(_REMOVE, "remove_local_product_media")


# JPEG original для compare/remove.
def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), (8, 16, 24))
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


# Local + in-memory S3 для compare/remove.
def _pair(tmp_path: Path) -> tuple[LocalStorage, S3Storage]:
    local = LocalStorage(root=tmp_path)
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=FakeS3Client(),
    )
    return local, s3


def test_is_product_variant_filename() -> None:
    assert is_product_variant_filename("abc_300.jpg") is True
    assert is_product_variant_filename("abc_600.jpg") is True
    assert is_product_variant_filename("abc.jpg") is False
    assert is_product_variant_filename("abc_3000.jpg") is False


def test_verify_counts_match_and_missing(tmp_path: Path) -> None:
    local, s3 = _pair(tmp_path)
    data = _jpeg_bytes()
    local.put("products/ok.jpg", data, "image/jpeg")
    s3.put("products/ok.jpg", data, "image/jpeg")
    s3.put("products/ok_300.jpg", data, "image/jpeg")
    report = _verify.compare_product_media(local, s3)
    assert report["originals"]["matched"] == 1
    assert report["originals"]["missing_local"] == 0
    assert report["variants"]["missing_local"] == 1
    assert report["variants"]["s3"] == 1


def test_remove_dry_run_does_not_delete(tmp_path: Path) -> None:
    local, s3 = _pair(tmp_path)
    data = _jpeg_bytes()
    local.put("products/ok.jpg", data, "image/jpeg")
    s3.put("products/ok.jpg", data, "image/jpeg")
    report = _remove.plan_removal(local, s3, apply=False)
    assert report["dry_run"] is True
    assert report["eligible"] == 1
    assert report["deleted"] == 0
    assert local.exists("products/ok.jpg")


def test_remove_apply_deletes_only_verified(tmp_path: Path) -> None:
    local, s3 = _pair(tmp_path)
    data = _jpeg_bytes()
    local.put("products/ok.jpg", data, "image/jpeg")
    s3.put("products/ok.jpg", data, "image/jpeg")
    local.put("products/mismatch.jpg", data, "image/jpeg")
    s3.put("products/mismatch.jpg", b"other", "image/jpeg")
    local.put("products/nos3.jpg", data, "image/jpeg")
    corrupt = next(iter(KNOWN_CORRUPT_ORIGINAL_NAMES))
    local.put(f"products/{corrupt}", data, "image/jpeg")
    local.put("products/note.txt", b"x", "text/plain")
    report = _remove.plan_removal(local, s3, apply=True)
    assert report["deleted"] == 1
    assert local.exists("products/ok.jpg") is False
    assert local.exists("products/mismatch.jpg") is True
    assert local.exists("products/nos3.jpg") is True
    assert local.exists(f"products/{corrupt}") is True
    assert local.exists("products/note.txt") is True
    skipped = report["skipped_by_reason"]
    assert skipped["mismatch"] == 1
    assert skipped["missing_s3"] == 1
    assert skipped["corrupt"] == 1
    assert skipped["not_product_media"] == 1


def test_remove_repeat_is_idempotent(tmp_path: Path) -> None:
    local, s3 = _pair(tmp_path)
    data = _jpeg_bytes()
    local.put("products/ok.jpg", data, "image/jpeg")
    s3.put("products/ok.jpg", data, "image/jpeg")
    first = _remove.plan_removal(local, s3, apply=True)
    second = _remove.plan_removal(local, s3, apply=True)
    assert first["deleted"] == 1
    assert second["deleted"] == 0
    assert second["eligible"] == 0


def test_s3_backend_read_does_not_need_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    fake = FakeS3Client()
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    s3.put("products/abc.jpg", b"from-s3", "image/jpeg")
    monkeypatch.setattr("src.main.get_storage", lambda: s3)
    response = _product_media_response("abc.jpg")
    assert response.body == b"from-s3"
    assert not (products / "abc.jpg").exists()


def test_s3_upload_writes_storage_not_media_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    fake = FakeS3Client()
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    monkeypatch.setattr("src.utils.images.get_storage", lambda: s3)
    url = _store_product_bytes("hero.jpg", _jpeg_bytes(), "image/jpeg")
    assert url == "/media/products/hero.jpg"
    assert not (products / "hero.jpg").exists()
    assert s3.exists("products/hero.jpg")
    assert s3.exists("products/hero_300.jpg")
