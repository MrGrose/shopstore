"""Regression tests for catalog variant import identity.

Prod incident: variant_external_id=43956216201258 with option2=S;
re-import with option2=4-7 must UPDATE, not INSERT (UniqueViolation).

"""

from dataclasses import dataclass
from decimal import Decimal

import pytest

from src.models.product import Product, ProductVariant
from src.schemas.catalog_import import ProductImportVariant
from src.services.catalog.importing.helpers import upsert_variants

# Prod sample from RCA (2026-08-07).
_PROD_VARIANT_EXTERNAL_ID = "43956216201258"
_PROD_SKU = "P000000182230202"


@dataclass(frozen=True)
class _VariantSnapshot:
    external_id: str | None
    sku: str | None
    option1: str | None
    option2: str | None
    price: Decimal
    inventory_quantity: int
    available: bool


def _base_product() -> Product:
    return Product(
        title="Velociti Run Cush Crew 3pack Socks (white)",
        brand="Under Armour",
        sale_price=Decimal("0"),
        supplier_price_eur=Decimal("0"),
        regular_price=Decimal("0"),
        stock=0,
        product_url="https://example.com/socks-white",
        is_active=True,
    )


def _existing_socks_variant(*, option2: str) -> ProductVariant:
    return ProductVariant(
        variant_external_id=_PROD_VARIANT_EXTERNAL_ID,
        sku=_PROD_SKU,
        option1="White",
        option2=option2,
        price=Decimal("1990"),
        compare_at_price=Decimal("0"),
        inventory_quantity=5,
        available=True,
    )


def _import_payload(*, option2: str) -> list[ProductImportVariant]:
    return [
        ProductImportVariant(
            id=_PROD_VARIANT_EXTERNAL_ID,
            sku=_PROD_SKU,
            option1="White",
            option2=option2,
            price=Decimal("1990"),
            compare_at_price=Decimal("0"),
            inventory_quantity=5,
            available=True,
        )
    ]


def _snapshot_variants(product: Product) -> tuple[_VariantSnapshot, ...]:
    return tuple(
        _VariantSnapshot(
            external_id=variant.variant_external_id,
            sku=variant.sku,
            option1=variant.option1,
            option2=variant.option2,
            price=Decimal(str(variant.price or 0)),
            inventory_quantity=int(variant.inventory_quantity or 0),
            available=bool(variant.available),
        )
        for variant in sorted(
            product.variants,
            key=lambda item: str(item.variant_external_id or ""),
        )
    )


# Case 1: prod UniqueViolation — same external id, option label drift (S → 4-7).
def test_upsert_updates_variant_when_option_label_changes() -> None:
    product = _base_product()
    product.variants.append(_existing_socks_variant(option2="S"))

    upsert_variants(product, _import_payload(option2="4-7"), selected_variant=None)

    assert len(product.variants) == 1
    variant = product.variants[0]
    assert variant.variant_external_id == _PROD_VARIANT_EXTERNAL_ID
    assert variant.option2 == "4-7"


# Case 2: repeated import of the same snapshot must be idempotent.
def test_repeated_import_same_snapshot_is_idempotent() -> None:
    product = _base_product()
    product.variants.append(_existing_socks_variant(option2="S"))
    payload = _import_payload(option2="S")

    upsert_variants(product, payload, selected_variant=None)
    first = _snapshot_variants(product)

    upsert_variants(product, payload, selected_variant=None)
    second = _snapshot_variants(product)

    assert first == second
    assert len(product.variants) == 1


# Case 3: parallel import + DOM on one product — no duplicate variant_external_id.
@pytest.mark.skip(
    reason="Integration baseline: isolated test DB + concurrent sessions",
)
def test_parallel_import_and_dom_no_duplicate_external_id() -> None:
    """Import coordinator and DOM enrichment must not create duplicate external ids."""
    pytest.skip("Not implemented in Phase 0 unit scope")


# Case 4: pricing + DOM status on one product — no deadlock.
@pytest.mark.skip(
    reason="Integration baseline: needs concurrent pricing + DOM writers (Phase 0)",
)
def test_pricing_and_dom_status_update_no_deadlock() -> None:
    """Concurrent product row writers should not deadlock after Phase 1 ordering."""
    pytest.skip("Not implemented in Phase 0 unit scope")
