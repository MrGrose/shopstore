from pathlib import Path

import pytest
from fastapi import HTTPException

from src.web.storefront_spa import (
    is_storefront_ready,
    ready_storefront_check,
    storefront_readiness_error,
    storefront_spa_response,
)


def test_is_storefront_ready_true_when_index_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(
        "src.web.storefront_spa.settings.STOREFRONT_DIST_DIR", str(dist)
    )

    assert is_storefront_ready() is True
    assert storefront_readiness_error() is None
    assert ready_storefront_check(is_dev=False) is None


def test_is_storefront_ready_false_when_index_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "empty-dist"
    dist.mkdir()
    monkeypatch.setattr(
        "src.web.storefront_spa.settings.STOREFRONT_DIST_DIR", str(dist)
    )

    assert is_storefront_ready() is False
    assert storefront_readiness_error() == "storefront not built"
    assert ready_storefront_check(is_dev=False) == "storefront not built"
    assert ready_storefront_check(is_dev=True) is None


def test_storefront_spa_response_raises_when_dist_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "missing"
    dist.mkdir()
    monkeypatch.setattr(
        "src.web.storefront_spa.settings.STOREFRONT_DIST_DIR", str(dist)
    )

    with pytest.raises(HTTPException) as exc_info:
        storefront_spa_response()

    assert exc_info.value.status_code == 503
