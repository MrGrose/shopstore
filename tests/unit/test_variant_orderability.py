from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.product import Product, ProductVariant
from src.schemas.catalog_import import (
    ProductImport,
    ProductImportPdpMeta,
    ProductImportVariant,
)
from src.scraper.sources.collection_dom import apply_collection_listing
from src.scraper.sources.graphql_catalog import _variant_payload, apply_variant_stock
from src.services.cart_service import CartService
from src.services.catalog.importing.helpers import preserve_existing_variant_state
from src.services.catalog.importing.skeleton_writer import preserve_graphql_dom_fields
from src.services.orders.supplier_availability.client import (
    parse_supplier_variant_offline,
)

# Regression: On THE ROGER Pro 3 Clay cream/blue 42,5 (не production hardcode).
_REGRESSION_VID = 55634795659649
_REGRESSION_SKU = "P000000319020305"
_SIBLING_VID = 43980347211818


def _incoming(
    *,
    available: bool,
    qty: int,
    variant_id: int = _REGRESSION_VID,
    sku: str = _REGRESSION_SKU,
) -> ProductImportVariant:
    return ProductImportVariant(
        id=variant_id,
        sku=sku,
        option1="cream, blue",
        option2="42,5",
        available=available,
        inventory_quantity=qty,
        price=Decimal("185.00"),
        compare_at_price=Decimal("185.00"),
    )


def _existing(
    *,
    available: bool,
    qty: int,
    variant_id: str = str(_REGRESSION_VID),
    sku: str = _REGRESSION_SKU,
) -> Product:
    product = Product(
        title="THE ROGER Pro 3 Clay",
        brand="On",
        sale_price=Decimal("185"),
        supplier_price_eur=Decimal("120"),
        regular_price=Decimal("185"),
        stock=qty,
        product_url="https://www.supplier-demo.com/products/demo",
        is_active=True,
    )
    product.variants = [
        ProductVariant(
            variant_external_id=variant_id,
            sku=sku,
            option1="cream, blue",
            option2="42,5",
            inventory_quantity=qty,
            available=available,
            price=Decimal("185"),
            compare_at_price=Decimal("185"),
        )
    ]
    return product


# Collection ?variant= не ставит available=true / qty=1.
def test_collection_listing_does_not_fabricate_stock() -> None:
    product = {
        "product_data": {
            "variants": [
                {
                    "id": _REGRESSION_VID,
                    "sku": _REGRESSION_SKU,
                    "available": False,
                    "inventory_quantity": 0,
                }
            ]
        },
        "selected_variant": {
            "id": _REGRESSION_VID,
            "available": False,
            "inventory_quantity": 0,
        },
        "stock": 0,
    }
    listed = apply_collection_listing(product, {str(_REGRESSION_VID)})
    variant = product["product_data"]["variants"][0]
    assert listed == 1
    assert variant["available"] is False
    assert variant["inventory_quantity"] == 0
    assert product["selected_variant"]["available"] is False
    assert product.get("pdp_meta") is None


# GraphQL false/0 бьёт stale true/2.
def test_preserve_authoritative_false_beats_stale_true() -> None:
    existing = _existing(available=True, qty=2)
    merged = preserve_existing_variant_state(
        [_incoming(available=False, qty=0)], existing
    )
    assert len(merged) == 1
    assert merged[0].available is False
    assert merged[0].inventory_quantity == 0


# GraphQL true + synthetic qty=0 сохраняет DOM qty.
def test_preserve_keeps_dom_qty_when_graphql_available_true() -> None:
    existing = _existing(available=True, qty=2)
    merged = preserve_existing_variant_state(
        [_incoming(available=True, qty=0)], existing
    )
    assert merged[0].available is True
    assert merged[0].inventory_quantity == 2


# listing_stock_synced больше не пропускает preserve.
def test_preserve_graphql_dom_fields_false_beats_stale() -> None:
    existing = _existing(available=True, qty=2)
    incoming = ProductImport(
        title="x",
        brand="On",
        product_url="https://www.supplier-demo.com/products/demo",
        pdp_meta=ProductImportPdpMeta(stock_source="collection_listing_fallback"),
    )
    _sale, _reg, stock, variants, _selected = preserve_graphql_dom_fields(
        existing,
        incoming,
        [_incoming(available=False, qty=0)],
        None,
        resolve_stock=lambda fallback, items, selected: sum(
            v.inventory_quantity for v in items
        ),
        preserve_variants=preserve_existing_variant_state,
        preserve_selected=lambda selected, product: selected,
    )
    assert variants[0].available is False
    assert variants[0].inventory_quantity == 0
    assert stock == 0


# DOM product-data false/0 перезаписывает stale true/2.
def test_apply_variant_stock_authoritative_false() -> None:
    product = {
        "product_data": {
            "variants": [
                {
                    "id": _REGRESSION_VID,
                    "sku": _REGRESSION_SKU,
                    "available": True,
                    "inventory_quantity": 2,
                }
            ]
        }
    }
    changed = apply_variant_stock(
        product,
        {
            "variants": [
                {
                    "id": _REGRESSION_VID,
                    "available": False,
                    "inventory_quantity": 0,
                }
            ]
        },
    )
    variant = product["product_data"]["variants"][0]
    assert changed is True
    assert variant["available"] is False
    assert variant["inventory_quantity"] == 0


# Product-level availableForSale не делает variant available.
def test_graphql_variant_payload_ignores_product_available() -> None:
    payload = _variant_payload(
        {
            "id": f"gid://shopify/ProductVariant/{_REGRESSION_VID}",
            "sku": _REGRESSION_SKU,
            "availableForSale": False,
            "title": "cream, blue / 42,5",
            "selectedOptions": [
                {"name": "Variant", "value": "cream, blue"},
                {"name": "Shoe size", "value": "42,5"},
            ],
            "price": {"amount": "185.00", "currencyCode": "EUR"},
        }
    )
    assert payload["available"] is False
    assert payload["inventory_quantity"] == 0


# Size 42,5 в options.values не делает variant orderable.
def test_option_matrix_does_not_imply_orderable() -> None:
    product = {
        "product_data": {
            "variants": [
                {
                    "id": _REGRESSION_VID,
                    "available": False,
                    "inventory_quantity": 0,
                    "option2": "42,5",
                }
            ]
        },
        "options": [{"name": "Shoe size", "values": ["40", "42,5", "43"]}],
    }
    apply_collection_listing(product, {str(_REGRESSION_VID)})
    assert product["product_data"]["variants"][0]["available"] is False


# Sibling colour true не меняет current variant.
def test_sibling_variant_does_not_affect_current() -> None:
    product = {
        "product_data": {
            "variants": [
                {
                    "id": _REGRESSION_VID,
                    "available": False,
                    "inventory_quantity": 0,
                }
            ]
        }
    }
    apply_variant_stock(
        product,
        {
            "variants": [
                {
                    "id": _SIBLING_VID,
                    "available": True,
                    "inventory_quantity": 17,
                }
            ]
        },
    )
    current = product["product_data"]["variants"][0]
    assert current["available"] is False
    assert current["inventory_quantity"] == 0


# Offline client: regression fixture false / 0.
def test_parse_supplier_variant_offline_oos() -> None:
    product_json = (
        '{"variants":[{"id":55634795659649,"sku":"P000000319020305",'
        '"available":false,"option1":"cream, blue","option2":"42,5"}]}'
    )
    html = (
        '<html><body><script id="product-data" type="application/json">'
        '{"variants":[{"id":55634795659649,"available":false,'
        '"inventory_quantity":0,"option1":"cream, blue","option2":"42,5"}]}'
        "</script></body></html>"
    )
    result = parse_supplier_variant_offline(
        product_url="https://www.supplier-demo.com/products/demo",
        product_json_text=product_json,
        html=html,
        variant_id=str(_REGRESSION_VID),
        sku=_REGRESSION_SKU,
    )
    assert result.found is True
    assert result.snapshot is not None
    assert result.snapshot.available is False
    assert result.snapshot.inventory_quantity == 0


# Cart отказывает unavailable variant.
@pytest.mark.asyncio
async def test_cart_rejects_unavailable_variant() -> None:
    product = _existing(available=False, qty=0)
    product.id = 14714
    product.variants[0].id = 80242
    product.variants[0].product_id = 14714
    service = CartService.__new__(CartService)
    service.product_crud = MagicMock()
    service.product_crud.get_by_id_with_related = AsyncMock(return_value=product)
    with pytest.raises(ValueError, match="недоступен"):
        await service._resolve_product_availability(14714, 80242)
