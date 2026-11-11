from datetime import datetime
from typing import Protocol


# Контракт хранения файлов.
class Storage(Protocol):
    # Пишет объект по логическому ключу.
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    # Удаляет объект; отсутствие ключа — no-op.
    def delete(self, key: str) -> None: ...

    # Проверяет, есть ли объект.
    def exists(self, key: str) -> bool: ...

    # Читает байты объекта.
    def read(self, key: str) -> bytes: ...

    # Публичный URL для product media (не для приватных вложений).
    def public_url(self, key: str) -> str: ...

    # Ключи с данным prefix.
    def iter_keys(self, prefix: str = "") -> list[str]: ...

    # Ключи и mtime/LastModified; нет метки → None.
    def iter_key_mtimes(
        self, prefix: str = ""
    ) -> list[tuple[str, datetime | None]]: ...
