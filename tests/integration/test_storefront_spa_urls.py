from pathlib import Path

import httpx
import pytest

from src.main import app


@pytest.fixture
def storefront_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<html><body>storefront</body></html>", encoding="utf-8"
    )
    monkeypatch.setattr(
        "src.web.storefront_spa.settings.STOREFRONT_DIST_DIR", str(dist)
    )
    return dist


@pytest.mark.asyncio
async def test_storefront_spa_routes_serve_index(storefront_dist: Path) -> None:
    del storefront_dist
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        for path in ("/", "/catalog", "/catalog/all", "/catalog/padel"):
            response = await client.get(path)
            assert response.status_code == 200, path
            assert "storefront" in response.text


@pytest.mark.asyncio
async def test_ref_alias_redirects_to_home_with_ref() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get("/ref/partner-alias", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/?ref=partner-alias"


@pytest.mark.asyncio
async def test_legacy_catalog_ref_serves_spa_without_server_redirect(
    storefront_dist: Path,
) -> None:
    del storefront_dist
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get("/catalog?ref=legacycode", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers.get("location") is None
