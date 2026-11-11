from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from src.core.config import settings
from src.repositories.session import async_engine, async_session_maker
from src.schemas.product import PUBLIC_CARD_GALLERY_LIMIT, ProductPublicCardSchema
from src.services.catalog import CatalogService


def _card_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 1,
        "title": "Racket",
        "brand": "Babolat",
        "sale_price": Decimal("10000"),
        "regular_price": Decimal("12000"),
        "product_url": "/p/1",
        "is_active": True,
        "available_stock": 4,
        "image_url": "/media/products/cover.jpg",
    }
    payload.update(overrides)
    return payload


# Schema: images sorted by position, max 5, cover unchanged.
def test_public_card_images_sorted_and_capped_at_five() -> None:
    images = [
        SimpleNamespace(
            id=i,
            url=f"/media/products/{position}.jpg",
            source_url=None,
            alt=None,
            position=position,
        )
        for i, position in enumerate((4, 1, 3, 0, 5, 2, 6), start=1)
    ]
    card = ProductPublicCardSchema.model_validate(_card_payload(images=images))
    assert [item.position for item in card.images] == [0, 1, 2, 3, 4]
    assert len(card.images) == PUBLIC_CARD_GALLERY_LIMIT
    assert [item.url for item in card.images] == [
        "/media/products/0.jpg",
        "/media/products/1.jpg",
        "/media/products/2.jpg",
        "/media/products/3.jpg",
        "/media/products/4.jpg",
    ]
    assert card.image_url == "/media/products/cover.jpg"


# Schema: blank gallery rows dropped, cover kept.
def test_public_card_images_drop_blank_and_keep_cover() -> None:
    images = [
        SimpleNamespace(id=1, url="", source_url=None, alt=None, position=0),
        SimpleNamespace(
            id=2,
            url="/media/products/keep.jpg",
            source_url=None,
            alt=None,
            position=1,
        ),
    ]
    card = ProductPublicCardSchema.model_validate(_card_payload(images=images))
    assert [item.url for item in card.images] == ["/media/products/keep.jpg"]
    assert card.image_url == "/media/products/cover.jpg"


# Schema: missing images defaults to [].
def test_public_card_images_default_empty() -> None:
    card = ProductPublicCardSchema(**_card_payload())
    assert card.images == []


# List path: product_images loaded once via selectinload IN (...), not per row.
async def test_catalog_list_selectinloads_product_images() -> None:
    captured: list[str] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    sync_engine = async_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor)
    try:
        async with async_session_maker() as session:
            items, _total, _has_more = await CatalogService(session).get_products_list(
                page=1,
                page_size=8,
                load_product_images=True,
                load_cover_image=False,
                resolve_local_images=True,
                count_total=False,
            )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor)

    if len(items) < 2:
        pytest.skip("need at least two catalog products to distinguish N+1")

    image_selects = [
        sql
        for sql in captured
        if "product_images" in sql.lower() and sql.lstrip().lower().startswith("select")
    ]
    assert len(image_selects) == 1, image_selects
    joined = image_selects[0].lower()
    assert " in (" in joined or " in(" in joined


SUPPLIER = "https://cdn.shopify.com/s/files/1/0638/1885/8538/files/P000000267060100.jpg"


# Managed URL становится public, supplier остаётся fallback_url.
def test_public_card_image_keeps_supplier_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://cdn.shopstore.example")
    card = ProductPublicCardSchema.model_validate(
        _card_payload(
            images=[
                SimpleNamespace(
                    id=1,
                    url="/media/products/foo.jpg",
                    source_url=SUPPLIER,
                    alt=None,
                    position=0,
                )
            ]
        )
    )
    image = card.images[0]
    assert image.url == "https://cdn.shopstore.example/media/products/foo.jpg"
    assert image.fallback_url == SUPPLIER
    assert "source_url" not in image.model_dump()


# Managed без source_url не получает выдуманный fallback.
def test_public_card_image_fallback_null_without_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://cdn.shopstore.example")
    card = ProductPublicCardSchema.model_validate(
        _card_payload(
            images=[
                SimpleNamespace(
                    id=1,
                    url="/media/products/foo.jpg",
                    source_url=None,
                    alt=None,
                    position=0,
                )
            ]
        )
    )
    image = card.images[0]
    assert image.url == "https://cdn.shopstore.example/media/products/foo.jpg"
    assert image.fallback_url is None


# Только supplier URL остаётся primary, без fallback и без public base.
def test_public_card_image_source_only_stays_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEDIA_PUBLIC_BASE", "https://cdn.shopstore.example")
    card = ProductPublicCardSchema.model_validate(
        _card_payload(
            images=[
                SimpleNamespace(
                    id=1,
                    url=None,
                    source_url=SUPPLIER,
                    alt=None,
                    position=0,
                )
            ]
        )
    )
    image = card.images[0]
    assert image.url == SUPPLIER
    assert image.fallback_url is None
    assert not image.url.startswith("https://cdn.shopstore.example")


# Пустые URL не превращаются в fallback.
def test_public_card_image_blank_row_adds_no_fallback() -> None:
    card = ProductPublicCardSchema.model_validate(
        _card_payload(
            images=[
                SimpleNamespace(id=1, url="", source_url=None, alt=None, position=0),
                SimpleNamespace(id=2, url=None, source_url="  ", alt=None, position=1),
            ]
        )
    )
    assert card.images == []
