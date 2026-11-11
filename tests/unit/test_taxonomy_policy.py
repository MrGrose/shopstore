import pytest

from src.scraper.sources.graphql_categories import resolve_graphql_categories
from src.services.catalog.categories.registries import (
    APPAREL_PARENT_BY_SPORT,
    PARENT_APPAREL_BUCKETS,
    STOREFRONT_SPORTS,
)
from src.services.catalog.categories.taxonomy_policy import (
    _apply_padel_clothing_title_refinement,
    apparel_parent_for_sport,
    classify_item_category_role,
    project_supplier_merchandise_taxonomy,
    refine_parent_apparel_l2,
    refine_visible_container_l2,
)

_TENNIS_RACKET_ACCESSORIES_TAXONOMY = {
    "item_category": "Tennis",
    "item_category2": "Racket accessories",
    "item_category3": None,
    "sport_type": "Tennis",
}
_TENNIS_SHOE_ACCESSORIES_TAXONOMY = {
    "item_category": "Tennis",
    "item_category2": "Shoe accessories",
    "item_category3": None,
    "sport_type": "Tennis",
}
_TENNIS_COURT_EQUIPMENT_TAXONOMY = {
    "item_category": "Tennis",
    "item_category2": "Court equipment",
    "item_category3": None,
    "sport_type": "Tennis",
}


def _resolve_tennis_accessory(
    *,
    product_type: str,
    collections: list[tuple[str, str]],
    title: str = "",
    supplier_taxonomy: dict | None = None,
) -> dict[str, str | None]:
    return resolve_graphql_categories(
        sport_type="Tennis",
        product_type=product_type,
        collections=collections,
        title=title,
        supplier_taxonomy=supplier_taxonomy or _TENNIS_RACKET_ACCESSORIES_TAXONOMY,
    )


_PADEL_CLOTHING_TAXONOMY = {
    "item_category": "Padel",
    "item_category2": "Padel clothing",
    "item_category3": None,
    "sport_type": "Padel",
}
_PADEL_PARENT_COLLECTIONS = [("padel-padel-clothing", "Padel clothing (Padel)")]


def _refine_padel_clothing_title(title: str) -> str:
    return refine_parent_apparel_l2(
        "Padel clothing",
        _PADEL_PARENT_COLLECTIONS,
        supplier_taxonomy=_PADEL_CLOTHING_TAXONOMY,
        product_type="Outerwear",
        storefront_sport="Padel",
        title=title,
    )


def test_classify_sport_namespace_for_all_storefront_sports() -> None:
    for sport in STOREFRONT_SPORTS:
        assert classify_item_category_role(sport) == "sport_namespace"


def test_classify_merchandise_l1_accessories() -> None:
    assert classify_item_category_role("Accessories") == "merchandise_l1"


def test_apparel_parent_by_sport_not_padel_only() -> None:
    assert apparel_parent_for_sport("Padel") == "Padel clothing"
    assert apparel_parent_for_sport("Tennis") == "Tennis clothing"
    assert apparel_parent_for_sport("Running") == "Running"
    assert set(APPAREL_PARENT_BY_SPORT) == STOREFRONT_SPORTS


def test_sport_namespace_coarse_padel_apparel() -> None:
    projected = project_supplier_merchandise_taxonomy(
        {
            "item_category": "Padel",
            "item_category2": "Padel clothing",
            "item_category3": None,
        },
        storefront_sport="Padel",
        product_type="Outerwear",
    )
    assert projected.category_l1 == "Padel clothing"
    assert projected.category_l2 == "Padel clothing"
    assert projected.l2_is_parent_bucket is True


def test_sport_namespace_padel_equipment_line() -> None:
    projected = project_supplier_merchandise_taxonomy(
        {
            "item_category": "Padel",
            "item_category2": "Padel shoes",
            "item_category3": None,
        },
        storefront_sport="Padel",
        product_type="Padel shoes",
    )
    assert projected.category_l1 == "Padel shoes"
    assert projected.category_l2 == "Padel shoes"


def test_sport_namespace_tennis_shoes() -> None:
    projected = project_supplier_merchandise_taxonomy(
        {
            "item_category": "Tennis",
            "item_category2": "Tennis shoes",
            "item_category3": None,
        },
        storefront_sport="Tennis",
        product_type="Tennis shoes",
    )
    assert projected.category_l1 == "Tennis shoes"
    assert projected.category_l2 == "Tennis shoes"


def test_merchandise_l1_keeps_tennis_clothing_on_padel_sport() -> None:
    projected = project_supplier_merchandise_taxonomy(
        {
            "item_category": "Tennis clothing",
            "item_category2": "Hoodies & Sweaters",
            "item_category3": "Hoodies",
        },
        storefront_sport="Padel",
        product_type="Outerwear",
    )
    assert projected.category_l1 == "Tennis clothing"
    assert projected.category_l2 == "Hoodies & Sweaters"
    assert projected.category_l3 == "Hoodies"


def test_refine_parent_apparel_from_collection_handle() -> None:
    collections = [
        ("tennis-clothing-shirts-t-shirts", "T-Shirts (Tennis clothing/Shirts)"),
        ("padel-padel-clothing", "Padel clothing (Padel)"),
    ]
    refined = refine_parent_apparel_l2(
        "Padel clothing",
        collections,
        storefront_sport="Padel",
    )
    assert refined == "Shirts"


@pytest.mark.parametrize(
    ("title", "expected_l2"),
    [
        ("Swift Shorts Men", "Shorts"),
        ("Bloom Skirt Women-white", "Skirts"),
        ("Minimal Skirt Women", "Skirts"),
        ("Team Skirts Women", "Skirts"),
        ("Orbit Dress Women", "Dresses"),
        ("Gomese Hoody Men", "Hoodies & Sweaters"),
        ("Malla Tight Women", "Pants"),
        ("Leiro Polo Men", "Shirts"),
        ("Padel Is Us T-Shirt Men", "Shirts"),
        ("Kirsch Long Sleeve Women", "Shirts"),
    ],
)
def test_refine_padel_clothing_from_title(title: str, expected_l2: str) -> None:
    assert _refine_padel_clothing_title(title) == expected_l2


# Shorts в title не должен попадать в Skirts.
def test_refine_padel_clothing_shorts_not_skirts() -> None:
    assert _refine_padel_clothing_title("Court 2in1 Shorts Women-violet") == "Shorts"


def test_refine_padel_clothing_title_does_not_affect_tennis() -> None:
    refined = refine_visible_container_l2(
        "Tennis clothing",
        {"item_category": "Tennis", "item_category2": "Tennis clothing"},
        [("tennis-clothing", "Tennis clothing (Tennis)")],
        product_type="Outerwear",
        storefront_sport="Tennis",
        title="Swift Shorts Men",
    )
    assert refined == "Tennis clothing"


def test_resolve_graphql_padel_clothing_shorts_from_title() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Padel",
        product_type="Outerwear",
        collections=_PADEL_PARENT_COLLECTIONS,
        title="Swift Shorts Men",
        supplier_taxonomy=_PADEL_CLOTHING_TAXONOMY,
    )
    assert resolved["category_l2"] == "Shorts"
    assert resolved["sport_type"] == "Padel"


def test_parent_buckets_cover_all_sports() -> None:
    for parent in APPAREL_PARENT_BY_SPORT.values():
        assert parent in PARENT_APPAREL_BUCKETS


def test_tennis_accessories_grommet_handle_without_ic3() -> None:
    resolved = _resolve_tennis_accessory(
        product_type="Racket accessories",
        collections=[
            (
                "accessories-racket-accessories-grommets",
                "Grommets (Accessories/Racket accessories)",
            ),
            ("accessories-racket-accessories", "Racket accessories (Accessories)"),
        ],
        title="Pure Drive Team Grommet set",
    )
    assert resolved["category_l3"] == "Grommets"
    assert resolved["sport_type"] == "Tennis"


def test_tennis_accessories_dampener_handle_without_ic3() -> None:
    resolved = _resolve_tennis_accessory(
        product_type="Racket accessories",
        collections=[
            (
                "accessories-racket-accessories-dampeners",
                "Dampeners (Accessories/Racket accessories)",
            ),
        ],
        title="FUN Dampener 2 Pack",
    )
    assert resolved["category_l3"] == "Dampeners"


def test_tennis_accessories_shoelaces_handle() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Tennis",
        product_type="Shoe accessories",
        collections=[
            (
                "tennis-shoes-men-shoe-accessories-shoelaces",
                "Shoelaces (Tennis shoes/Shoe accessories)",
            ),
        ],
        title="Shoelaces 120cm-Blue",
        supplier_taxonomy=_TENNIS_SHOE_ACCESSORIES_TAXONOMY,
    )
    assert resolved["category_l3"] == "Shoelaces"


def test_tennis_accessories_nets_handle() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Tennis",
        product_type="Coach equipment",
        collections=[
            (
                "accessories-court-equipment-nets-accessories",
                "Nets & Accessories (Accessories/Court equipment)",
            ),
        ],
        title="Tennis Net 6,10m Replacement-Black",
        supplier_taxonomy=_TENNIS_COURT_EQUIPMENT_TAXONOMY,
    )
    assert resolved["category_l3"] == "Nets & Accessories"


def test_tennis_accessories_supplier_ic3_wins_over_handle() -> None:
    resolved = _resolve_tennis_accessory(
        product_type="Racket accessories",
        collections=[
            (
                "accessories-racket-accessories-grommets",
                "Grommets (Accessories/Racket accessories)",
            ),
        ],
        title="Pure Strike 100 Grommet set",
        supplier_taxonomy={
            **_TENNIS_RACKET_ACCESSORIES_TAXONOMY,
            "item_category3": "Grommets",
        },
    )
    assert resolved["category_l3"] == "Grommets"


def test_tennis_accessories_refinement_does_not_affect_running() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Running",
        product_type="Bandages",
        collections=[
            (
                "accessories-racket-accessories-grommets",
                "Grommets (Accessories/Racket accessories)",
            ),
        ],
        title="Pure Drive Team Grommet set",
        supplier_taxonomy={
            "item_category": "Running",
            "item_category2": "Bandages",
            "item_category3": None,
        },
    )
    assert resolved["category_l3"] != "Grommets"


def test_tennis_accessories_refinement_does_not_affect_padel() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Padel",
        product_type="Racket accessories",
        collections=[
            (
                "accessories-racket-accessories-grommets",
                "Grommets (Accessories/Racket accessories)",
            ),
        ],
        title="Pure Drive Team Grommet set",
        supplier_taxonomy={
            "item_category": "Padel",
            "item_category2": "Racket accessories",
            "item_category3": None,
        },
    )
    assert resolved["category_l3"] != "Grommets"


def test_tennis_accessories_refinement_does_not_affect_tennis_apparel() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Tennis",
        product_type="Outerwear",
        collections=[("tennis-clothing-shirts", "Shirts (Tennis clothing/Shirts)")],
        title="RF Cap Men",
        supplier_taxonomy={
            "item_category": "Tennis",
            "item_category2": "Tennis clothing",
            "item_category3": None,
        },
    )
    assert resolved["category_l2"] == "Tennis clothing"
    assert resolved["category_l3"] is None


def test_tennis_accessories_butt_cap_title_to_grips_not_caps() -> None:
    resolved = _resolve_tennis_accessory(
        product_type="Racket accessories",
        collections=[
            ("accessories-racket-accessories", "Racket accessories (Accessories)")
        ],
        title="Pro Staff RF 97 V13 Butt Cap-Black",
    )
    assert resolved["category_l3"] == "Grips"
    assert resolved["category_l3"] != "Caps & Visors"


def test_tennis_accessories_ball_marker_title_to_ball_clips() -> None:
    resolved = _resolve_tennis_accessory(
        product_type="Racket accessories",
        collections=[
            ("accessories-racket-accessories", "Racket accessories (Accessories)")
        ],
        title="Classic Ball Marker-Blue",
    )
    assert resolved["category_l3"] == "Ball clips"


def test_padel_clothing_title_jacket_to_jackets() -> None:
    assert (
        _apply_padel_clothing_title_refinement(
            "Padel clothing", "Padel", "Breath Training jacket - black"
        )
        == "Jackets"
    )


def test_padel_clothing_title_training_jacket_to_jackets() -> None:
    assert (
        _apply_padel_clothing_title_refinement(
            "Padel clothing",
            "Padel",
            "J. Lebron Training jacket Men-black",
        )
        == "Jackets"
    )


@pytest.mark.parametrize(
    "title",
    [
        "BPG261 Cap Men - white",
        "BPV261 Visor Women - white",
        "BP262 (PACK DE 3) Sports Socks Unisex - black",
    ],
)
def test_padel_clothing_title_cap_visor_socks_stay_container(title: str) -> None:
    assert (
        _apply_padel_clothing_title_refinement("Padel clothing", "Padel", title)
        == "Padel clothing"
    )


def test_padel_clothing_title_shorts_and_skirt_rules_unchanged() -> None:
    assert (
        _apply_padel_clothing_title_refinement(
            "Padel clothing", "Padel", "Meis 25V Shorts Men-Sage"
        )
        == "Shorts"
    )
    assert (
        _apply_padel_clothing_title_refinement(
            "Padel clothing", "Padel", "Asegur Skirt Women - apricot"
        )
        == "Skirts"
    )


def test_tennis_accessories_ambiguous_shoe_misc_stays_unclassified() -> None:
    resolved = resolve_graphql_categories(
        sport_type="Tennis",
        product_type="Shoe accessories",
        collections=[
            ("tennis-shoes-shoe-accessories", "Shoe accessories (Tennis shoes)"),
        ],
        title="Lights Up Strawberry Miscellaneous Unisex - pink, green",
        supplier_taxonomy=_TENNIS_SHOE_ACCESSORIES_TAXONOMY,
    )
    assert resolved["category_l3"] is None


def test_refine_outerwear_tennis_tshirt_to_shirts() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_visible_container_l2,
    )

    refined = refine_visible_container_l2(
        "Outerwear",
        {"item_category": "Tennis", "item_category2": "Tennis clothing"},
        [],
        product_type="Outerwear",
        storefront_sport="Tennis",
        title="Dri-Fit Victory T-Shirt Women - white, black",
    )
    assert refined == "Shirts"


def test_refine_outerwear_padel_skirt_to_skirts() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_visible_container_l2,
    )

    refined = refine_visible_container_l2(
        "Outerwear",
        {"item_category": "Padel", "item_category2": "Padel"},
        [],
        product_type="Outerwear",
        storefront_sport="Padel",
        title="Basica Skirt Women-beige",
    )
    assert refined == "Skirts"


def test_refine_padel_makeup_bag_taxonomy() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_padel_makeup_bag_taxonomy,
    )

    l1, l2, l3 = refine_padel_makeup_bag_taxonomy(
        "Padel accessories",
        "Padel accessories",
        None,
        "Padel",
        "D.CASE Make up bag - white",
    )
    assert (l1, l2, l3) == ("Padel", "Bags", "Cosmetic bags")


def test_refine_storefront_mapping_taxonomy_wristband() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Padel clothing",
        "Padel clothing",
        None,
        "Padel",
        "BPMU262 Wristband long - black",
    )
    assert (l1, l2, l3) == ("Padel accessories", "Padel accessories", None)


def test_refine_storefront_mapping_taxonomy_padel_cap() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Padel accessories",
        "Padel accessories",
        None,
        "Padel",
        "BPG261 Cap Men - black",
    )
    assert (l1, l2, l3) == ("Padel clothing", "Headgear", None)


def test_refine_storefront_mapping_taxonomy_water_bottle() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Accessories",
        "Accessories",
        None,
        "Padel",
        "Big Mouth Water Bottle-White",
    )
    assert (l1, l2, l3) == ("Accessories", "Training accessories", None)


def test_refine_storefront_mapping_taxonomy_running_shorts() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Running clothes",
        "Pants",
        "Running pants & tights",
        "Running",
        "adi365 3in Running shorts Men - grey",
    )
    assert (l1, l2, l3) == ("Running", "Shorts", None)


def test_refine_storefront_mapping_taxonomy_running_clothes_bucket_from_title() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    assert refine_storefront_mapping_taxonomy(
        "Running clothes",
        "Running clothes",
        None,
        "Running",
        "PHOENIX Shorts Men - blue",
    ) == ("Running", "Shorts", None)
    assert refine_storefront_mapping_taxonomy(
        "Running clothes",
        "Running clothes",
        None,
        "Running",
        "VANITY POCKET Tight Women - black, olive",
    ) == ("Running clothes", "Pants", None)
    assert refine_storefront_mapping_taxonomy(
        "Running clothes",
        "Running clothes",
        None,
        "Running",
        "INNER TECH Sweatshirt Women - blue",
    ) == ("Running clothes", "Hoodies & Sweaters", None)


def test_refine_storefront_mapping_taxonomy_tennis_compression_tights() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    assert refine_storefront_mapping_taxonomy(
        "Tennis clothing",
        "Compression",
        None,
        "Tennis",
        "Motion Ankle Leg Tight Women-Black",
    ) == ("Tennis clothing", "Compression", "Tights")


def test_refine_storefront_mapping_taxonomy_padel_makeup_bag() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Padel",
        "Bags",
        None,
        "Padel",
        "D.CASE Make up bag - white",
    )
    assert (l1, l2, l3) == ("Padel", "Bags", "Cosmetic bags")


def test_refine_storefront_mapping_taxonomy_outerwear_tshirt() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Tennis clothing",
        "Outerwear",
        None,
        "Tennis",
        "Ace Slim T-Shirt Women - dark blue",
    )
    assert (l1, l2, l3) == ("Tennis clothing", "Shirts", None)


def test_refine_storefront_mapping_taxonomy_racket_dampener() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Accessories",
        "Racket accessories",
        None,
        "Tennis",
        "ZOO Dampener 2 Pack-Multicoloured",
    )
    assert (l1, l2, l3) == ("Accessories", "Racket accessories", "Dampeners")


def test_refine_tennis_headgear_cap_to_caps_visors() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Tennis clothing",
        "Headgear",
        None,
        "Tennis",
        "Club Court Cap Unisex - black",
    )
    assert (l1, l2, l3) == ("Tennis clothing", "Accessories", "Caps & Visors")


def test_refine_tennis_headgear_headband() -> None:
    from src.services.catalog.categories.taxonomy_policy import (
        refine_storefront_mapping_taxonomy,
    )

    l1, l2, l3 = refine_storefront_mapping_taxonomy(
        "Tennis clothing",
        "Headgear",
        None,
        "Tennis",
        "Jacob Headband Unisex - white, blue",
    )
    assert (l1, l2, l3) == ("Tennis clothing", "Accessories", "Headbands")
