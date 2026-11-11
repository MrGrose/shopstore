from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from src.core.config import settings
from src.storage import get_storage
from src.storage.local import LocalStorage
from src.utils import images as image_utils


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path, public_prefix="/media")


def test_put_creates_file(storage: LocalStorage, tmp_path: Path) -> None:
    storage.put("products/foo.jpg", b"jpeg-bytes")
    assert (tmp_path / "products" / "foo.jpg").read_bytes() == b"jpeg-bytes"


def test_read_roundtrip(storage: LocalStorage) -> None:
    storage.put("products/foo.jpg", b"hello")
    assert storage.read("products/foo.jpg") == b"hello"


def test_exists_true_false(storage: LocalStorage) -> None:
    assert storage.exists("products/missing.jpg") is False
    storage.put("products/foo.jpg", b"x")
    assert storage.exists("products/foo.jpg") is True


def test_delete_removes_file(storage: LocalStorage) -> None:
    storage.put("products/foo.jpg", b"x")
    storage.delete("products/foo.jpg")
    assert storage.exists("products/foo.jpg") is False


def test_delete_missing_is_noop(storage: LocalStorage) -> None:
    storage.delete("products/missing.jpg")


def test_public_url_matches_local_media_contract(storage: LocalStorage) -> None:
    assert storage.public_url("products/foo.jpg") == "/media/products/foo.jpg"


def test_namespace_maps_under_media_root(storage: LocalStorage, tmp_path: Path) -> None:
    storage.put("products/foo.jpg", b"x")
    storage.put("support/note.txt", b"y")
    assert (tmp_path / "products" / "foo.jpg").is_file()
    assert (tmp_path / "support" / "note.txt").is_file()


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "products/../../etc/passwd",
        "/etc/passwd",
        r"..\secret",
        "products/foo/../../../etc/passwd",
    ],
)
def test_traversal_is_rejected(storage: LocalStorage, key: str) -> None:
    with pytest.raises(ValueError, match="storage key"):
        storage.put(key, b"x")
    with pytest.raises(ValueError, match="storage key"):
        storage.read(key)
    with pytest.raises(ValueError, match="storage key"):
        storage.exists(key)


def test_get_storage_uses_media_root_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    backend = get_storage()
    backend.put("products/from-factory.jpg", b"z")
    assert (products / "from-factory.jpg").read_bytes() == b"z"
    assert backend.public_url("products/from-factory.jpg") == (
        "/media/products/from-factory.jpg"
    )


def test_get_storage_rejects_unknown_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "ftp")
    with pytest.raises(RuntimeError, match="не поддерживается"):
        get_storage()


@pytest.mark.asyncio
async def test_save_product_image_writes_via_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(products))
    monkeypatch.setattr(image_utils, "MEDIA_ROOT", products)
    monkeypatch.setattr(image_utils, "MEDIA_URL_PREFIX", "/media/products")
    monkeypatch.setattr(image_utils, "PREVIEW_SIZES", (600,))

    payload = BytesIO()
    Image.new("RGB", (800, 400), (10, 20, 30)).save(payload, format="JPEG")
    upload = UploadFile(
        filename="photo.jpg",
        file=BytesIO(payload.getvalue()),
        headers=Headers({"content-type": "image/jpeg"}),
    )

    url = await image_utils.save_product_image(upload)
    assert url.startswith("/media/products/")
    name = Path(url).name
    original = products / name
    preview = products / f"{Path(name).stem}_600.jpg"
    assert original.is_file()
    assert preview.is_file()
    assert original.read_bytes() != preview.read_bytes()
    with Image.open(preview) as img:
        assert img.size == (600, 300)


def test_local_iter_key_mtimes_uses_file_mtime(tmp_path: Path) -> None:
    storage = LocalStorage(root=tmp_path)
    storage.put("support/1/a.jpg", b"x", "image/jpeg")
    rows = dict(storage.iter_key_mtimes("support/"))
    assert "support/1/a.jpg" in rows
    mtime = rows["support/1/a.jpg"]
    assert mtime is not None
    assert abs((datetime.now(UTC) - mtime).total_seconds()) < 10
