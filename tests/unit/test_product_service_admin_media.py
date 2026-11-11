from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.product import Product, ProductImage
from src.schemas.product import ProductUpdate
from src.services.product_service import ProductService


def test_normalize_admin_gallery_urls_dedupes_and_skips_empty() -> None:
    urls = ["https://a.example/img.jpg", "https://a.example/img.jpg", "  ", "https://b"]
    assert ProductService._normalize_admin_gallery_urls(urls) == [
        "https://a.example/img.jpg",
        "https://b",
    ]


def test_replace_admin_gallery_replaces_positions() -> None:
    product = Product(
        id=1,
        title="Test",
        brand="Brand",
        product_url="https://shop.example/p",
        sale_price=100,
        regular_price=100,
        stock=1,
        is_active=True,
    )
    product.images = [
        ProductImage(id=10, product_id=1, url="https://old/1.jpg", position=0),
        ProductImage(id=11, product_id=1, url="https://old/2.jpg", position=1),
    ]

    ProductService._replace_admin_gallery(
        product,
        ["https://new/cover.jpg", "https://new/2.jpg"],
    )

    assert len(product.images) == 2
    assert [image.url for image in product.images] == [
        "https://new/cover.jpg",
        "https://new/2.jpg",
    ]
    assert [image.position for image in product.images] == [0, 1]


@pytest.mark.asyncio
async def test_update_product_replaces_gallery_and_cover(monkeypatch) -> None:
    product = Product(
        id=7,
        title="Test",
        brand="Brand",
        product_url="https://shop.example/p",
        sale_price=100,
        regular_price=100,
        stock=1,
        is_active=True,
        image_url="https://old/cover.jpg",
    )
    product.images = [
        ProductImage(id=1, product_id=7, url="https://old/gallery.jpg", position=0),
    ]

    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = ProductService(session)
    service.product_crud = AsyncMock()
    service.product_crud.get_by_id_with_related = AsyncMock(return_value=product)
    service.pricing_service = MagicMock()

    stock_service = MagicMock()
    stock_service.refresh_products = AsyncMock()
    monkeypatch.setattr(
        "src.services.product_service.CatalogStockService",
        lambda _session: stock_service,
    )
    monkeypatch.setattr(
        "src.services.product_service.invalidate_catalog_read_caches",
        lambda reason: None,
    )

    await service.update_product(
        7,
        ProductUpdate(image_url="https://new/cover.jpg"),
        gallery_urls=["https://new/gallery.jpg", "https://new/extra.jpg"],
    )

    assert product.image_url == "https://new/cover.jpg"
    assert [image.url for image in product.images] == [
        "https://new/gallery.jpg",
        "https://new/extra.jpg",
    ]
    session.commit.assert_awaited()
    stock_service.refresh_products.assert_awaited_once_with([7])
