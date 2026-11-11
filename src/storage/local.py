from datetime import UTC, datetime
from pathlib import Path


# Локальный backend: key -> файл под media root.
class LocalStorage:
    # root -> каталог /media (внутри него products/, позже support/).
    def __init__(self, root: Path | str, public_prefix: str = "/media") -> None:
        self._root = Path(root).resolve()
        self._public_prefix = public_prefix.rstrip("/") or "/media"

    # Превращает логический key в путь внутри media root.
    def _path_for_key(self, key: str) -> Path:
        normalized = key.replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or normalized.endswith("/")
            or "\x00" in normalized
        ):
            raise ValueError("Некорректный storage key")
        first = normalized.split("/", 1)[0]
        if ":" in first:
            raise ValueError("Некорректный storage key")
        parts = Path(normalized).parts
        if any(part == ".." for part in parts):
            raise ValueError("Некорректный storage key")
        path = (self._root / normalized).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError("Некорректный storage key")
        return path

    # Пишет файл по key; content_type для local не используется.
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _ = content_type

    # Удаляет файл, если он есть.
    def delete(self, key: str) -> None:
        path = self._path_for_key(key)
        if path.is_file():
            path.unlink()

    # True, если по key лежит обычный файл.
    def exists(self, key: str) -> bool:
        path = self._path_for_key(key)
        return path.is_file()

    # Читает байты файла.
    def read(self, key: str) -> bytes:
        path = self._path_for_key(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    # URL вида /media/products/foo.jpg.
    def public_url(self, key: str) -> str:
        # Lazy import: images ↔ storage, иначе циклический импорт при загрузке settings.
        from src.utils.images import public_url_for_storage_key

        return public_url_for_storage_key(key)

    # Ключи файлов под данным prefix.
    def iter_keys(self, prefix: str = "") -> list[str]:
        return [key for key, _mtime in self.iter_key_mtimes(prefix)]

    # Ключи и mtime файлов под prefix (UTC).
    def iter_key_mtimes(self, prefix: str = "") -> list[tuple[str, datetime | None]]:
        normalized = prefix.replace("\\", "/").strip("/")
        base = self._root / normalized if normalized else self._root
        if not base.is_dir():
            return []
        rows: list[tuple[str, datetime | None]] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(self._root).as_posix()
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            rows.append((key, mtime))
        rows.sort(key=lambda item: item[0])
        return rows
