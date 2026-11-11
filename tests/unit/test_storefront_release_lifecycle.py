from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.catalog.display.constants import (
    RELEASE_STATUS_BACKFILLED,
    RELEASE_STATUS_DRAFT,
    RELEASE_STATUS_VERIFIED_DIRTY,
)
from src.services.catalog.display.release_service import (
    StorefrontReleaseError,
    StorefrontReleaseService,
)


class _FakeRepo:
    def __init__(self, release) -> None:
        self._release = release

    async def get_release(self, release_id: int):
        return self._release


class _FakeReconciler:
    async def run(self, release_id: int):
        from src.services.catalog.display.reconciler import CoverageReport

        return CoverageReport(0, 0, 0, 1, 0, {})


@pytest.mark.asyncio
async def test_mark_verified_rejects_draft_without_backfill() -> None:
    release = type("R", (), {"id": 1, "status": RELEASE_STATUS_DRAFT})()
    svc = StorefrontReleaseService(session=MagicMock())
    svc.session.flush = AsyncMock()
    svc.repo = _FakeRepo(release)
    svc.reconciler = _FakeReconciler()
    with pytest.raises(StorefrontReleaseError, match="backfill"):
        await svc.mark_verified(1)


@pytest.mark.asyncio
async def test_mark_verified_allows_backfilled() -> None:
    release = type(
        "R",
        (),
        {
            "id": 1,
            "status": RELEASE_STATUS_BACKFILLED,
            "verified_at": None,
            "dirty_at": None,
        },
    )()
    svc = StorefrontReleaseService(session=MagicMock())
    svc.session.flush = AsyncMock()
    svc.repo = _FakeRepo(release)
    svc.reconciler = _FakeReconciler()
    result = await svc.mark_verified(1)
    assert result.status == "verified"


@pytest.mark.asyncio
async def test_mark_verified_allows_verified_dirty() -> None:
    release = type(
        "R",
        (),
        {
            "id": 2,
            "status": RELEASE_STATUS_VERIFIED_DIRTY,
            "verified_at": None,
            "dirty_at": object(),
        },
    )()
    svc = StorefrontReleaseService(session=MagicMock())
    svc.session.flush = AsyncMock()
    svc.repo = _FakeRepo(release)
    svc.reconciler = _FakeReconciler()
    result = await svc.mark_verified(2)
    assert result.status == "verified"
