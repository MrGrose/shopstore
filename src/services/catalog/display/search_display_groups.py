from dataclasses import dataclass

STOREFRONT_DISPLAY_MAP_VERSION = 5

_TENNIS_APPAREL_TOP = "Tennis"
_TENNIS_APPAREL_SUB = "apparel"
_RUNNING_APPAREL_TOP = "Running"
_RUNNING_APPAREL_SUB = "apparel"


@dataclass(frozen=True)
class CatalogRawSlice:
    category_l2: str
    category_l3: str | None = None


@dataclass(frozen=True)
class StorefrontDisplayGroup:
    display_key: str
    label_ru: str
    sources: tuple[CatalogRawSlice, ...]


TENNIS_APPAREL_DISPLAY_GROUPS: tuple[StorefrontDisplayGroup, ...] = (
    StorefrontDisplayGroup(
        "t-shirts",
        "Футболки",
        (
            CatalogRawSlice("Shirts", "T-Shirts"),
            CatalogRawSlice("Tops", "T-Shirts"),
        ),
    ),
    StorefrontDisplayGroup(
        "polo",
        "Поло",
        (
            CatalogRawSlice("Polos"),
            CatalogRawSlice("Shirts", "Polos"),
        ),
    ),
    StorefrontDisplayGroup(
        "longsleeves",
        "Лонгсливы",
        (CatalogRawSlice("Shirts", "Long sleeve"),),
    ),
    StorefrontDisplayGroup(
        "tops",
        "Топы",
        (CatalogRawSlice("Tops"),),
    ),
    StorefrontDisplayGroup(
        "sports-bras",
        "Спортивные топы",
        (
            CatalogRawSlice("Sports Bras"),
            CatalogRawSlice("Underwear", "Sports Bras"),
        ),
    ),
    StorefrontDisplayGroup(
        "shorts",
        "Шорты",
        (
            CatalogRawSlice("Shorts"),
            CatalogRawSlice("Shorts", "Ball shorts"),
            CatalogRawSlice("Pants", "Shorts"),
            CatalogRawSlice("Compression", "Shorts"),
        ),
    ),
    StorefrontDisplayGroup(
        "skirts",
        "Юбки",
        (CatalogRawSlice("Skirts"),),
    ),
    StorefrontDisplayGroup(
        "dresses",
        "Платья",
        (CatalogRawSlice("Dresses"),),
    ),
    StorefrontDisplayGroup(
        "pants-leggings",
        "Брюки и леггинсы",
        (
            CatalogRawSlice("Pants", "Leggings"),
            CatalogRawSlice("Pants", "Capri pants"),
            CatalogRawSlice("Compression", "Pants"),
            CatalogRawSlice("Compression", "Tights"),
        ),
    ),
    StorefrontDisplayGroup(
        "jackets-vests",
        "Куртки и жилеты",
        (
            CatalogRawSlice("Outerwear"),
            CatalogRawSlice("Jackets", "Vests"),
            CatalogRawSlice("Jackets", "Training jackets"),
            CatalogRawSlice("Jackets", "Sweat jackets"),
        ),
    ),
    StorefrontDisplayGroup(
        "hoodies-sweatshirts",
        "Толстовки",
        (
            CatalogRawSlice("Hoodies & Sweaters", "Hoodies"),
            CatalogRawSlice("Hoodies & Sweaters", "Sweatshirts"),
            CatalogRawSlice("Hoodies & Sweaters", "Slipover"),
        ),
    ),
    StorefrontDisplayGroup(
        "tracksuits",
        "Спортивные костюмы",
        (
            CatalogRawSlice("Tracksuits"),
            CatalogRawSlice("Pants", "Tracksuit bottoms"),
        ),
    ),
    StorefrontDisplayGroup(
        "underwear",
        "Нижнее бельё",
        (
            CatalogRawSlice("Underwear", "Panties"),
            CatalogRawSlice("Underwear", "Slips"),
            CatalogRawSlice("Underwear", "Strings"),
            CatalogRawSlice("Underwear", "Boxer shorts"),
        ),
    ),
)

RUNNING_APPAREL_DISPLAY_GROUPS: tuple[StorefrontDisplayGroup, ...] = (
    StorefrontDisplayGroup(
        "running-socks",
        "Носки",
        (
            CatalogRawSlice("Socks", "Running socks"),
            CatalogRawSlice("Socks", "High Socks"),
        ),
    ),
    StorefrontDisplayGroup(
        "headwear",
        "Головные уборы",
        (CatalogRawSlice("Headgear", "Headwear"),),
    ),
    StorefrontDisplayGroup(
        "gloves",
        "Перчатки",
        (CatalogRawSlice("Running accessories", "Gloves"),),
    ),
    StorefrontDisplayGroup(
        "neckwarmers",
        "Шейные повязки",
        (
            CatalogRawSlice("Scarves", "Neckwarmer"),
            CatalogRawSlice("Running clothes", "Neckwarmer"),
        ),
    ),
)

# L3 chips, скрытые в Running → accessories (перенесены в apparel display groups).
RUNNING_ACCESSORIES_ABSORBED_L3: frozenset[str] = frozenset(
    {
        "Gloves",
    }
)

_DISPLAY_BY_KEY: dict[str, StorefrontDisplayGroup] = {
    group.display_key: group
    for group in (*TENNIS_APPAREL_DISPLAY_GROUPS, *RUNNING_APPAREL_DISPLAY_GROUPS)
}

_LEGACY_SINGLE_SLICES: dict[str, CatalogRawSlice] = {
    "Panties": CatalogRawSlice("Underwear", "Panties"),
    "Slips": CatalogRawSlice("Underwear", "Slips"),
    "Strings": CatalogRawSlice("Underwear", "Strings"),
    "Boxer shorts": CatalogRawSlice("Underwear", "Boxer shorts"),
}

_LEGACY_GROUP_ALIASES: dict[str, str] = {
    "Sports Bras": "sports-bras",
}
