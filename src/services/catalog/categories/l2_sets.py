APPAREL_CORE_L2: tuple[str, ...] = (
    "Shirts",
    "Shorts",
    "Pants",
    "Dresses",
    "Skirts",
    "Hoodies & Sweaters",
    "Tracksuits",
    "Jackets",
    "Outerwear",
    "Compression",
    "Sports Bras",
    "Tops",
    "Swimwear",
    "Underwear",
)

RUNNING_APPAREL_L2: tuple[str, ...] = ("Running apparel", "Running clothes")

APPAREL_L2 = frozenset(
    {
        *APPAREL_CORE_L2,
        *RUNNING_APPAREL_L2,
        "Padel clothing",
    }
)

PADEL_APPAREL_NAV_L2: tuple[str, ...] = (*APPAREL_CORE_L2, "Padel clothing")

TENNIS_APPAREL_NAV_L2: tuple[str, ...] = (
    "Padel clothing",
    *APPAREL_CORE_L2,
    *RUNNING_APPAREL_L2,
)

RUNNING_APPAREL_NAV_L2: tuple[str, ...] = (
    *RUNNING_APPAREL_L2,
    "Compression",
    "Jackets",
    "Outerwear",
    "Hoodies & Sweaters",
    "Tracksuits",
    "Shirts",
    "Shorts",
    "Pants",
    "Tops",
    "Underwear",
    "Socks",
    "Headgear",
    "Scarves",
)

ACCESSORIES_NAV_COMMON_L2: tuple[str, ...] = (
    "Accessories",
    "Overgrips",
    "Replacement grips",
    "Racket accessories",
    "Socks",
    "Wristbands",
    "Bandages",
    "Gloves",
    "Headgear",
    "Scarves",
    "Towels",
    "Training accessories",
    "Shoe accessories",
    "Fitness accessories",
    "Running accessories",
    "Running belts",
    "Court equipment",
    "Coach equipment",
    "Technical equipment",
    "Gifts",
)

PADEL_ACCESSORIES_NAV_L2: tuple[str, ...] = (
    "Padel accessories",
    "Grips",
    *ACCESSORIES_NAV_COMMON_L2,
)

TENNIS_ACCESSORIES_NAV_L2: tuple[str, ...] = (*ACCESSORIES_NAV_COMMON_L2, "Pickleball")

RUNNING_ACCESSORIES_NAV_L2: tuple[str, ...] = (
    "Running accessories",
    "Running belts",
    "Fitness accessories",
    "Wristbands",
    "Towels",
    "Bandages",
    "Accessories",
    "Shoe accessories",
    "Technical equipment",
    "Backpacks",
    "Bags",
)

ACCESSORIES_L2_FORCE = frozenset(
    {
        "Overgrips",
        "Replacement grips",
        "Racket accessories",
        "Coach equipment",
        "Court equipment",
        "Technical equipment",
        "Pickleball",
        "Gifts",
        "Books, DVD's, magazines",
    }
)

ACCESSORIES_PRODUCT_TYPES = ACCESSORIES_L2_FORCE | frozenset({"Accessories"})

RUNNING_L2 = frozenset(
    {
        *RUNNING_APPAREL_L2,
        "Running shoes",
        "Running accessories",
        "Running belts",
    }
)

PADEL_RACKET_L2: tuple[str, ...] = ("Padel rackets", "Padel racket")

TENNIS_RACKET_L2: tuple[str, ...] = (
    "Tennis rackets",
    "Junior rackets",
    "Tour rackets",
    "Allround rackets",
    "Power rackets",
    "Control rackets",
)

PARENT_L2_FOR_RACKET_SUBTYPES = frozenset(
    {
        "Tennis rackets",
        "Padel rackets",
        "Rackets",
        "Padel racket",
    }
)

BAGS_PADEL_NAV_L2: tuple[str, ...] = (
    "Padel bags",
    "Bags",
    "Racket bags",
    "Sports bags",
    "Gym bags",
    "Backpacks",
)

BAGS_TENNIS_NAV_L2: tuple[str, ...] = (
    "Bags",
    "Racket bags",
    "Sports bags",
    "Gym bags",
    "Backpacks",
    "Padel bags",
)
