from __future__ import annotations

import contextlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.config import settings
from src.models.product import Product, ProductImage
from src.schemas.catalog_import import ProductImport, ProductImportImage
from src.services.catalog.importing import helpers as imp
from src.services.catalog.importing.enrichment_writer import (
    UpdateFlags,
    apply_existing_product_update,
    compute_update_flags,
)
from src.utils.images import MEDIA_URL_PREFIX, resolve_product_cover_url

# Production-shaped URLs from local smoke (no production DB ids).
BROKEN_COVER_SHORTS = (
    "https://www.supplier-demo.com/cdn/shop/files/0204760655700000.jpg"
    "?v=1781565182&width=1946"
)
MALFORMED_DOM_COVER = (
    "https://www.supplier-demo.com/\\/\\/www.supplier-demo.com/cdn/shop/files/"
    "0204760655700000_dbf7e69f-b20d-416a-a987-7b5604347c17.jpg?v=1787185519"
)
LIVE_SHOPIFY_SHORTS = (
    "https://cdn.shopify.com/s/files/1/0638/1885/8538/files/"
    "0204760655700000_dbf7e69f-b20d-416a-a987-7b5604347c17.jpg?v=1787185519"
)
BROKEN_COVER_RACKET = (
    "https://www.supplier-demo.com/cdn/shop/files/0070760427400000.jpg"
    "?v=1776191782&width=1946"
)
LIVE_SHOPIFY_RACKET = (
    "https://cdn.shopify.com/s/files/1/0638/1885/8538/files/"
    "0070760427400000_ff66c4d6-f0f2-44d3-8e4d-afb8abf614db.jpg?v=1787639874"
)


@pytest.fixture
def local_media(tmp_path, monkeypatch):
    root = tmp_path / "products"
    root.mkdir()
    prefix = "/media/products"
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(root))
    monkeypatch.setattr("src.utils.images.MEDIA_ROOT", root)
    monkeypatch.setattr("src.utils.images.MEDIA_URL_PREFIX", prefix)

    def make_local(name: str, content: bytes = b"jpeg-bytes") -> str:
        (root / name).write_bytes(content)
        return f"{prefix}/{name}"

    return make_local


def _product(**fields) -> Product:
    product = Product(
        title="Smoke SKU",
        brand="Brand",
        sale_price=Decimal("49.95"),
        regular_price=Decimal("59.95"),
        supplier_price_eur=Decimal("49.95"),
        stock=3,
        product_url="https://www.supplier-demo.com/products/smoke-sku",
        external_id="smoke-ext-001",
        image_url=BROKEN_COVER_SHORTS,
    )
    for key, value in fields.items():
        setattr(product, key, value)
    return product


def _flags_kwargs(existing: Product, **overrides):
    base = {
        "existing": existing,
        "sale_price": Decimal(existing.supplier_price_eur or 0),
        "regular_price": Decimal(existing.regular_price or 0),
        "stock": int(existing.stock or 0),
        "incoming_variant_signature": (),
        "current_variant_signature": (),
        "incoming_gallery_layout": ((None, 0),),
        "current_gallery_layout": ((None, 0),),
        "incoming_gallery_url_signature": (
            imp.build_supplier_gallery_url_signature(
                [ProductImportImage(url=LIVE_SHOPIFY_SHORTS)]
            )
        ),
        "current_gallery_url_signature": (
            imp.build_supplier_gallery_url_signature(
                [ProductImportImage(url=BROKEN_COVER_SHORTS)]
            )
        ),
        "incoming_feature_signature": (),
        "current_feature_signature": (),
        "incoming_description": None,
        "is_dom_full": False,
        "is_dom_import": False,
        "incoming_has_features": False,
        "catalog": {
            "category_l1": existing.category_l1,
            "category_l2": existing.category_l2,
            "category_l3": existing.category_l3,
            "gender": existing.gender,
        },
        "category_l2": existing.category_l2,
        "sport_type": existing.sport_type,
        "trade_group": existing.trade_group,
        "write_categories": False,
        "is_graphql_base": True,
    }
    base.update(overrides)
    return base


def _graphql_flags(
    existing: Product,
    incoming_gallery: list[ProductImportImage],
    **overrides,
):
    layout = imp.build_gallery_layout_signature(incoming_gallery)
    return _flags_kwargs(
        existing,
        incoming_gallery_layout=layout,
        current_gallery_layout=imp.current_gallery_layout_signature(existing),
        incoming_gallery_url_signature=imp.build_supplier_gallery_url_signature(
            incoming_gallery
        ),
        current_gallery_url_signature=imp.current_supplier_gallery_url_signature(
            existing, incoming_gallery
        ),
        **overrides,
    )


def test_sync_product_cover_skips_broken_pos0(local_media) -> None:
    valid_local = local_media("valid-cover.jpg")
    product = _product()
    product.images = [
        ProductImage(url=MALFORMED_DOM_COVER, position=0),
        ProductImage(url=BROKEN_COVER_SHORTS, position=1),
        ProductImage(url=valid_local, position=2),
    ]
    imp.sync_product_cover_from_gallery(product)
    assert product.image_url == valid_local


def test_sync_product_cover_prefers_existing_local(local_media) -> None:
    local_cover = local_media("preferred.jpg")
    product = _product()
    product.images = [
        ProductImage(url=LIVE_SHOPIFY_SHORTS, position=0),
        ProductImage(url=local_cover, position=1),
    ]
    imp.sync_product_cover_from_gallery(product)
    assert product.image_url == local_cover


def test_graphql_gallery_change_refreshes_media() -> None:
    existing = _product()
    existing.images = [
        ProductImage(url=BROKEN_COVER_SHORTS, position=0),
    ]
    incoming = [ProductImportImage(url=LIVE_SHOPIFY_SHORTS)]
    flags = compute_update_flags(**_graphql_flags(existing, incoming))
    assert flags.refresh_media is True
    assert flags.has_changes is True


def test_graphql_gallery_unchanged_does_not_refresh_media() -> None:
    existing = _product(stock=3)
    incoming = [ProductImportImage(url=LIVE_SHOPIFY_SHORTS)]
    existing.images = [ProductImage(url=LIVE_SHOPIFY_SHORTS, position=0)]
    flags = compute_update_flags(**_graphql_flags(existing, incoming, stock=7))
    assert flags.refresh_media is False
    assert flags.has_changes is True


def test_graphql_identical_second_import_no_media_refresh(local_media) -> None:
    local_cover = local_media("repaired-cover.jpg")
    incoming = [
        ProductImportImage(url=LIVE_SHOPIFY_SHORTS),
        ProductImportImage(url=LIVE_SHOPIFY_RACKET),
    ]
    existing = _product()
    existing.images = [
        ProductImage(url=local_cover, position=0),
        ProductImage(url=local_media("gallery-2.jpg"), position=1),
    ]
    flags = compute_update_flags(**_graphql_flags(existing, incoming))
    assert flags.refresh_media is False
    assert flags.has_changes is False


def test_graphql_stock_only_update_does_not_refresh_media(local_media) -> None:
    local_cover = local_media("stock-cover.jpg")
    incoming = [ProductImportImage(url=LIVE_SHOPIFY_SHORTS)]
    existing = _product(stock=4)
    existing.images = [ProductImage(url=local_cover, position=0)]
    flags = compute_update_flags(**_graphql_flags(existing, incoming, stock=9))
    assert flags.refresh_media is False
    assert flags.has_changes is True


def test_graphql_supplier_gallery_changed_refreshes_media() -> None:
    old_shopify = (
        "https://cdn.shopify.com/s/files/1/0638/1885/8538/files/"
        "old-image-a1111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jpg?v=1"
    )
    new_shopify = (
        "https://cdn.shopify.com/s/files/1/0638/1885/8538/files/"
        "new-image-b2222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb.jpg?v=1"
    )
    existing = _product()
    existing.images = [ProductImage(url=old_shopify, position=0)]
    incoming = [ProductImportImage(url=new_shopify)]
    flags = compute_update_flags(**_graphql_flags(existing, incoming))
    assert flags.refresh_media is True


def test_supplier_signature_local_matches_incoming_shopify(local_media) -> None:
    local_cover = local_media("canonical-cover.jpg")
    incoming = [ProductImportImage(url=LIVE_SHOPIFY_SHORTS)]
    existing = _product()
    existing.images = [ProductImage(url=local_cover, position=0)]
    incoming_sig = imp.build_supplier_gallery_url_signature(incoming)
    current_sig = imp.current_supplier_gallery_url_signature(existing, incoming)
    assert incoming_sig == current_sig
    assert incoming_sig[0].startswith("files/")


@pytest.mark.asyncio
async def test_graphql_refresh_downloads_images(local_media, monkeypatch) -> None:
    local_path = local_media("downloaded.jpg")

    async def fake_save(url: str) -> str:
        return local_path if url == LIVE_SHOPIFY_SHORTS else None

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        fake_save,
    )

    existing = _product()
    existing.images = [ProductImage(url=BROKEN_COVER_SHORTS, position=0)]
    product = ProductImport(
        title=existing.title,
        brand=existing.brand,
        product_url=existing.product_url,
        import_source="graphql_base",
        media_gallery=[ProductImportImage(url=LIVE_SHOPIFY_SHORTS)],
        image_url=LIVE_SHOPIFY_SHORTS,
        stock=existing.stock,
    )
    flags = UpdateFlags(
        has_changes=True,
        refresh_media=True,
        features_changed=False,
        write_categories=False,
    )
    session = MagicMock()
    session.no_autoflush = contextlib.nullcontext()
    session.flush = AsyncMock()
    downloaded_cache: dict[str, str | None] = {}

    await apply_existing_product_update(
        existing,
        product,
        flags=flags,
        sale_price=existing.supplier_price_eur,
        regular_price=existing.regular_price,
        stock=int(existing.stock or 0),
        external_id=existing.external_id,
        image_url=None,
        product_url=product.product_url,
        catalog={
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "gender": None,
        },
        category_l2=None,
        sport_type=None,
        trade_group=None,
        pricing_category_key=None,
        eur_rate=Decimal("1"),
        is_graphql_base=True,
        is_dom_full=False,
        is_dom_import=False,
        translation_map={},
        variants_payload=[],
        selected_variant=None,
        media_gallery=product.media_gallery,
        features=[],
        download_images=True,
        downloaded_cache=downloaded_cache,
        session=session,
        apply_description=MagicMock(),
        attach_images=imp.attach_images,
        attach_features=imp.attach_features,
        upsert_variants=MagicMock(),
        apply_pricing=AsyncMock(),
    )

    assert len(existing.images) == 1
    assert existing.images[0].url == local_path
    assert existing.image_url == local_path
    assert existing.image_url.startswith(f"{MEDIA_URL_PREFIX}/")


@pytest.mark.asyncio
async def test_graphql_refresh_without_download_uses_current_remote_gallery() -> None:
    existing = _product()
    existing.images = [ProductImage(url=BROKEN_COVER_SHORTS, position=0)]
    product = ProductImport(
        title=existing.title,
        brand=existing.brand,
        product_url=existing.product_url,
        import_source="graphql_base",
        media_gallery=[ProductImportImage(url=LIVE_SHOPIFY_SHORTS)],
        image_url=LIVE_SHOPIFY_SHORTS,
    )
    flags = UpdateFlags(
        has_changes=True,
        refresh_media=True,
        features_changed=False,
        write_categories=False,
    )
    session = MagicMock()
    session.no_autoflush = contextlib.nullcontext()
    session.flush = AsyncMock()

    await apply_existing_product_update(
        existing,
        product,
        flags=flags,
        sale_price=existing.supplier_price_eur,
        regular_price=existing.regular_price,
        stock=int(existing.stock or 0),
        external_id=existing.external_id,
        image_url=None,
        product_url=product.product_url,
        catalog={
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "gender": None,
        },
        category_l2=None,
        sport_type=None,
        trade_group=None,
        pricing_category_key=None,
        eur_rate=Decimal("1"),
        is_graphql_base=True,
        is_dom_full=False,
        is_dom_import=False,
        translation_map={},
        variants_payload=[],
        selected_variant=None,
        media_gallery=product.media_gallery,
        features=[],
        download_images=False,
        downloaded_cache={},
        session=session,
        apply_description=MagicMock(),
        attach_images=imp.attach_images,
        attach_features=imp.attach_features,
        upsert_variants=MagicMock(),
        apply_pricing=AsyncMock(),
    )

    assert existing.image_url is None
    assert existing.images[0].source_url == LIVE_SHOPIFY_SHORTS
    assert existing.images[0].url is None


def test_graphql_cover_does_not_use_old_position_zero(local_media) -> None:
    product = _product(image_url=BROKEN_COVER_RACKET)
    product.images = [
        ProductImage(url=MALFORMED_DOM_COVER, position=0),
        ProductImage(url=LIVE_SHOPIFY_RACKET, position=1),
    ]
    imp.sync_product_cover_from_gallery(product)
    assert product.image_url is None
    assert (
        resolve_product_cover_url(product.image_url, product.images)
        == LIVE_SHOPIFY_RACKET
    )


@pytest.mark.parametrize(
    ("broken_cover", "live_gallery"),
    [
        (BROKEN_COVER_SHORTS, LIVE_SHOPIFY_SHORTS),
        (BROKEN_COVER_RACKET, LIVE_SHOPIFY_RACKET),
    ],
)
@pytest.mark.asyncio
async def test_smoke_shaped_graphql_refresh_replaces_broken_cover(
    local_media,
    monkeypatch,
    broken_cover: str,
    live_gallery: str,
) -> None:
    local_path = local_media("smoke-cover.jpg")

    async def fake_save(url: str) -> str:
        return local_path if url == live_gallery else None

    monkeypatch.setattr(
        "src.services.catalog.importing.helpers.save_image_from_url",
        fake_save,
    )

    existing = _product(image_url=broken_cover)
    existing.images = [ProductImage(url=broken_cover, position=0)]
    product = ProductImport(
        title=existing.title,
        brand=existing.brand,
        product_url=existing.product_url,
        import_source="graphql_base",
        media_gallery=[ProductImportImage(url=live_gallery)],
        image_url=live_gallery,
    )
    flags = UpdateFlags(
        has_changes=True,
        refresh_media=True,
        features_changed=False,
        write_categories=False,
    )
    session = MagicMock()
    session.no_autoflush = contextlib.nullcontext()
    session.flush = AsyncMock()
    downloaded_cache: dict[str, str | None] = {}

    await apply_existing_product_update(
        existing,
        product,
        flags=flags,
        sale_price=existing.supplier_price_eur,
        regular_price=existing.regular_price,
        stock=int(existing.stock or 0),
        external_id=existing.external_id,
        image_url=None,
        product_url=product.product_url,
        catalog={
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "gender": None,
        },
        category_l2=None,
        sport_type=None,
        trade_group=None,
        pricing_category_key=None,
        eur_rate=Decimal("1"),
        is_graphql_base=True,
        is_dom_full=False,
        is_dom_import=False,
        translation_map={},
        variants_payload=[],
        selected_variant=None,
        media_gallery=product.media_gallery,
        features=[],
        download_images=True,
        downloaded_cache=downloaded_cache,
        session=session,
        apply_description=MagicMock(),
        attach_images=imp.attach_images,
        attach_features=imp.attach_features,
        upsert_variants=MagicMock(),
        apply_pricing=AsyncMock(),
    )

    assert existing.image_url != broken_cover
    assert existing.image_url == local_path
    assert existing.image_url.startswith(f"{MEDIA_URL_PREFIX}/")


@pytest.mark.asyncio
async def test_graphql_gallery_change_calls_attach_images() -> None:
    existing = _product()
    existing.images = [ProductImage(url=BROKEN_COVER_SHORTS, position=0)]
    product = ProductImport(
        title=existing.title,
        brand=existing.brand,
        product_url=existing.product_url,
        import_source="graphql_base",
        media_gallery=[ProductImportImage(url=LIVE_SHOPIFY_SHORTS)],
    )
    attach_mock = AsyncMock()
    flags = UpdateFlags(
        has_changes=True,
        refresh_media=True,
        features_changed=False,
        write_categories=False,
    )
    session = MagicMock()
    session.no_autoflush = contextlib.nullcontext()
    session.flush = AsyncMock()

    await apply_existing_product_update(
        existing,
        product,
        flags=flags,
        sale_price=existing.supplier_price_eur,
        regular_price=existing.regular_price,
        stock=int(existing.stock or 0),
        external_id=existing.external_id,
        image_url=None,
        product_url=product.product_url,
        catalog={
            "category_l1": None,
            "category_l2": None,
            "category_l3": None,
            "gender": None,
        },
        category_l2=None,
        sport_type=None,
        trade_group=None,
        pricing_category_key=None,
        eur_rate=Decimal("1"),
        is_graphql_base=True,
        is_dom_full=False,
        is_dom_import=False,
        translation_map={},
        variants_payload=[],
        selected_variant=None,
        media_gallery=product.media_gallery,
        features=[],
        download_images=False,
        downloaded_cache={},
        session=session,
        apply_description=MagicMock(),
        attach_images=attach_mock,
        attach_features=imp.attach_features,
        upsert_variants=MagicMock(),
        apply_pricing=AsyncMock(),
    )

    attach_mock.assert_awaited_once()
    assert existing.images == []
