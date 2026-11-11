from src.services.catalog.categories.pipeline import (
    resolve_catalog_fields_from_supplier_snapshot,
)


def _snapshot(
    import_sport: str,
    product_type: str,
    collections: list[dict[str, str]] | None = None,
    supplier_taxonomy: dict[str, str] | None = None,
) -> dict:
    payload: dict = {
        "import_collection_sport": import_sport,
        "product_type": product_type,
        "collections": collections or [],
    }
    if supplier_taxonomy:
        payload["supplier_taxonomy"] = supplier_taxonomy
    return payload


def test_padel_clothing_shirts_collection_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "padel-padel-clothing-shirts-men",
                    "title": "Shirts (padel/padel clothing/shirts)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["sport_type"] == "Padel"
    assert catalog["category_l2"] == "Shirts"


def test_padel_clothing_tshirts_collection_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennis-clothing-shirts-t-shirts-men",
                    "title": "T-Shirts (padel/padel clothing/shirts)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["category_l2"] == "Shirts"


def test_padel_clothing_tennisroecke_to_skirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennisbekleidung-tennisroecke-women",
                    "title": "Skirts (tennis/tennis clothing/skirts)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["category_l2"] == "Skirts"


def test_padel_clothing_dresses_collection():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennisbekleidung-dresses-women",
                    "title": "Dresses (tennis/tennis clothing/dresses)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["category_l2"] == "Dresses"


def test_padel_clothing_shorts_collection():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennis-clothing-shorts-men",
                    "title": "Shorts (tennis/tennis clothing/shorts)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["category_l2"] == "Shorts"


def test_running_outerwear_running_tops_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Outerwear",
            collections=[
                {
                    "handle": "running-running-clothes-running-tops-women",
                    "title": "Running tops (running/running clothes/tops)",
                }
            ],
        )
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l2"] == "Shirts"


def test_running_outerwear_pants_tights_to_pants():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Outerwear",
            collections=[
                {
                    "handle": "running-running-clothes-running-pants-tights-men",
                    "title": "Running pants (running/running clothes/pants)",
                }
            ],
        )
    )
    assert catalog["category_l2"] == "Pants"


def test_running_clothes_socks_to_socks_l2():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Running clothes",
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Running clothes",
                "item_category3": "Running socks",
            },
        )
    )
    assert catalog["category_l2"] == "Socks"
    assert catalog["category_l3"] == "Running socks"


def test_running_clothes_gloves_to_gloves_l2():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Running clothes",
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Running clothes",
                "item_category3": "Gloves",
            },
        )
    )
    assert catalog["category_l2"] == "Running accessories"
    assert catalog["category_l3"] == "Gloves"


def test_padel_clothing_tennisbekleidung_tops_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennisbekleidung-tops-damen-weiss",
                    "title": "Tops (tennis/tennis clothing/tops)",
                },
                {"handle": "padel-padel-clothing", "title": "Padel clothing"},
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        ),
        title="Pirac Tank Top Women",
    )
    assert catalog["sport_type"] == "Padel"
    assert catalog["category_l2"] == "Shirts"


def test_running_gloves_orphan_normalized_to_running_accessories():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Gloves",
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Running clothes",
                "item_category3": "Gloves",
            },
        ),
        title="Run Glove Running Gloves-Black",
    )
    assert catalog["category_l2"] == "Running accessories"
    assert catalog["category_l3"] == "Gloves"


def test_running_recovery_shoes_stay_running():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Running shoes",
            collections=[
                {
                    "handle": "running-running-shoes-recovery-shoes",
                    "title": "Recovery shoes (running/running shoes/recovery)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Running shoes",
                "item_category2": "Running shoes",
                "item_category3": "Recovery shoes",
            },
        ),
        title="Recovery Runner Slipper",
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l2"] == "Running shoes"


def test_padel_overgrips_stay_padel_despite_tennis_supplier_sport():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Overgrips",
            collections=[
                {"handle": "padel-padel-accessories", "title": "Padel accessories"}
            ],
            supplier_taxonomy={
                "item_category": "Accessories",
                "item_category2": "Overgrips",
                "sport_type": "Tennis",
            },
        )
    )
    assert catalog["sport_type"] == "Padel"


def test_tennis_shoes_keep_subtype_in_l3():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Tennis",
            "Clay court shoes",
            collections=[
                {
                    "handle": "tennis-tennis-shoes-clay-court-shoes-men",
                    "title": "Clay court shoes (tennis/tennis shoes/clay)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Tennis shoes",
                "item_category2": "Clay court shoes",
            },
        )
    )
    assert catalog["sport_type"] == "Tennis"
    assert catalog["category_l2"] == "Tennis shoes"
    assert catalog["category_l3"] == "Clay court shoes"


def test_padel_rackets_without_subtype_have_no_l3():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Padel rackets",
            collections=[{"handle": "padel-padel-racket-en", "title": "Padel rackets"}],
            supplier_taxonomy={
                "item_category": "Padel rackets",
                "item_category2": "Padel rackets",
            },
        ),
        title="Generic Padel Racket",
    )
    assert catalog["category_l2"] == "Padel rackets"
    assert catalog["category_l3"] is None


def test_padel_outerwear_shirts_collection_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennis-clothing-shirts-t-shirts",
                    "title": "T-Shirts (tennis clothing)",
                },
                {"handle": "padel-padel-clothing", "title": "Padel clothing (Padel)"},
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Outerwear",
            },
        ),
        title="Shenzi Lifestyle T-Shirt Women-Red",
    )
    assert catalog["sport_type"] == "Padel"
    assert catalog["category_l2"] == "Shirts"


def test_padel_outerwear_hoodies_collection_to_hoodies():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "tennis-clothing-men-hoodies-sweaters-hoodies",
                    "title": "Hoodies (tennis clothing)",
                },
                {"handle": "padel-padel-clothing", "title": "Padel clothing (Padel)"},
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Outerwear",
            },
        ),
        title="Spike Logo Chill Hoody Men-Dark Green",
    )
    assert catalog["sport_type"] == "Padel"
    assert catalog["category_l2"] == "Hoodies & Sweaters"


def test_running_shoes_recovery_collection_to_l3():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Shoes",
            collections=[
                {
                    "handle": "running-running-shoes-recovery-shoes",
                    "title": "Recovery shoes (Running/Running shoes)",
                },
                {"handle": "tennis-shoes-slippers", "title": "Slippers (Tennis shoes)"},
            ],
        ),
        title="Gizeh Sandal Women - lilac",
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l3"] == "Recovery shoes"


def test_running_apparel_other_jackets_collection_to_l3():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Jackets",
            collections=[
                {
                    "handle": "running-running-clothes-running-jackets-vests",
                    "title": "Running jackets & vests (Running/Running clothes)",
                },
                {
                    "handle": "running-running-clothes",
                    "title": "Running clothes (Running)",
                },
            ],
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Running clothes",
            },
        ),
        title="Swift Running jacket Women - berry, silver",
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l3"] == "Running jackets & vests"


def test_running_compression_tube_not_mapped_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Outerwear",
            collections=[
                {
                    "handle": "accessories-training-accessories",
                    "title": "Training accessories",
                },
                {
                    "handle": "running-running-clothes-running-tops",
                    "title": "Tops (running/running clothes/running tops)",
                },
                {
                    "handle": "accessories-training-accessories-bandages-tapes",
                    "title": "Bandages & tapes",
                },
            ],
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Outerwear",
            },
        ),
        title="Hypervent Compression tube Unisex - black",
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l2"] == "Compression"
    assert catalog["category_l3"] is None
    assert catalog["category_l2"] != "Shirts"


def test_running_arm_sleeve_in_accessories_to_running_accessories():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Running",
            "Outerwear",
            collections=[
                {
                    "handle": "accessories-training-accessories",
                    "title": "Training accessories",
                },
                {
                    "handle": "running-running-clothes-running-tops",
                    "title": "Tops (running/running clothes/running tops)",
                },
            ],
            supplier_taxonomy={
                "item_category": "Running",
                "item_category2": "Outerwear",
            },
        ),
        title="Arm sleeve Unisex - black",
    )
    assert catalog["sport_type"] == "Running"
    assert catalog["category_l2"] == "Running accessories"


def test_tshirts_orphan_normalized_to_shirts():
    catalog = resolve_catalog_fields_from_supplier_snapshot(
        _snapshot(
            "Padel",
            "Outerwear",
            collections=[
                {
                    "handle": "padel-padel-clothing-shirts-t-shirts-women",
                    "title": "T-Shirts (padel/padel clothing/shirts)",
                }
            ],
            supplier_taxonomy={
                "item_category": "Padel",
                "item_category2": "Padel clothing",
            },
        )
    )
    assert catalog["category_l2"] == "Shirts"
