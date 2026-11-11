import os

# Host pytest: loopback Redis до чтения Settings из compose-oriented .env (redis:6379).
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

import pytest  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.repositories.session import async_engine  # noqa: E402


# Тесты всегда на LocalStorage, даже если в .env остался STORAGE_BACKEND=s3 или dual.
@pytest.fixture(autouse=True)
def _storage_backend_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")


# Сбрасывает пул async engine после теста (избегает «attached to a different loop»).
@pytest.fixture(autouse=True)
async def reset_async_engine_pool():
    yield
    await async_engine.dispose()
