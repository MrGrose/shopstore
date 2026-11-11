import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from src.models.product import Product, ProductFeature, ProductImage
from src.repositories.session import async_session_maker
from src.scraper.enrichment.product_dom import _dom_update_details, apply_dom_details
from src.services.catalog.importing.dom_status import record_dom_status
from src.services.catalog.importing.product_complete import (
    has_valid_product_description,
    is_product_complete,
    validate_full_dom_details,
)

_IMPRINT_16878 = (
    "TRADINTER S.L. Transpaderne, 29 4 Izsa., Building Barajas I, "
    "Madrid 28042, Spain www.bullpadel.com"
)
_VALID_DESC = (
    "Experience Unmatched Comfort with the Oneda Tank Top for Women. "
    "Designed specifically for the dynamic world of padel."
)
_GALLERY = [{"url": "https://www.supplier-demo.com/cdn/shop/files/oneda.jpg"}]


def _full_details(description: str, gallery: list | None = None) -> dict:
    return {
        "description": description,
        "media_gallery": gallery if gallery is not None else list(_GALLERY),
        "prices": {"sale_price": "47.95", "regular_price": "47.99"},
        "product_data": {},
        "selected_variant": {},
        "features": [],
        "pdp_meta": {},
    }


def test_http_200_imprint_is_validation_failure():
    assert validate_full_dom_details(_full_details(_IMPRINT_16878)) == (
        "invalid_description"
    )


def test_http_200_valid_description_and_gallery_is_success():
    assert validate_full_dom_details(_full_details(_VALID_DESC)) is None


def test_empty_pdp_is_invalid_pdp():
    assert (
        validate_full_dom_details({"description": "", "media_gallery": []})
        == "invalid_pdp"
    )


def test_valid_description_without_gallery_is_invalid_gallery():
    assert (
        validate_full_dom_details(_full_details(_VALID_DESC, gallery=[]))
        == "invalid_gallery"
    )


def test_apply_dom_details_still_treats_imprint_as_enriched():
    product: dict = {"product_url": "https://example.com/p"}
    enriched = apply_dom_details(
        product,
        _full_details(_IMPRINT_16878),
        update_details=True,
    )
    assert enriched is True
    assert product.get("import_source") == "dom"


def test_full_gate_rejects_imprint_before_success():
    details = _full_details(_IMPRINT_16878)
    product = {"dom_mode": "FULL", "product_url": "https://example.com/p"}
    assert _dom_update_details(product) is True
    invalid = validate_full_dom_details(details)
    assert invalid == "invalid_description"
    product["_dom_last_error"] = invalid
    assert product.get("import_source") != "dom"


def test_lite_does_not_require_description_or_gallery():
    product = {"dom_mode": "LITE"}
    assert _dom_update_details(product) is False
    empty = validate_full_dom_details({"description": "", "media_gallery": []})
    assert empty == "invalid_pdp"


def test_long_description_with_www_is_not_imprint():
    text = (
        "Experience Unmatched Comfort with the Oneda Tank Top for Women. "
        "See details at www.bullpadel.com and on the official padel shop. "
        "Crafted from polyester for breathability on court."
    )
    assert len(text) >= 150
    assert has_valid_product_description(text) is True
    assert validate_full_dom_details(_full_details(text)) is None


def test_valid_description_qualifies_for_dom_full_at():
    assert has_valid_product_description(_VALID_DESC) is True
    assert has_valid_product_description(_IMPRINT_16878) is False


@pytest.mark.asyncio
async def test_local_clone_16878_matches_invalid_description_contract() -> None:
    async with async_session_maker() as session:
        product = await session.scalar(
            select(Product)
            .where(Product.id == 16878)
            .options(
                selectinload(Product.images),
                selectinload(Product.features),
            )
        )
    if product is None:
        pytest.skip("local clone missing product 16878")
    if has_valid_product_description(product.description_raw):
        pytest.skip("product 16878 already recovered from imprint")
    gallery = [{"url": image.url} for image in (product.images or []) if image.url]
    assert (
        validate_full_dom_details(
            {"description": product.description_raw, "media_gallery": gallery}
        )
        == "invalid_description"
    )
    assert is_product_complete(product) is False
    assert int(product.dom_attempts or 0) == 0
    assert not product.dom_last_error


def _status_product(prefix: str, attempts: int) -> Product:
    return Product(
        title=f"DOM val {prefix}",
        brand="TestBrand",
        sale_price=100,
        regular_price=100,
        supplier_price_eur=50,
        stock=1,
        is_active=True,
        external_id=f"{prefix}-ext",
        product_url=f"https://example.com/{prefix}",
        description_raw=_IMPRINT_16878,
        dom_attempts=attempts,
        dom_last_error=None,
    )


async def _insert_status_product(product: Product) -> int:
    async with async_session_maker() as session:
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return int(product.id)


async def _delete_status_product(product_id: int) -> None:
    async with async_session_maker() as session:
        await session.execute(
            delete(ProductFeature).where(ProductFeature.product_id == product_id)
        )
        await session.execute(
            delete(ProductImage).where(ProductImage.product_id == product_id)
        )
        await session.execute(delete(Product).where(Product.id == product_id))
        await session.commit()


@pytest.mark.asyncio
async def test_validation_failure_increments_attempts_and_does_not_reset() -> None:
    prefix = f"dom-val-{uuid.uuid4().hex[:12]}"
    product_id = await _insert_status_product(_status_product(prefix, attempts=2))
    payload = {
        "product_url": f"https://example.com/{prefix}",
        "_dom_last_error": "invalid_description",
    }
    try:
        await record_dom_status(success_products=[], failed_products=[payload])
        async with async_session_maker() as session:
            row = await session.scalar(select(Product).where(Product.id == product_id))
        assert row is not None
        assert int(row.dom_attempts or 0) == 3
        assert row.dom_last_error == "invalid_description"
        assert row.is_active is True
    finally:
        await _delete_status_product(product_id)


@pytest.mark.asyncio
async def test_validated_success_still_resets_attempts() -> None:
    prefix = f"dom-val-{uuid.uuid4().hex[:12]}"
    product_id = await _insert_status_product(_status_product(prefix, attempts=2))
    success = {
        "product_url": f"https://example.com/{prefix}",
        "import_source": "dom",
    }
    try:
        await record_dom_status(success_products=[success], failed_products=[])
        async with async_session_maker() as session:
            row = await session.scalar(select(Product).where(Product.id == product_id))
        assert row is not None
        assert int(row.dom_attempts or 0) == 0
        assert row.dom_last_error is None
    finally:
        await _delete_status_product(product_id)


@pytest.mark.asyncio
async def test_fifth_validation_failure_reaches_max_attempts_and_stays_active() -> None:
    prefix = f"dom-val-{uuid.uuid4().hex[:12]}"
    product_id = await _insert_status_product(_status_product(prefix, attempts=4))
    payload = {
        "product_url": f"https://example.com/{prefix}",
        "_dom_last_error": "invalid_description",
    }
    try:
        await record_dom_status(success_products=[], failed_products=[payload])
        async with async_session_maker() as session:
            row = await session.scalar(select(Product).where(Product.id == product_id))
        assert row is not None
        assert int(row.dom_attempts or 0) == 5
        assert row.dom_last_error == "invalid_description"
        assert row.is_active is True
        assert row.deactivated_at is None
    finally:
        await _delete_status_product(product_id)
