import argparse
import filecmp
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.images import MEDIA_ROOT, PREVIEW_SIZES  # noqa: E402

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SAMPLE_LIMIT = 10


# Результат сканирования дубликатов превью.
@dataclass
class DuplicatePreviewScan:
    media_root: Path
    originals: int = 0
    previews: int = 0
    duplicates: list[Path] = field(default_factory=list)
    non_identical: int = 0
    missing_originals: int = 0
    bytes_reclaimable: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


# Если имя файла — превью с суффиксом размера, возвращает имя оригинала.
def preview_original_name(name: str, sizes: Sequence[int]) -> str | None:
    path = Path(name)
    suffix = path.suffix.lower()
    if suffix not in _IMAGE_SUFFIXES:
        return None
    stem = path.stem
    for size in sorted(sizes, key=lambda item: len(str(item)), reverse=True):
        tag = f"_{size}"
        if not stem.endswith(tag):
            continue
        base = stem[: -len(tag)]
        if not base:
            continue
        return f"{base}{path.suffix}"
    return None


# Совпадают ли файлы байт в байт. None — ошибка чтения/доступа.
def _is_byte_identical(left: Path, right: Path) -> bool | None:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return filecmp.cmp(left, right, shallow=False)
    except OSError:
        return None


# Сканирует каталог media. Ничего не удаляет.
def scan_duplicate_previews(
    media_root: Path, sizes: Sequence[int] | None = None
) -> DuplicatePreviewScan:
    preview_sizes = tuple(sizes if sizes is not None else PREVIEW_SIZES)
    result = DuplicatePreviewScan(media_root=media_root)
    if not media_root.is_dir():
        return result

    for path in media_root.iterdir():
        if not path.is_file():
            continue
        original_name = preview_original_name(path.name, preview_sizes)
        if original_name is None:
            result.originals += 1
            continue

        result.previews += 1
        original = media_root / original_name
        if not original.is_file():
            result.missing_originals += 1
            continue
        identical = _is_byte_identical(path, original)
        if identical is None:
            result.errors.append(
                {
                    "preview": path.name,
                    "original": original_name,
                    "error": "read or compare failed",
                }
            )
            continue
        if identical:
            result.duplicates.append(path)
            try:
                result.bytes_reclaimable += path.stat().st_size
            except OSError:
                result.errors.append(
                    {
                        "preview": path.name,
                        "original": original_name,
                        "error": "stat failed after duplicate match",
                    }
                )
        else:
            result.non_identical += 1
    return result


# Человекочитаемый размер для отчёта.
def _format_bytes(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.2f} ГБ"
    if size >= 1024**2:
        return f"{size / 1024**2:.2f} МБ"
    if size >= 1024:
        return f"{size / 1024:.2f} КБ"
    return f"{size} байт"


# JSON-отчёт для dry-run/apply.
def build_report(scan: DuplicatePreviewScan, apply: bool) -> dict[str, object]:
    return {
        "media_root": str(scan.media_root),
        "apply": apply,
        "originals": scan.originals,
        "previews": scan.previews,
        "duplicate_previews": len(scan.duplicates),
        "non_identical_previews": scan.non_identical,
        "missing_originals": scan.missing_originals,
        "errors": len(scan.errors),
        "bytes_reclaimable": scan.bytes_reclaimable,
        "duplicate_names": [path.name for path in scan.duplicates],
        "error_details": scan.errors,
    }


# Печатает статистику сканирования.
def print_report(scan: DuplicatePreviewScan, apply: bool) -> None:
    print(f"Каталог media: {scan.media_root}")
    print(f"Оригиналов: {scan.originals}")
    print(f"Превью: {scan.previews}")
    print(f"Дубликатов превью: {len(scan.duplicates)}")
    print(
        f"Можно освободить: {_format_bytes(scan.bytes_reclaimable)}"
        f" ({scan.bytes_reclaimable} байт)"
    )
    print(f"Неидентичных превью: {scan.non_identical}")
    print(f"Превью без оригинала: {scan.missing_originals}")
    print(f"Ошибок чтения/сравнения: {len(scan.errors)}")
    if scan.duplicates:
        print("Примеры дубликатов:")
        for path in scan.duplicates[:_SAMPLE_LIMIT]:
            print(f"  {path.name}")
    if scan.errors:
        print("Примеры ошибок:")
        for row in scan.errors[:_SAMPLE_LIMIT]:
            print(f"  {row['preview']} ({row['error']})")
    if apply:
        print(f"Удалено дубликатов превью: {len(scan.duplicates)}")
    else:
        print("Пробный запуск — ничего не удалено.")


# Удаляет уже отобранные дубликаты превью.
def delete_duplicates(paths: Sequence[Path]) -> None:
    for path in paths:
        path.unlink()


# Сканирует media и при необходимости удаляет только байтовые копии превью.
def run(
    media_root: Path,
    apply: bool,
    sizes: Sequence[int] | None = None,
    report_json: Path | None = None,
) -> DuplicatePreviewScan:
    scan = scan_duplicate_previews(media_root, sizes=sizes)
    if apply:
        delete_duplicates(scan.duplicates)
    print_report(scan, apply=apply)
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(
            json.dumps(build_report(scan, apply=apply), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON-отчёт: {report_json}")
    return scan


# Точка входа: по умолчанию только отчёт, --apply удаляет дубли.
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Удаляет превью _300/_600/_900, которые байт в байт "
            "совпадают с оригиналом. По умолчанию только отчёт."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="удалить дубликаты (по умолчанию только отчёт)",
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=None,
        help="каталог media (по умолчанию из настроек)",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="сохранить полный JSON-отчёт (список дубликатов и ошибок)",
    )
    args = parser.parse_args()
    media_root = args.media_root if args.media_root is not None else MEDIA_ROOT
    if not media_root.is_dir():
        print(f"ОШИБКА: директория media не найдена: {media_root}", file=sys.stderr)
        raise SystemExit(1)
    run(
        media_root=media_root,
        apply=args.apply,
        report_json=args.report_json,
    )


if __name__ == "__main__":
    main()
