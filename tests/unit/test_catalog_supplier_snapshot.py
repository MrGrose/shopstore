import json
from pathlib import Path

from src.models.product import Product, ProductFeature, ProductImage
from src.services.catalog.categories.pipeline import (
    resolve_catalog_fields_from_supplier_snapshot,
)
from src.services.catalog.importing.product_complete import is_product_complete
from src.services.catalog.supplier.snapshot import (
    apply_supplier_snapshot_to_product,
    build_supplier_snapshot,
    merge_supplier_taxonomy_from_pdp_meta,
    supplier_snapshot_hash,
)
from src.utils.datetime_fmt import utc_now_naive

_GOLDEN_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / ".01_hlam/docs/samples/graphql_catalog_sample.json"
)


# Проверяет is_product_complete на минимальном Product.
def test_is_product_complete_requires_core_fields():
    product = Product(
        title="Test",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=0,
        external_id="ext1",
        product_url="https://example.com/p",
        description_raw="desc",
    )
    assert is_product_complete(product) is False

    product.images = [ProductImage(url="https://img", position=0)]
    assert is_product_complete(product) is False

    product.features = [ProductFeature(name="Weight", value="360g", position=0)]
    assert is_product_complete(product) is True

    product.features = []
    product.dom_full_at = utc_now_naive()
    assert is_product_complete(product) is True


# Сравнивает build_supplier_snapshot с golden fixture.
def test_build_supplier_snapshot_matches_golden_sample():
    if not _GOLDEN_SAMPLE.is_file():
        return
    payload = json.loads(_GOLDEN_SAMPLE.read_text(encoding="utf-8"))
    for row in payload.get("samples") or []:
        import_payload = row.get("import_payload") or {}
        expected = row.get("supplier_snapshot_for_db")
        if not expected:
            continue
        built = build_supplier_snapshot(import_payload)
        assert built is not None
        assert built == expected
        assert supplier_snapshot_hash(built) == supplier_snapshot_hash(expected)


# Hash стабилен при одинаковом canonical JSON.
def test_supplier_snapshot_hash_stable():
    snapshot = {
        "import_collection_sport": "Padel",
        "product_type": "Padel rackets",
        "collections": [{"handle": "padel", "title": "Padel"}],
    }
    assert supplier_snapshot_hash(snapshot) == supplier_snapshot_hash(dict(snapshot))


# merge_supplier_taxonomy_from_pdp_meta: no-op без skeleton snapshot.
def test_merge_supplier_taxonomy_requires_skeleton() -> None:
    product = Product(
        title="Test",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=0,
    )
    assert (
        merge_supplier_taxonomy_from_pdp_meta(product, {"item_category2": "T-Shirts"})
        is False
    )


# merge_supplier_taxonomy_from_pdp_meta: partial merge и hash update.
def test_merge_supplier_taxonomy_partial_merge() -> None:
    product = Product(
        title="Test",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=0,
        supplier_snapshot_json={
            "import_collection_sport": "Padel",
            "product_type": "Outerwear",
            "collections": [
                {"handle": "padel-padel-clothing", "title": "Padel clothing"}
            ],
        },
        supplier_snapshot_hash=supplier_snapshot_hash(
            {
                "import_collection_sport": "Padel",
                "product_type": "Outerwear",
                "collections": [
                    {"handle": "padel-padel-clothing", "title": "Padel clothing"}
                ],
            }
        ),
    )
    changed = merge_supplier_taxonomy_from_pdp_meta(
        product,
        {
            "item_category": "Padel clothing",
            "item_category2": "T-Shirts",
            "sport_type": "Padel",
        },
    )
    assert changed is True
    taxonomy = (product.supplier_snapshot_json or {}).get("supplier_taxonomy") or {}
    assert taxonomy["item_category2"] == "T-Shirts"
    assert (
        merge_supplier_taxonomy_from_pdp_meta(product, {"item_category2": "T-Shirts"})
        is False
    )


# merge_supplier_taxonomy_from_pdp_meta: пустой pdp_meta — no-op.
def test_merge_supplier_taxonomy_empty_pdp_meta() -> None:
    product = Product(
        title="Test",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=0,
        supplier_snapshot_json={
            "import_collection_sport": "Padel",
            "product_type": "Outerwear",
            "collections": [],
        },
    )
    assert merge_supplier_taxonomy_from_pdp_meta(product, {}) is False


# Следующий GraphQL snapshot сохраняет taxonomy, добавленную DOM enrichment.
def test_graphql_snapshot_preserves_dom_supplier_taxonomy() -> None:
    graphql_payload = {
        "pdp_meta": {
            "supplier": {
                "import_collection_sport": "Running",
                "product_type": "Headgear",
                "collections": [
                    {
                        "handle": "running-running-clothes-headwear",
                        "title": "Headwear (Running/Running clothes)",
                    }
                ],
            }
        }
    }
    product = Product(
        title="Nefun Run Cap Unisex-multicoloured",
        brand="PAC",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=1,
    )

    assert apply_supplier_snapshot_to_product(product, graphql_payload) is True
    assert (
        merge_supplier_taxonomy_from_pdp_meta(
            product,
            {
                "item_category": "Running",
                "item_category2": "Running clothes",
                "item_category3": "Headwear",
                "sport_type": "Running",
            },
        )
        is True
    )

    assert apply_supplier_snapshot_to_product(product, graphql_payload) is False
    snapshot = product.supplier_snapshot_json or {}
    taxonomy = snapshot.get("supplier_taxonomy") or {}
    assert taxonomy["item_category3"] == "Headwear"
    resolved = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title=product.title,
    )
    assert resolved["category_l2"] == "Headgear"
    assert resolved["category_l3"] == "Headwear"

    graphql_payload["pdp_meta"]["supplier"]["collections"].append(
        {"handle": "sale", "title": "% SALE %"}
    )
    assert apply_supplier_snapshot_to_product(product, graphql_payload) is True
    changed_snapshot = product.supplier_snapshot_json or {}
    changed_taxonomy = changed_snapshot.get("supplier_taxonomy") or {}
    assert changed_taxonomy["item_category3"] == "Headwear"


# Смена supplier scope не переносит устаревшую DOM taxonomy в новый snapshot.
def test_graphql_snapshot_drops_dom_taxonomy_after_supplier_scope_change() -> None:
    product = Product(
        title="Test",
        brand="Brand",
        sale_price=0,
        regular_price=0,
        supplier_price_eur=0,
        stock=1,
        supplier_snapshot_json={
            "import_collection_sport": "Running",
            "product_type": "Headgear",
            "collections": [],
            "supplier_taxonomy": {
                "item_category2": "Running clothes",
                "item_category3": "Headwear",
            },
        },
    )
    product.supplier_snapshot_hash = supplier_snapshot_hash(
        product.supplier_snapshot_json
    )
    changed_payload = {
        "pdp_meta": {
            "supplier": {
                "import_collection_sport": "Running",
                "product_type": "Socks",
                "collections": [],
            }
        }
    }

    assert apply_supplier_snapshot_to_product(product, changed_payload) is True
    snapshot = product.supplier_snapshot_json or {}
    assert snapshot["product_type"] == "Socks"
    assert "supplier_taxonomy" not in snapshot
