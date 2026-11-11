import pytest

from src.core.config import settings
from src.storage.local import LocalStorage
from src.utils.images import (
    public_product_media_url,
    public_url_for_storage_key,
    resolve_product_image_url,
)


def test_public_product_media_url_without_base_keeps_relative() -> None:
    url = "/media/products/abc-123.jpg"
    assert public_product_media_url(url) == url


def test_public_product_media_url_with_base_joins_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    url = "/media/products/abc-123.jpg"
    assert (
        public_product_media_url(url)
        == "https://media.example.com/media/products/abc-123.jpg"
    )


def test_public_product_media_url_preserves_supplier_cdn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com")
    supplier = "https://cdn.shopify.com/s/files/1/a.jpg"
    assert public_product_media_url(supplier) == supplier


def test_public_product_media_url_variant_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://media.example.com/")
    original = "/media/products/uuid.jpg"
    variant = resolve_product_image_url(original, 600)
    assert variant == "https://media.example.com/media/products/uuid_600.jpg"


def test_public_url_for_storage_key_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        public_url_for_storage_key("../products/evil.jpg")


def test_public_url_for_storage_key_rejects_support_prefix() -> None:
    with pytest.raises(ValueError):
        public_url_for_storage_key("support/1/secret.jpg")


def test_storage_public_url_uses_media_public_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://cdn.example.com")
    assert (
        public_url_for_storage_key("products/a.jpg")
        == "https://cdn.example.com/media/products/a.jpg"
    )


def test_local_storage_public_url_without_base() -> None:
    storage = LocalStorage(root="/tmp/unused")
    assert storage.public_url("products/a.jpg") == "/media/products/a.jpg"


def test_media_public_base_rejects_credentials() -> None:
    from pydantic import ValidationError

    from src.core.config import Settings

    with pytest.raises(ValidationError, match="учётные данные"):
        Settings(MEDIA_PUBLIC_BASE="https://user:pass@cdn.example.com")


def test_store_product_bytes_keeps_relative_db_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.utils.images import MEDIA_URL_PREFIX, _store_product_bytes

    class FakeStorage:
        def put(
            self, key: str, content: bytes, content_type: str | None = None
        ) -> None:
            self.last_key = key

    fake = FakeStorage()
    monkeypatch.setattr("src.utils.images.get_storage", lambda: fake)
    monkeypatch.setattr(
        "src.utils.images._preview_payloads", lambda _content, _suffix: []
    )

    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "")
    url_empty = _store_product_bytes("persist-uuid.jpg", b"jpeg", "image/jpeg")
    assert url_empty == f"{MEDIA_URL_PREFIX}/persist-uuid.jpg"
    assert fake.last_key == "products/persist-uuid.jpg"

    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://cdn.shopstore.example")
    url_cdn = _store_product_bytes("persist-uuid.jpg", b"jpeg", "image/jpeg")
    assert url_cdn == f"{MEDIA_URL_PREFIX}/persist-uuid.jpg"
    assert not url_cdn.startswith("https://")
