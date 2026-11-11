from src.scraper.sources.graphql_categories import resolve_graphql_categories
from src.services.catalog.categories.pipeline import (
    resolve_catalog_fields_from_supplier_snapshot,
)
from src.services.catalog.categories.sport_policy import resolve_storefront_sport
from src.utils.html_text import strip_html_plaintext


def test_padel_accessories_stay_padel_not_tennis() -> None:
    collections = [
        ("padel-padel-accessories", "Padel accessories (Padel)"),
    ]
    sport = resolve_storefront_sport(
        import_collection_sport="Padel",
        merchandise_l1="Accessories",
        merchandise_l2="Overgrips",
        product_collections=collections,
    )
    assert sport == "Padel"


def test_padel_apparel_l1_and_shirt_l2() -> None:
    snapshot = {
        "import_collection_sport": "Padel",
        "product_type": "Outerwear",
        "collections": [
            {"handle": "padel-padel-clothing", "title": "Padel clothing (Padel)"},
            {
                "handle": "tennis-clothing-shirts-women-lilac",
                "title": "Women's purple shirts",
            },
        ],
        "supplier_taxonomy": {
            "item_category": "Padel clothing",
            "item_category2": "T-Shirts",
            "sport_type": "Padel",
        },
    }
    got = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title="Leido T-Shirt Men-Green",
    )
    assert got["sport_type"] == "Padel"
    assert got["category_l1"] == "Padel clothing"
    assert got["category_l2"] == "Shirts"


def test_graphql_categories_padel_overgrip() -> None:
    got = resolve_graphql_categories(
        sport_type="Padel",
        product_type="Overgrips",
        collections=[("padel-padel-accessories", "Padel accessories (Padel)")],
        title="Padel Overgrip 3 Pack-Orange",
    )
    assert got["sport_type"] == "Padel"
    assert got["category_l1"] == "Accessories"


def test_strip_html_plaintext() -> None:
    raw = "<p>Hello <strong>world</strong></p>"
    assert strip_html_plaintext(raw) == "Hello world"


def test_padel_import_wins_over_supplier_tennis_sport_on_overgrip() -> None:
    snapshot = {
        "import_collection_sport": "Padel",
        "product_type": "Overgrips",
        "collections": [
            {"handle": "padel-padel-accessories", "title": "Padel accessories"}
        ],
        "supplier_taxonomy": {
            "item_category": "Accessories",
            "item_category2": "Grips",
            "item_category3": "Overgrips",
            "sport_type": "Tennis",
        },
    }
    got = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title="Pro Overgrip 3 Pack-White",
    )
    assert got["sport_type"] == "Padel"


def test_padel_import_wins_over_supplier_tennis_sport_on_padel_bag() -> None:
    snapshot = {
        "import_collection_sport": "Padel",
        "product_type": "Backpacks",
        "collections": [{"handle": "padel-padel-bags", "title": "Padel bags (Padel)"}],
        "supplier_taxonomy": {
            "item_category": "Padel",
            "item_category2": "Padel bags",
            "sport_type": "Tennis",
        },
    }
    got = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title="Tour 25L Backpack - blue",
    )
    assert got["sport_type"] == "Padel"


def test_padel_import_wins_over_supplier_pickleball_sport_on_padel_shoe() -> None:
    snapshot = {
        "import_collection_sport": "Padel",
        "product_type": "Padel shoes",
        "collections": [
            {"handle": "padel-padel-shoes", "title": "Padel shoes (Padel)"}
        ],
        "supplier_taxonomy": {
            "item_category": "Padel",
            "item_category2": "Padel shoes",
            "sport_type": "Pickleball",
        },
    }
    got = resolve_catalog_fields_from_supplier_snapshot(
        snapshot,
        title="HYBRID FLY 26V Padel shoe Men-white",
    )
    assert got["sport_type"] == "Padel"
