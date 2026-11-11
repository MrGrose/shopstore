import logging
from datetime import UTC, datetime

from src.storage.base import Storage

logger = logging.getLogger(__name__)


# Более свежий mtime; None только если обе метки пустые.
def _newer_mtime(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    left_utc = left.astimezone(UTC) if left.tzinfo else left.replace(tzinfo=UTC)
    right_utc = right.astimezone(UTC) if right.tzinfo else right.replace(tzinfo=UTC)
    return max(left_utc, right_utc)


class DualStorage:
    # primary = S3, secondary = local (как в factory).
    def __init__(self, primary: Storage, secondary: Storage) -> None:
        self._primary = primary
        self._secondary = secondary

    # Сначала secondary (local), потом primary (S3).
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self._secondary.put(key, data, content_type)
        try:
            self._primary.put(key, data, content_type)
        except Exception:
            # Local уже записан; вызывающий откатывает через delete(key).
            logger.exception("DualStorage: local записан, S3 put не удался: %s", key)
            raise

    # Сначала secondary (local), потом primary (S3).
    def delete(self, key: str) -> None:
        self._secondary.delete(key)
        try:
            self._primary.delete(key)
        except Exception:
            logger.exception("DualStorage: local удалён, S3 delete не удался: %s", key)
            raise

    # True, если объект есть в S3 или на диске.
    def exists(self, key: str) -> bool:
        return self._primary.exists(key) or self._secondary.exists(key)

    # Читает S3, при отсутствии — local.
    def read(self, key: str) -> bytes:
        try:
            return self._primary.read(key)
        except FileNotFoundError:
            return self._secondary.read(key)

    # Тот же /media/products URL, что у LocalStorage.
    def public_url(self, key: str) -> str:
        return self._secondary.public_url(key)

    # Объединяет ключи primary и secondary без дублей.
    def iter_keys(self, prefix: str = "") -> list[str]:
        return [key for key, _mtime in self.iter_key_mtimes(prefix)]

    # Ключи и самый свежий mtime из двух backend'ов.
    def iter_key_mtimes(self, prefix: str = "") -> list[tuple[str, datetime | None]]:
        newest: dict[str, datetime | None] = {}
        for key, mtime in self._primary.iter_key_mtimes(prefix):
            newest[key] = mtime
        for key, mtime in self._secondary.iter_key_mtimes(prefix):
            newest[key] = _newer_mtime(newest.get(key), mtime)
        return list(newest.items())
