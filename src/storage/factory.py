from pathlib import Path

from src.core.config import settings
from src.storage.base import Storage
from src.storage.dual import DualStorage
from src.storage.local import LocalStorage
from src.storage.s3 import S3Storage

_ALLOWED = frozenset({"local", "s3", "dual"})


# LocalStorage с root = родитель MEDIA_ROOT (keys: products/{file}).
def _local() -> LocalStorage:
    return LocalStorage(root=Path(settings.MEDIA_ROOT).parent)


# S3Storage на SeaweedFS (или другом S3 endpoint из env).
def _s3() -> S3Storage:
    endpoint = settings.S3_ENDPOINT.strip()
    if not endpoint:
        raise RuntimeError("S3_ENDPOINT обязателен при STORAGE_BACKEND=s3 или dual")
    if not settings.S3_ACCESS_KEY.strip() or not settings.S3_SECRET_KEY.strip():
        raise RuntimeError(
            "S3_ACCESS_KEY и S3_SECRET_KEY обязательны при STORAGE_BACKEND=s3 или dual"
        )
    return S3Storage(
        endpoint,
        settings.S3_ACCESS_KEY,
        settings.S3_SECRET_KEY,
        settings.S3_BUCKET,
        settings.S3_REGION,
    )


# Единственная точка выбора backend: local | s3 | dual.
def get_storage() -> Storage:
    backend = settings.STORAGE_BACKEND.strip().lower()
    if backend not in _ALLOWED:
        raise RuntimeError(
            f"STORAGE_BACKEND={backend!r} не поддерживается; "
            "используйте local, s3 или dual"
        )
    if backend == "local":
        return _local()
    if backend == "s3":
        return _s3()
    return DualStorage(_s3(), _local())
