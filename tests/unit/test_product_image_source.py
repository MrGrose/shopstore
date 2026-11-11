from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.models.product import Product, ProductImage
from src.schemas.catalog_import import ProductImportImage
from src.schemas.product import ProductImageSchema
from src.services.catalog.importing.helpers import (
    attach_images,
    build_supplier_gallery_url_signature,
    current_supplier_gallery_url_signature,
    gallery_asset_dedupe_key,
    resolve_image_url,
    sync_product_cover_from_gallery,
)
from src.utils.images import resolve_product_cover_url, resolve_stored_product_image

CDN = "https://cdn.shopify.com/s/files/1/p.jpg"
TP_BASE = (
    "https://www.supplier-demo.com/cdn/shop/files/3904680048400000.jpg?v=1774934021"
)
TP_WIDTH = (
    "https://www.supplier-demo.com/cdn/shop/files/3904680048400000.jpg"
    "?v=1774934021&width=1946"
)

SUPPLIER_FILE = "https://supplier.example/cdn/shop/files/file.jpg"
SUPPLIER_FILE_V = "https://supplier.example/cdn/shop/files/file.jpg?v=123"
SUPPLIER_FILE_W = "https://supplier.example/cdn/shop/files/file.jpg?width=1946"
SUPPLIER_FILE_VW = "https://supplier.example/cdn/shop/files/file.jpg?v=123&width=1946"
SUPPLIER_ANOTHER = "https://supplier.example/cdn/shop/files/another.jpg"
SUPPLIER_FILE_A = "https://supplier.example/cdn/shop/files/file-a.jpg"
SUPPLIER_FILE_B = "https://supplier.example/cdn/shop/files/file-b.jpg"
SUPPLIER_SAME_NAME_OTHER_HOST = "https://other.example/assets/files/file.jpg?v=1"

TP_OTHER = (
    "https://www.supplier-demo.com/cdn/shop/files/3904680048400000_2.jpg?v=1774934021"
)


# Минимальный Product для тестов галереи.
def _product() -> Product:
    product = Product(
        title="Smoke SKU",
        brand="Brand",
        sale_price=Decimal("49.95"),
        regular_price=Decimal("59.95"),
        supplier_price_eur=Decimal("49.95"),
        stock=3,
        product_url="https://www.supplier-demo.com/products/smoke-sku",
        external_id="smoke-ext-001",
        image_url=None,
    )
    product.images = []
    return product


# S3 primary, CDN fallback, neither → empty.
def test_resolve_stored_product_image_priority() -> None:
    managed = "/media/products/abc.jpg"
    assert resolve_stored_product_image(managed, CDN) == (managed, CDN)
    assert resolve_stored_product_image(None, CDN) == (CDN, None)
    assert resolve_stored_product_image(CDN, None) == (CDN, None)
    assert resolve_stored_product_image(None, None) == (None, None)
    assert resolve_stored_product_image(managed, None) == (managed, None)


# Cover: managed gallery beats legacy CDN cover column.
def test_resolve_product_cover_url_prefers_managed() -> None:
    images = [
        SimpleNamespace(url=None, source_url=CDN, position=0),
        SimpleNamespace(
            url="/media/products/abc.jpg",
            source_url="https://cdn.shopify.com/s/files/1/b.jpg",
            position=1,
        ),
    ]
    assert (
        resolve_product_cover_url(
            "https://cdn.shopify.com/s/files/1/legacy.jpg", images
        )
        == "/media/products/abc.jpg"
    )


# Cover: CDN-only gallery, no managed URL.
def test_resolve_product_cover_url_cdn_only() -> None:
    images = [
        SimpleNamespace(
            url=None,
            source_url="https://www.supplier-demo.com/files/p.jpg",
            position=0,
        )
    ]
    assert (
        resolve_product_cover_url(None, images)
        == "https://www.supplier-demo.com/files/p.jpg"
    )


# Cover: no image.
def test_resolve_product_cover_url_empty() -> None:
    assert resolve_product_cover_url(None, []) is None


# Download off: source kept, managed empty.
@pytest.mark.asyncio
async def test_attach_images_download_off_keeps_source(monkeypatch) -> None:
    async def _fail_save(_url: str) -> str | None:
        raise AssertionError("download must not run")

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _fail_save,
    )
    product = _product()
    await attach_images(
        product,
        [ProductImportImage(url=CDN, alt="a")],
        False,
        {},
    )
    assert len(product.images) == 1
    assert product.images[0].source_url == CDN
    assert product.images[0].url is None
    sync_product_cover_from_gallery(product)
    assert product.image_url is None


# Download on: source + managed.
@pytest.mark.asyncio
async def test_attach_images_download_on_keeps_source(monkeypatch) -> None:
    async def _save(_url: str) -> str:
        return "/media/products/abc.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    await attach_images(
        product,
        [ProductImportImage(url=CDN, alt="a")],
        True,
        {},
    )
    assert product.images[0].source_url == CDN
    assert product.images[0].url == "/media/products/abc.jpg"
    sync_product_cover_from_gallery(product)
    assert product.image_url == "/media/products/abc.jpg"


# Download fail: source kept, managed empty.
@pytest.mark.asyncio
async def test_attach_images_download_fail_keeps_source(monkeypatch) -> None:
    async def _save(_url: str) -> None:
        return None

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    cache: dict[str, str | None] = {}
    await attach_images(
        product,
        [ProductImportImage(url=CDN, alt="a")],
        True,
        cache,
    )
    assert cache[CDN] is None
    assert product.images[0].source_url == CDN
    assert product.images[0].url is None
    sync_product_cover_from_gallery(product)
    assert product.image_url is None


# resolve_image_url больше не возвращает CDN.
@pytest.mark.asyncio
async def test_resolve_image_url_download_off_returns_none() -> None:
    assert await resolve_image_url(CDN, False, {}) is None


# Repeat scrape: source_url identity, без exists().
def test_supplier_signature_uses_source_url() -> None:
    cdn = "https://cdn.shopify.com/s/files/1/abc/p.jpg?width=100"
    incoming = [ProductImportImage(url=cdn, alt="")]
    product = _product()
    product.images = [
        ProductImage(
            url="/media/products/abc.jpg",
            source_url=cdn,
            position=0,
        )
    ]
    assert build_supplier_gallery_url_signature(incoming) == (
        current_supplier_gallery_url_signature(product, incoming)
    )


# Long CDN URL помещается в source_url, не в cover.
def test_long_cdn_stays_on_source_url() -> None:
    cdn = "https://cdn.shopify.com/s/files/" + ("a" * 400) + "/p.jpg"
    assert len(cdn) > 255
    primary, fallback = resolve_stored_product_image("/media/products/x.jpg", cdn)
    assert primary == "/media/products/x.jpg"
    assert fallback == cdn


# API schema отдаёт managed url и CDN fallback, без source_url.
def test_product_image_schema_resolves_display_urls() -> None:
    row = ProductImage(
        id=7,
        url="/media/products/abc.jpg",
        source_url=CDN,
        alt="a",
        position=0,
    )
    schema = ProductImageSchema.model_validate(row)
    assert schema.url == "/media/products/abc.jpg"
    assert schema.fallback_url == CDN
    assert not hasattr(schema, "source_url") or "source_url" not in schema.model_dump()


# Пустая gallery row не даёт display URL.
def test_product_image_schema_blank_without_urls() -> None:
    row = ProductImage(id=8, url=None, source_url=None, alt=None, position=1)
    schema = ProductImageSchema.model_validate(row)
    assert schema.url == ""
    assert schema.fallback_url is None


def test_gallery_asset_dedupe_key_treats_query_variants_as_one_asset() -> None:
    assert gallery_asset_dedupe_key(TP_BASE) == gallery_asset_dedupe_key(TP_WIDTH)
    assert gallery_asset_dedupe_key(TP_BASE) != gallery_asset_dedupe_key(TP_OTHER)


@pytest.mark.asyncio
async def test_attach_images_exact_same_url_deduped(monkeypatch) -> None:
    calls: list[str] = []

    async def _save(url: str) -> str:
        calls.append(url)
        return "/media/products/one.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    await attach_images(
        product,
        [
            ProductImportImage(url=TP_BASE, alt="a"),
            ProductImportImage(url=TP_BASE, alt="b"),
        ],
        True,
        {},
    )
    assert len(product.images) == 1
    assert product.images[0].source_url == TP_BASE
    assert calls == [TP_BASE]


@pytest.mark.asyncio
async def test_attach_images_query_variants_deduped(monkeypatch) -> None:
    calls: list[str] = []

    async def _save(url: str) -> str:
        calls.append(url)
        return "/media/products/one.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    await attach_images(
        product,
        [
            ProductImportImage(url=TP_BASE, alt="base"),
            ProductImportImage(url=TP_WIDTH, alt="width"),
        ],
        True,
        {},
    )
    assert len(product.images) == 1
    assert product.images[0].source_url == TP_BASE
    assert calls == [TP_BASE]


@pytest.mark.asyncio
async def test_attach_images_distinct_assets_kept(monkeypatch) -> None:
    calls: list[str] = []

    async def _save(url: str) -> str:
        calls.append(url)
        return f"/media/products/{len(calls)}.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    await attach_images(
        product,
        [
            ProductImportImage(url=TP_BASE, alt="a"),
            ProductImportImage(url=TP_OTHER, alt="b"),
        ],
        True,
        {},
    )
    assert len(product.images) == 2
    assert [img.position for img in product.images] == [0, 1]
    assert calls == [TP_BASE, TP_OTHER]


@pytest.mark.asyncio
async def test_attach_images_preserves_order_when_skipping_duplicates(
    monkeypatch,
) -> None:
    async def _save(url: str) -> str:
        return f"/media/products/{url.rsplit('/', 1)[-1][:8]}.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    await attach_images(
        product,
        [
            ProductImportImage(url=TP_BASE, alt="first"),
            ProductImportImage(url=TP_OTHER, alt="second"),
            ProductImportImage(url=TP_WIDTH, alt="dup"),
        ],
        True,
        {},
    )
    assert len(product.images) == 2
    assert product.images[0].source_url == TP_BASE
    assert product.images[1].source_url == TP_OTHER
    assert [img.position for img in product.images] == [0, 1]


@pytest.mark.asyncio
async def test_attach_images_download_off_dedupes_source_only_rows(monkeypatch) -> None:
    async def _fail_save(_url: str) -> str | None:
        raise AssertionError("download must not run")

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _fail_save,
    )
    product = _product()
    await attach_images(
        product,
        [
            ProductImportImage(url=TP_BASE, alt="a"),
            ProductImportImage(url=TP_WIDTH, alt="b"),
        ],
        False,
        {},
    )
    assert len(product.images) == 1
    assert product.images[0].source_url == TP_BASE
    assert product.images[0].url is None


@pytest.mark.asyncio
async def test_resolve_image_url_reuses_canonical_cache_entry(monkeypatch) -> None:
    calls: list[str] = []

    async def _save(url: str) -> str:
        calls.append(url)
        return "/media/products/cached.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    cache: dict[str, str | None] = {}
    first = await resolve_image_url(TP_BASE, True, cache)
    second = await resolve_image_url(TP_WIDTH, True, cache)
    assert first == "/media/products/cached.jpg"
    assert second == "/media/products/cached.jpg"
    assert calls == [TP_BASE]
    assert cache[TP_WIDTH] == "/media/products/cached.jpg"


def test_gallery_asset_dedupe_key_four_query_variants_share_one_key() -> None:
    keys = {
        gallery_asset_dedupe_key(url)
        for url in (
            SUPPLIER_FILE,
            SUPPLIER_FILE_V,
            SUPPLIER_FILE_W,
            SUPPLIER_FILE_VW,
        )
    }
    assert len(keys) == 1
    assert keys.pop() == gallery_asset_dedupe_key(SUPPLIER_FILE)


def test_gallery_asset_dedupe_key_different_filenames_differ() -> None:
    assert gallery_asset_dedupe_key(SUPPLIER_FILE_A) != gallery_asset_dedupe_key(
        SUPPLIER_FILE_B
    )


def test_gallery_asset_dedupe_key_local_urls_require_exact_match() -> None:
    local_a = "/media/products/aaa.jpg"
    local_b = "/media/products/bbb.jpg"
    assert gallery_asset_dedupe_key(local_a) == f"local:{local_a}"
    assert gallery_asset_dedupe_key(local_a) != gallery_asset_dedupe_key(local_b)


def test_gallery_asset_dedupe_key_non_http_not_deduped() -> None:
    assert gallery_asset_dedupe_key("relative/path.jpg") is None
    assert gallery_asset_dedupe_key("") is None


def test_gallery_asset_dedupe_key_same_filename_different_hosts_uses_canonical() -> (
    None
):
    # Existing canonical_supplier_gallery_url keys by files/... path only.
    assert gallery_asset_dedupe_key(SUPPLIER_FILE) == gallery_asset_dedupe_key(
        SUPPLIER_SAME_NAME_OTHER_HOST
    )


@pytest.mark.asyncio
async def test_attach_images_scraper_gallery_simulation_two_images(
    monkeypatch,
) -> None:
    download_calls: list[str] = []
    issued_urls: list[str] = []

    async def _save(url: str) -> str:
        download_calls.append(url)
        managed = f"/media/products/uuid-{len(issued_urls) + 1}.jpg"
        issued_urls.append(managed)
        return managed

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    gallery = [
        ProductImportImage(url=SUPPLIER_FILE, alt="base"),
        ProductImportImage(url=SUPPLIER_FILE_V, alt="v"),
        ProductImportImage(url=SUPPLIER_FILE_W, alt="w"),
        ProductImportImage(url=SUPPLIER_FILE_VW, alt="vw"),
        ProductImportImage(url=SUPPLIER_ANOTHER, alt="other"),
    ]
    await attach_images(product, gallery, True, {})
    assert len(product.images) == 2
    assert product.images[0].source_url == SUPPLIER_FILE
    assert product.images[0].position == 0
    assert product.images[1].source_url == SUPPLIER_ANOTHER
    assert product.images[1].position == 1
    assert download_calls == [SUPPLIER_FILE, SUPPLIER_ANOTHER]
    assert len({img.url for img in product.images}) == 2


@pytest.mark.asyncio
async def test_attach_images_download_off_four_item_gallery_two_rows(
    monkeypatch,
) -> None:
    async def _fail_save(_url: str) -> str | None:
        raise AssertionError("download must not run")

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _fail_save,
    )
    product = _product()
    gallery = [
        ProductImportImage(url=SUPPLIER_FILE, alt="base"),
        ProductImportImage(url=SUPPLIER_FILE_V, alt="v"),
        ProductImportImage(url=SUPPLIER_FILE_W, alt="w"),
        ProductImportImage(url=SUPPLIER_ANOTHER, alt="other"),
    ]
    await attach_images(product, gallery, False, {})
    assert len(product.images) == 2
    assert product.images[0].source_url == SUPPLIER_FILE
    assert product.images[1].source_url == SUPPLIER_ANOTHER
    assert all(img.url is None for img in product.images)


@pytest.mark.asyncio
async def test_attach_images_import_pipeline_reuses_cache_without_second_download(
    monkeypatch,
) -> None:
    download_calls: list[str] = []

    async def _save(url: str) -> str:
        download_calls.append(url)
        return "/media/products/from-pipeline.jpg"

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        _save,
    )
    product = _product()
    downloaded_cache: dict[str, str | None] = {}
    gallery = [
        ProductImportImage(url=TP_BASE, alt="gallery-0"),
        ProductImportImage(url=TP_WIDTH, alt="gallery-dup"),
        ProductImportImage(url=TP_OTHER, alt="gallery-1"),
    ]
    await attach_images(product, gallery, True, downloaded_cache)
    cover = await resolve_image_url(TP_WIDTH, True, downloaded_cache)
    assert len(product.images) == 2
    assert download_calls == [TP_BASE, TP_OTHER]
    assert cover == "/media/products/from-pipeline.jpg"
    assert TP_WIDTH in downloaded_cache
