from src.services.catalog.categories.sport_policy import (
    resolve_storefront_sport,
    sport_from_collection_handles,
)


def test_strong_padel_merchandise_beats_taxonomy_pickleball() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Padel",
        merchandise_l1="Padel",
        merchandise_l2="Padel shoes",
        product_type="Padel shoes",
        product_collections=[("padel-padel-shoes", "Padel shoes (Padel)")],
        supplier_taxonomy_sport="Pickleball",
    )
    assert sport == "Padel"


def test_strong_padel_collection_beats_accessories_and_taxonomy_tennis() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Padel",
        merchandise_l1="Accessories",
        merchandise_l2="Grips",
        product_type="Overgrips",
        product_collections=[("padel-padel-accessories", "Padel accessories (Padel)")],
        supplier_taxonomy_sport="Tennis",
    )
    assert sport == "Padel"


def test_running_merchandise_beats_padel_import() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Padel",
        merchandise_l1="Running",
        merchandise_l2="Running shoes",
        product_type="Shoes",
        product_collections=[("running-running-shoes", "Running shoes (Running)")],
        supplier_taxonomy_sport="Padel",
    )
    assert sport == "Running"


def test_padel_import_beats_tennis_only_collections() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Padel",
        merchandise_l1="Padel",
        merchandise_l2="Padel clothing",
        product_type="Outerwear",
        product_collections=[
            ("tennis-clothing-shirts-women-lilac", "Women's purple shirts"),
            ("sale-tennis-clothing", "Tennis clothing on sale"),
        ],
        supplier_taxonomy_sport="Tennis",
    )
    assert sport == "Padel"


def test_padel_collection_beats_tennis_import() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Tennis",
        merchandise_l1="Padel",
        merchandise_l2="Padel bags",
        product_type="Backpacks",
        product_collections=[("padel-padel-bags", "Padel bags (Padel)")],
        supplier_taxonomy_sport="Tennis",
    )
    assert sport == "Padel"


def test_collection_sport_when_import_not_storefront() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Training",
        merchandise_l1="Tennis clothing",
        merchandise_l2="Shirts",
        product_collections=[("tennis-clothing-shirts", "Shirts (Tennis clothing)")],
        supplier_taxonomy_sport="Tennis",
    )
    assert sport == "Tennis"


def test_taxonomy_sport_fallback_when_no_other_signals() -> None:
    sport = resolve_storefront_sport(
        import_collection_sport="Brands",
        merchandise_l1="",
        merchandise_l2="",
        product_collections=[],
        supplier_taxonomy_sport="Pickleball",
    )
    assert sport == "Pickleball"


def test_padel_collection_wins_over_tennis_handle_order() -> None:
    collections = [
        ("tennis-clothing-shirts-t-shirts", "T-Shirts (Tennis clothing/Shirts)"),
        ("padel-padel-clothing", "Padel clothing (Padel)"),
    ]
    assert sport_from_collection_handles(collections) == "Padel"
