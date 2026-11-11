from dataclasses import dataclass

from src.services.catalog.categories.l2_sets import (
    BAGS_PADEL_NAV_L2,
    BAGS_TENNIS_NAV_L2,
    PADEL_ACCESSORIES_NAV_L2,
    PADEL_APPAREL_NAV_L2,
    PADEL_RACKET_L2,
    RUNNING_ACCESSORIES_NAV_L2,
    RUNNING_APPAREL_NAV_L2,
    TENNIS_ACCESSORIES_NAV_L2,
    TENNIS_APPAREL_NAV_L2,
    TENNIS_RACKET_L2,
)
from src.services.catalog.read.scope import CATALOG_TOP_ORDER
from src.utils.labels import TENNIS_SHOE_SUBTYPE_L3, TENNIS_SHOES_BASE_L2


@dataclass(frozen=True)
class CatalogSubCategoryDef:
    slug: str
    label: str
    category_l2: tuple[str, ...]


_SUBCATEGORIES_BY_SPORT: dict[str, tuple[CatalogSubCategoryDef, ...]] = {
    "Padel": (
        CatalogSubCategoryDef("rackets", "Ракетки", PADEL_RACKET_L2),
        CatalogSubCategoryDef("apparel", "Одежда", PADEL_APPAREL_NAV_L2),
        CatalogSubCategoryDef("shoes", "Обувь", ("Padel shoes", "Shoes")),
        CatalogSubCategoryDef("balls", "Мячи", ("Padel balls", "Giant balls")),
        CatalogSubCategoryDef("bags", "Сумки", BAGS_PADEL_NAV_L2),
        CatalogSubCategoryDef(
            "accessories",
            "Аксессуары",
            PADEL_ACCESSORIES_NAV_L2,
        ),
    ),
    "Tennis": (
        CatalogSubCategoryDef("rackets", "Ракетки", TENNIS_RACKET_L2),
        CatalogSubCategoryDef("apparel", "Одежда", TENNIS_APPAREL_NAV_L2),
        CatalogSubCategoryDef(
            "shoes",
            "Обувь",
            (
                *TENNIS_SHOES_BASE_L2,
                "Trainers",
                *tuple(sorted(TENNIS_SHOE_SUBTYPE_L3)),
            ),
        ),
        CatalogSubCategoryDef("bags", "Сумки", BAGS_TENNIS_NAV_L2),
        CatalogSubCategoryDef("balls", "Мячи", ("Tennis balls", "Giant balls")),
        CatalogSubCategoryDef("strings", "Струны", ("String sets", "String reels")),
        CatalogSubCategoryDef(
            "accessories",
            "Аксессуары",
            TENNIS_ACCESSORIES_NAV_L2,
        ),
    ),
    "Running": (
        CatalogSubCategoryDef("shoes", "Обувь", ("Running shoes", "Shoes")),
        CatalogSubCategoryDef("apparel", "Одежда", RUNNING_APPAREL_NAV_L2),
        CatalogSubCategoryDef(
            "accessories",
            "Аксессуары",
            RUNNING_ACCESSORIES_NAV_L2,
        ),
    ),
}

CATALOG_SUBCATEGORIES: dict[str, tuple[CatalogSubCategoryDef, ...]] = {
    sport: _SUBCATEGORIES_BY_SPORT[sport] for sport in CATALOG_TOP_ORDER
}
