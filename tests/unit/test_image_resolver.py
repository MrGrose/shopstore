from io import BytesIO
from pathlib import Path

from PIL import Image

from src.storage.local import LocalStorage
from src.utils.images import (
    IMAGE_VARIANT_ORIGINAL,
    ensure_product_preview_variants,
    is_product_original_filename,
    resolve_product_image_url,
)


# Квадратный JPEG в памяти.
def _jpeg_bytes(size: int = 800) -> bytes:
    image = Image.new("RGB", (size, size), (12, 80, 160))
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def test_is_product_original_filename() -> None:
    assert is_product_original_filename("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg")
    assert not is_product_original_filename(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg"
    )
    assert not is_product_original_filename(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_w160.jpg"
    )
    assert not is_product_original_filename("readme.txt")


def test_resolve_original_and_variants() -> None:
    url = "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg"
    assert resolve_product_image_url(url, IMAGE_VARIANT_ORIGINAL) == url
    assert (
        resolve_product_image_url(url, 300)
        == "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg"
    )
    assert (
        resolve_product_image_url(url, "600")
        == "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_600.jpg"
    )
    assert (
        resolve_product_image_url(url, 900)
        == "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_900.jpg"
    )


def test_resolve_from_existing_variant_filename() -> None:
    url = "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_600.jpg"
    assert (
        resolve_product_image_url(url, "original")
        == "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg"
    )
    assert (
        resolve_product_image_url(url, 300)
        == "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg"
    )


def test_resolve_missing_and_unsupported_variant_falls_back_to_original() -> None:
    url = "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg"
    assert resolve_product_image_url(url, 1200) == url
    assert resolve_product_image_url(url, "hero") == url


def test_resolve_remote_url_unchanged() -> None:
    remote = "https://cdn.example/p.jpg"
    assert resolve_product_image_url(remote, 300) == remote
    shopify = "https://cdn.shopify.com/s/files/1/x.jpg"
    assert resolve_product_image_url(shopify, 600) == shopify


def test_resolve_malformed_and_empty() -> None:
    assert resolve_product_image_url(None, 300) is None
    assert resolve_product_image_url("  ", 300) is None
    assert resolve_product_image_url("not-a-url", 300) == "not-a-url"


def test_resolve_absolute_local_media_keeps_origin() -> None:
    url = (
        "http://127.0.0.1:8001/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg"
    )
    assert resolve_product_image_url(url, 300) == (
        "http://127.0.0.1:8001/media/products/"
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg"
    )


def test_ensure_preview_variants_skips_existing(tmp_path: Path) -> None:
    storage = LocalStorage(root=tmp_path)
    key = "products/hero.jpg"
    storage.put(key, _jpeg_bytes(), "image/jpeg")
    dry = ensure_product_preview_variants(storage, key, apply=False)
    assert dry["missing"] == 3
    assert dry["created"] == 0
    assert not storage.exists("products/hero_300.jpg")
    created = ensure_product_preview_variants(storage, key, apply=True)
    assert created["created"] == 3
    assert storage.exists("products/hero_300.jpg")
    original = storage.read(key)
    again = ensure_product_preview_variants(storage, key, apply=True)
    assert again["already_exists"] == 3
    assert again["created"] == 0
    assert storage.read(key) == original
