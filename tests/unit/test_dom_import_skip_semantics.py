from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.product import Product
from src.schemas.catalog_import import ProductImport, ProductImportGtm
from src.services.catalog.importing.coordinator import ProductImportService
from src.utils.datetime_fmt import utc_now_naive


@pytest.mark.asyncio
async def test_dom_import_skips_when_price_unchanged_and_touches_catalog_sync() -> None:
    price = Decimal("40.29")
    synced_before = utc_now_naive()
    existing = Product(
        id=10348,
        title="Test racket",
        brand="Bullpadel",
        sale_price=price,
        regular_price=price,
        supplier_price_eur=price,
        stock=1,
        external_id="ext-10348",
        product_url="https://example.com/p10348",
        catalog_synced_at=synced_before,
        dom_full_at=synced_before,
    )

    product = ProductImport(
        title="Test racket",
        brand="Bullpadel",
        sale_price=price,
        sale_price_numeric=price,
        regular_price=price,
        product_url="https://example.com/p10348",
        item_id="ext-10348",
        import_source="dom",
        dom_mode="LITE",
        stock=1,
        gtm=ProductImportGtm(),
    )

    session = MagicMock()
    svc = ProductImportService(session)
    svc.product_crud.get_by_external_id_with_related = AsyncMock(return_value=existing)
    svc.product_crud.get_by_url_with_related = AsyncMock(return_value=None)
    svc.pricing_service.get_margin_rules = AsyncMock(return_value={})
    svc.pricing_service.get_settings = AsyncMock(return_value=MagicMock(eur_rate="1.0"))
    svc.pricing_service.resolve_category_key = MagicMock(return_value="padel")

    result = await svc._import_one_product(
        product,
        download_images=False,
        downloaded_cache={},
        translation_map={},
        settings=MagicMock(eur_rate="1.0"),
        incoming_external_ids=set(),
        incoming_urls=set(),
        incoming_top_categories=set(),
        new_products=[],
        touched_ids=set(),
        taxonomy_changed_ids=set(),
    )

    assert result == {"created": 0, "updated": 0, "skipped": 1}
    assert existing.supplier_price_eur == price
    assert existing.catalog_synced_at is not None
    assert existing.catalog_synced_at >= synced_before
