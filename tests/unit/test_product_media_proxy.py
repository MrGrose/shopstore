from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import RedirectResponse, Response

from src.core.config import settings
from src.main import _product_media_response, serve_product_media


def test_product_media_reads_via_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    (products / "abc.jpg").write_bytes(b"jpeg-bytes")

    response = _product_media_response("abc.jpg")

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.body == b"jpeg-bytes"
    assert response.media_type == "image/jpeg"
    assert response.headers["Cache-Control"] == ("public, max-age=31536000, immutable")


def test_product_media_missing_is_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    with pytest.raises(HTTPException) as exc:
        _product_media_response("missing.jpg")
    assert exc.value.status_code == 404


def test_product_media_rejects_nested_and_non_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    (products / "note.txt").write_bytes(b"nope")
    with pytest.raises(HTTPException) as nested:
        _product_media_response("a/b.jpg")
    assert nested.value.status_code == 404
    with pytest.raises(HTTPException) as txt:
        _product_media_response("note.txt")
    assert txt.value.status_code == 404


def test_product_media_route_does_not_serve_support_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    (products / "abc.jpg").write_bytes(b"jpeg-bytes")

    mini = FastAPI()
    mini.add_api_route(
        "/media/products/{file_name}",
        serve_product_media,
        methods=["GET"],
    )
    client = TestClient(mini)
    found = client.get("/media/products/abc.jpg")
    hidden = client.get("/media/support/secret.jpg")
    assert found.status_code == 200
    assert found.content == b"jpeg-bytes"
    assert hidden.status_code == 404


def test_product_media_redirects_when_public_base_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    (products / "abc.jpg").write_bytes(b"jpeg-bytes")

    response = _product_media_response("abc.jpg")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://media.example.com/media/products/abc.jpg"
    )
