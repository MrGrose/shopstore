import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "media"
    / "migrate_remove_duplicate_previews.py"
)


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "migrate_remove_duplicate_previews", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def migrate():
    return _load_mod()


SIZES = (300, 600, 900)


def test_dry_run_does_not_delete_byte_identical_preview(
    tmp_path: Path, migrate
) -> None:
    original = tmp_path / "hero.jpg"
    preview = tmp_path / "hero_600.jpg"
    original.write_bytes(b"original-bytes")
    preview.write_bytes(b"original-bytes")
    scan = migrate.run(media_root=tmp_path, apply=False, sizes=SIZES)
    assert [path.name for path in scan.duplicates] == ["hero_600.jpg"]
    assert preview.is_file()
    assert original.is_file()


def test_apply_deletes_only_byte_identical_previews(tmp_path: Path, migrate) -> None:
    original = tmp_path / "hero.jpg"
    dup_300 = tmp_path / "hero_300.jpg"
    dup_600 = tmp_path / "hero_600.jpg"
    resized = tmp_path / "hero_900.jpg"
    original.write_bytes(b"original-bytes")
    dup_300.write_bytes(b"original-bytes")
    dup_600.write_bytes(b"original-bytes")
    resized.write_bytes(b"smaller-resized")
    scan = migrate.run(media_root=tmp_path, apply=True, sizes=SIZES)
    assert sorted(path.name for path in scan.duplicates) == [
        "hero_300.jpg",
        "hero_600.jpg",
    ]
    assert not dup_300.exists()
    assert not dup_600.exists()
    assert resized.is_file()
    assert original.is_file()
    assert scan.non_identical == 1


def test_same_size_different_bytes_is_not_duplicate(tmp_path: Path, migrate) -> None:
    original = tmp_path / "hero.jpg"
    preview = tmp_path / "hero_600.jpg"
    original.write_bytes(b"aaaa")
    preview.write_bytes(b"bbbb")
    scan = migrate.scan_duplicate_previews(tmp_path, sizes=SIZES)
    assert scan.duplicates == []
    assert scan.non_identical == 1
    assert preview.is_file()


def test_missing_original_is_not_deleted(tmp_path: Path, migrate) -> None:
    preview = tmp_path / "hero_600.jpg"
    preview.write_bytes(b"orphan-preview")
    scan = migrate.run(media_root=tmp_path, apply=True, sizes=SIZES)
    assert scan.duplicates == []
    assert scan.missing_originals == 1
    assert preview.is_file()


def test_non_preview_names_are_originals(tmp_path: Path, migrate) -> None:
    keep = tmp_path / "hero_3000.jpg"
    keep.write_bytes(b"not-a-preview")
    scan = migrate.scan_duplicate_previews(tmp_path, sizes=SIZES)
    assert scan.originals == 1
    assert scan.previews == 0
    assert keep.is_file()


def test_report_labels(
    tmp_path: Path, migrate, capsys: pytest.CaptureFixture[str]
) -> None:
    original = tmp_path / "hero.png"
    preview = tmp_path / "hero_300.png"
    original.write_bytes(b"png-bytes")
    preview.write_bytes(b"png-bytes")
    migrate.run(media_root=tmp_path, apply=False, sizes=SIZES)
    out = capsys.readouterr().out
    assert "Оригиналов: 1" in out
    assert "Превью: 1" in out
    assert "Дубликатов превью: 1" in out
    assert "Можно освободить:" in out
    assert "Неидентичных превью: 0" in out
    assert "Превью без оригинала: 0" in out
    assert "Ошибок чтения/сравнения: 0" in out
    assert "Пробный запуск — ничего не удалено." in out


def test_read_error_does_not_delete_preview(tmp_path: Path, migrate) -> None:
    original = tmp_path / "hero.jpg"
    preview = tmp_path / "hero_600.jpg"
    original.write_bytes(b"original-bytes")
    preview.write_bytes(b"original-bytes")
    original.chmod(0o000)
    scan = migrate.run(media_root=tmp_path, apply=True, sizes=SIZES)
    assert scan.duplicates == []
    assert len(scan.errors) == 1
    assert preview.is_file()
    original.chmod(0o644)


def test_report_json_writes_duplicate_list(tmp_path: Path, migrate) -> None:
    original = tmp_path / "hero.jpg"
    preview = tmp_path / "hero_300.jpg"
    original.write_bytes(b"same")
    preview.write_bytes(b"same")
    report_path = tmp_path / "report.json"
    migrate.run(
        media_root=tmp_path,
        apply=False,
        sizes=SIZES,
        report_json=report_path,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["duplicate_previews"] == 1
    assert payload["duplicate_names"] == ["hero_300.jpg"]
    assert payload["apply"] is False


def test_main_defaults_to_dry_run(
    tmp_path: Path, migrate, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "hero.jpg"
    preview = tmp_path / "hero_600.jpg"
    original.write_bytes(b"same")
    preview.write_bytes(b"same")
    monkeypatch.setattr(
        sys,
        "argv",
        ["migrate_remove_duplicate_previews.py", "--media-root", str(tmp_path)],
    )
    migrate.main()
    assert preview.is_file()
    assert original.is_file()
