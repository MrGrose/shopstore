import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "media"
    / "migrate_product_media_to_s3.py"
)


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "migrate_product_media_to_s3", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def migrate():
    return _load_mod()


UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# Original vs legacy preview vs I7 variant.
def test_is_original_name_skips_legacy_and_variants(migrate) -> None:
    is_orig = migrate._is_original_name
    assert is_orig(f"{UUID}.jpg") is True
    assert is_orig(f"{UUID}_300.jpg") is False
    assert is_orig(f"{UUID}_600.jpg") is False
    assert is_orig(f"{UUID}_900.jpg") is False
    assert is_orig(f"{UUID}_w160.jpg") is False
    assert is_orig(f"{UUID}_w560.jpg") is False
    assert is_orig(f"{UUID}_w1400.jpg") is False
    assert is_orig("readme.txt") is False


def test_is_variant_name_matches_current_and_legacy(migrate) -> None:
    is_var = migrate._is_variant_name
    assert is_var(f"{UUID}_300.jpg") is True
    assert is_var(f"{UUID}_600.jpg") is True
    assert is_var(f"{UUID}_900.jpg") is True
    assert is_var(f"{UUID}_w160.jpg") is True
    assert is_var(f"{UUID}.jpg") is False
    assert is_var("readme.txt") is False


def test_iter_items_variants_only_excludes_originals(tmp_path: Path, migrate) -> None:
    original = tmp_path / f"{UUID}.jpg"
    variant = tmp_path / f"{UUID}_300.jpg"
    legacy = tmp_path / f"{UUID}_w560.jpg"
    original.write_bytes(b"orig")
    variant.write_bytes(b"var")
    legacy.write_bytes(b"legacy")
    items = migrate._iter_items(
        tmp_path, MagicMock(), reverse=False, variants_only=True
    )
    names = sorted(path.name for path, _ in items)
    assert names == [f"{UUID}_300.jpg", f"{UUID}_w560.jpg"]
    assert original.name not in names


def test_iter_items_originals_excludes_variants(tmp_path: Path, migrate) -> None:
    original = tmp_path / f"{UUID}.jpg"
    variant = tmp_path / f"{UUID}_600.jpg"
    original.write_bytes(b"orig")
    variant.write_bytes(b"var")
    items = migrate._iter_items(
        tmp_path, MagicMock(), reverse=False, variants_only=False
    )
    names = [path.name for path, _ in items]
    assert names == [f"{UUID}.jpg"]


def test_process_one_dry_run_counts_upload_candidate(tmp_path: Path, migrate) -> None:
    path = tmp_path / f"{UUID}_300.jpg"
    path.write_bytes(b"variant-bytes")
    report: dict[str, object] = {
        "uploaded": 0,
        "already_exists": 0,
        "verified": 0,
        "failed": 0,
        "skipped": 0,
        "failed_keys": [],
        "total_source_bytes": 0,
    }
    s3 = MagicMock()
    s3.exists.return_value = False
    migrate._process_one(
        path,
        f"products/{path.name}",
        MagicMock(),
        s3,
        apply=False,
        reverse=False,
        overwrite=False,
        report=report,
    )
    assert report["skipped"] == 1
    assert report["uploaded"] == 0
    assert report["total_source_bytes"] == len(b"variant-bytes")
    s3.put.assert_not_called()


def test_process_one_idempotent_when_hash_matches(tmp_path: Path, migrate) -> None:
    path = tmp_path / f"{UUID}_900.jpg"
    data = b"same-bytes"
    path.write_bytes(data)
    report: dict[str, object] = {
        "uploaded": 0,
        "already_exists": 0,
        "verified": 0,
        "failed": 0,
        "skipped": 0,
        "failed_keys": [],
        "total_source_bytes": 0,
    }
    s3 = MagicMock()
    s3.exists.return_value = True
    s3.read.return_value = data
    migrate._process_one(
        path,
        f"products/{path.name}",
        MagicMock(),
        s3,
        apply=True,
        reverse=False,
        overwrite=False,
        report=report,
    )
    assert report["already_exists"] == 1
    assert report["failed"] == 0
    s3.put.assert_not_called()


def test_process_one_mismatch_fails_without_overwrite(tmp_path: Path, migrate) -> None:
    path = tmp_path / f"{UUID}_300.jpg"
    path.write_bytes(b"local")
    report: dict[str, object] = {
        "uploaded": 0,
        "already_exists": 0,
        "verified": 0,
        "failed": 0,
        "skipped": 0,
        "failed_keys": [],
        "total_source_bytes": 0,
    }
    s3 = MagicMock()
    s3.exists.return_value = True
    s3.read.return_value = b"remote"
    migrate._process_one(
        path,
        f"products/{path.name}",
        MagicMock(),
        s3,
        apply=True,
        reverse=False,
        overwrite=False,
        report=report,
    )
    assert report["failed"] == 1
    assert report["failed_keys"] == [
        {"key": f"products/{path.name}", "error": "exists but size/hash mismatch"}
    ]


def test_documented_missing_variant_keys_for_corrupt_originals(migrate) -> None:
    keys = migrate._documented_missing_variant_keys()
    assert len(keys) == 6
    assert keys == sorted(keys)
    assert all(key.endswith(".jpg") for key in keys)
    assert all("_300" in key or "_600" in key or "_900" in key for key in keys)
