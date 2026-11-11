from src.services.catalog.categories.l2_sets import (
    BAGS_PADEL_NAV_L2,
    BAGS_TENNIS_NAV_L2,
    PADEL_ACCESSORIES_NAV_L2,
    PADEL_APPAREL_NAV_L2,
    PADEL_RACKET_L2,
    RUNNING_ACCESSORIES_NAV_L2,
    RUNNING_APPAREL_L2,
    RUNNING_APPAREL_NAV_L2,
    RUNNING_L2,
    TENNIS_ACCESSORIES_NAV_L2,
    TENNIS_APPAREL_NAV_L2,
    TENNIS_RACKET_L2,
)
from src.services.catalog.read.scope import CATALOG_TOP_ORDER

STOREFRONT_SPORTS: frozenset[str] = frozenset(CATALOG_TOP_ORDER)

NON_STOREFRONT_IMPORT_SPORTS: frozenset[str] = frozenset(
    {"Training", "Lifestyle", "Pickleball", "Brands", "Topseller"}
)

MERCHANDISE_L1_LABELS: frozenset[str] = frozenset(
    {
        "Accessories",
        "Tennis clothing",
        "Padel clothing",
        *RUNNING_APPAREL_L2,
    }
)

APPAREL_PARENT_BY_SPORT: dict[str, str] = {
    "Padel": "Padel clothing",
    "Tennis": "Tennis clothing",
    "Running": "Running",
}

PARENT_APPAREL_BUCKETS: frozenset[str] = frozenset(
    {
        *APPAREL_PARENT_BY_SPORT.values(),
        *RUNNING_APPAREL_L2,
    }
)

FORBIDDEN_VISIBLE_CONTAINERS: frozenset[str] = frozenset(
    {
        "Outerwear",
        *RUNNING_APPAREL_L2,
        "Padel clothing",
        "Tennis clothing",
        "Running",
    }
)

PADEL_MERCHANDISE_L2: frozenset[str] = frozenset(
    {
        *PADEL_RACKET_L2,
        "Padel shoes",
        "Padel bags",
        "Padel accessories",
        "Padel balls",
        "Padel clothing",
    }
)

TENNIS_MERCHANDISE_L2: frozenset[str] = frozenset(
    {
        "Tennis shoes",
        "Tennis rackets",
        "Tennis balls",
        "Tennis clothing",
        "Junior rackets",
        "Tour rackets",
        "Allround rackets",
        "Power rackets",
        "Control rackets",
    }
)

RUNNING_MERCHANDISE_L2: frozenset[str] = frozenset(RUNNING_L2)

SPORT_MERCHANDISE_L2: dict[str, frozenset[str]] = {
    "Padel": PADEL_MERCHANDISE_L2,
    "Tennis": TENNIS_MERCHANDISE_L2,
    "Running": RUNNING_MERCHANDISE_L2,
}

PADEL_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "Padel shoes",
        "Padel rackets",
        "Padel racket",
        "Padel balls",
    }
)

TENNIS_MERCHANDISE_L1_LOW: frozenset[str] = frozenset(
    {
        "tennis clothing",
        "tennis shoes",
        "tennis rackets",
        "tennis balls",
    }
)

# supplier item_category3 → storefront leaf L2 (Running clothes refinement).
ITEM_CATEGORY3_TO_L2: dict[str, str] = {
    "Running tops": "Shirts",
    "Running pants & tights": "Pants",
    "Running jackets & vests": "Jackets",
    "Running socks": "Socks",
    "Headwear": "Headgear",
    "Gloves": "Running accessories",
    "Underwear": "Underwear",
    "Hoodies": "Hoodies & Sweaters",
}

# product_type внутри parent apparel bucket → leaf L2.
PRODUCT_TYPE_IN_PARENT_TO_L2: dict[str, str] = {
    "Headgear": "Headgear",
    "Socks": "Socks",
    "Jackets": "Jackets",
    "Shirts": "Shirts",
    "Shorts": "Shorts",
    "Skirts": "Skirts",
    "Dresses": "Dresses",
    "Pants": "Pants",
    "Hoodies": "Hoodies & Sweaters",
}

# Orphan L2 → nav-compatible alias.
ORPHAN_L2_NORMALIZATION: dict[str, str] = {
    "T-Shirts": "Shirts",
    "Padel racket": "Padel rackets",
    "Gloves": "Running accessories",
}

# running-tops → Shirts не применяется при compression/sleeve/tube сигналах.
RUNNING_TOPS_TO_SHIRTS_FRAGMENT = "running-running-clothes-running-tops"

COMPRESSION_SLEEVE_SIGNALS: tuple[str, ...] = (
    "compression",
    "sleeve",
    "sleeves",
    "tube",
    "tubes",
    "arm sleeve",
    "calf sleeve",
)

ACCESSORY_COLLECTION_MARKERS: tuple[str, ...] = (
    "accessories-training-accessories",
    "accessories-running-accessories",
    "running-running-accessories",
)

# Handle fragment → storefront category_l3; длинные фрагменты раньше.
COLLECTION_HANDLE_FRAGMENT_TO_L3: tuple[tuple[str, str], ...] = (
    ("running-running-shoes-recovery-shoes", "Recovery shoes"),
    ("running-running-clothes-running-jackets-vests", "Running jackets & vests"),
    ("running-running-clothes-running-pants-tights", "Running pants & tights"),
    ("running-running-clothes-underwear", "Underwear"),
    ("running-running-clothes-running-tops", "Running tops"),
)

# Running accessories: handle fragment → L3 + допустимые product_type.
RUNNING_ACCESSORIES_HANDLE_FRAGMENT_TO_L3: tuple[
    tuple[str, str, frozenset[str]], ...
] = (
    (
        "accessories-training-accessories-bandages-tapes",
        "Bandages & tapes",
        frozenset({"Bandages"}),
    ),
    (
        "running-running-accessories-bandages-tapes",
        "Bandages & tapes",
        frozenset({"Bandages"}),
    ),
    (
        "running-running-clothes-running-socks",
        "Running socks",
        frozenset({"Socks"}),
    ),
    (
        "accessories-training-accessories-fitness-accessories",
        "Training equipment",
        frozenset({"Fitness accessories"}),
    ),
    (
        "running-running-accessories-training-equipment",
        "Training equipment",
        frozenset({"Fitness accessories"}),
    ),
    (
        "accessories-training-accessories-water-bottles",
        "Water bottles",
        frozenset({"Accessories"}),
    ),
    (
        "other-accessories-water-bottles",
        "Water bottles",
        frozenset({"Accessories"}),
    ),
    (
        "running-running-accessories-hydration-systems",
        "Water bottles",
        frozenset({"Accessories"}),
    ),
    (
        "running-running-clothes-neckwarmer",
        "Neckwarmer",
        frozenset({"Scarves"}),
    ),
    (
        "tube-scarves",
        "Neckwarmer",
        frozenset({"Scarves"}),
    ),
    (
        "running-running-accessories-insoles",
        "Insoles",
        frozenset({"Shoe accessories"}),
    ),
    (
        "shoe-accessories-insoles",
        "Insoles",
        frozenset({"Shoe accessories"}),
    ),
    (
        "running-running-clothes-gloves",
        "Gloves",
        frozenset({"Gloves"}),
    ),
    (
        "tennis-clothing-men-accessories-gloves",
        "Gloves",
        frozenset({"Gloves"}),
    ),
    (
        "tennis-clothing-women-accessories-gloves",
        "Gloves",
        frozenset({"Gloves"}),
    ),
    (
        "tennis-clothing-kids-accessories-gloves",
        "Gloves",
        frozenset({"Gloves"}),
    ),
)

# Tennis accessories: L2 scope для handle/title L3 refinement.
TENNIS_RACKET_ACCESSORIES_L2: frozenset[str] = frozenset({"Racket accessories"})
TENNIS_SHOE_ACCESSORIES_L2: frozenset[str] = frozenset({"Shoe accessories"})
TENNIS_COURT_EQUIPMENT_L2: frozenset[str] = frozenset({"Court equipment"})
TENNIS_ACCESSORIES_L3_REFINEMENT_L2: frozenset[str] = frozenset(
    {
        *TENNIS_RACKET_ACCESSORIES_L2,
        *TENNIS_SHOE_ACCESSORIES_L2,
        *TENNIS_COURT_EQUIPMENT_L2,
    }
)

# Tennis accessories: handle fragment → L3 + допустимые category_l2.
TENNIS_ACCESSORIES_HANDLE_FRAGMENT_TO_L3: tuple[
    tuple[str, str, frozenset[str]], ...
] = (
    (
        "accessories-racket-accessories-grommets",
        "Grommets",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    (
        "accessories-racket-accessories-dampeners",
        "Dampeners",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    ("racket-accessories-dampeners", "Dampeners", TENNIS_RACKET_ACCESSORIES_L2),
    ("accessories-racket-accessories-stencil", "Stencil", TENNIS_RACKET_ACCESSORIES_L2),
    (
        "accessories-racket-accessories-lead-tape",
        "Lead tape",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    ("accessories-racket-accessories-grips", "Grips", TENNIS_RACKET_ACCESSORIES_L2),
    (
        "accessories-racket-accessories-racket-covers",
        "Racket covers",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    (
        "accessories-racket-accessories-frame-protection",
        "Frame protection",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    (
        "accessories-racket-accessories-elasto-cross",
        "Elasto-cross",
        TENNIS_RACKET_ACCESSORIES_L2,
    ),
    (
        "accessories-court-equipment-nets-accessories",
        "Nets & Accessories",
        TENNIS_COURT_EQUIPMENT_L2,
    ),
    ("nets-accessories", "Nets & Accessories", TENNIS_COURT_EQUIPMENT_L2),
    ("shoelaces", "Shoelaces", TENNIS_SHOE_ACCESSORIES_L2),
)

# Running accessories: product_type → L3 fallback (без title).
RUNNING_ACCESSORIES_PRODUCT_TYPE_TO_L3: dict[str, str] = {
    "Bandages": "Bandages & tapes",
    "Socks": "Running socks",
    "Fitness accessories": "Training equipment",
    "Gloves": "Gloves",
    "Scarves": "Neckwarmer",
    "Shoe accessories": "Insoles",
}

# Handle fragment → apparel L2; длинные фрагменты раньше.
COLLECTION_HANDLE_FRAGMENT_TO_L2: tuple[tuple[str, str], ...] = (
    (RUNNING_TOPS_TO_SHIRTS_FRAGMENT, "Shirts"),
    ("running-running-clothes-running-pants-tights", "Pants"),
    ("running-running-clothes-running-jackets-vests", "Jackets"),
    ("running-running-clothes-running-socks", "Socks"),
    ("tennisbekleidung-tennisroecke", "Skirts"),
    ("tennisbekleidung-tops", "Shirts"),
    ("tennis-clothing-shorts", "Shorts"),
    ("tennisbekleidung-shorts", "Shorts"),
    ("tennisbekleidung-dresses", "Dresses"),
    ("tennisbekleidung-jackets", "Jackets"),
    ("tennisbekleidung-hoodies", "Hoodies & Sweaters"),
    ("padel-padel-clothing-shirts", "Shirts"),
    ("padel-padel-clothing-shorts", "Shorts"),
    ("padel-padel-clothing-skirts", "Skirts"),
    ("padel-padel-clothing-dresses", "Dresses"),
    ("padel-padel-clothing-jackets", "Jackets"),
    ("tennis-clothing-shirts", "Shirts"),
    ("tennis-clothing-dresses", "Dresses"),
    ("tennis-clothing-skirts", "Skirts"),
    ("tennis-clothing-jackets", "Jackets"),
)

# Handle suffix → apparel L2 leaf; длинные суффиксы раньше.
APPAREL_L2_BY_COLLECTION_HANDLE_SUFFIX: tuple[tuple[str, str], ...] = (
    ("-shirts-t-shirts", "Shirts"),
    ("-hoodies-sweaters-hoodies", "Hoodies & Sweaters"),
    ("-hoodies-sweaters", "Hoodies & Sweaters"),
    ("-tracksuits", "Tracksuits"),
    ("-jackets", "Jackets"),
    ("-dresses", "Dresses"),
    ("-skirts", "Skirts"),
    ("-shorts", "Shorts"),
    ("-pants", "Pants"),
    ("-shirts", "Shirts"),
    ("-compression", "Compression"),
    ("-sports-bras", "Sports Bras"),
    ("-swimwear", "Swimwear"),
    ("-underwear", "Underwear"),
)

# Префиксы collection handle для apparel refinement.
APPAREL_COLLECTION_HANDLE_MARKERS: tuple[str, ...] = (
    "tennis-clothing",
    "tennisbekleidung",
    "running-",
    "padel-",
)

NAV_L2_BY_SPORT: dict[str, frozenset[str]] = {
    "Padel": frozenset(
        {
            *PADEL_RACKET_L2,
            *PADEL_APPAREL_NAV_L2,
            "Padel shoes",
            "Shoes",
            "Padel balls",
            "Giant balls",
            *BAGS_PADEL_NAV_L2,
            *PADEL_ACCESSORIES_NAV_L2,
        }
    ),
    "Tennis": frozenset(
        {
            *TENNIS_RACKET_L2,
            *TENNIS_APPAREL_NAV_L2,
            *BAGS_TENNIS_NAV_L2,
            "Tennis balls",
            "Giant balls",
            "String sets",
            "String reels",
            *TENNIS_ACCESSORIES_NAV_L2,
        }
    ),
    "Running": frozenset(
        {
            "Running shoes",
            "Shoes",
            *RUNNING_APPAREL_NAV_L2,
            *RUNNING_ACCESSORIES_NAV_L2,
        }
    ),
}
