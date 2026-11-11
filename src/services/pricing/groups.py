from dataclasses import dataclass

from src.services.catalog.display.pricing_nav_registry import CATALOG_SUBCATEGORIES

FALLBACK_SUBCATEGORY_SLUG = "__fallback__"


@dataclass(frozen=True)
class PricingGroup:
    sport_type: str
    subcategory_slug: str
    label: str
    category_l2: tuple[str, ...]


@dataclass(frozen=True)
class PricingGroupResolution:
    sport_type: str
    subcategory_slug: str
    matched_subcategory_slugs: tuple[str, ...]
    reason: str | None = None

    @property
    # Показывает, что товар однозначно попал в точную storefront-группу.
    def is_exact(self) -> bool:
        return self.reason is None


# Возвращает pricing-группы прямо из storefront registry.
def iter_pricing_groups() -> tuple[PricingGroup, ...]:
    return tuple(
        PricingGroup(
            sport_type=sport_type,
            subcategory_slug=subcategory.slug,
            label=subcategory.label,
            category_l2=subcategory.category_l2,
        )
        for sport_type, subcategories in CATALOG_SUBCATEGORIES.items()
        for subcategory in subcategories
    )


# Разрешает exact-группу или fallback с причиной.
def resolve_pricing_group(
    sport_type: str | None,
    category_l2: str | None,
) -> PricingGroupResolution:
    normalized_sport = (sport_type or "").strip()
    normalized_l2 = (category_l2 or "").strip()
    subcategories = CATALOG_SUBCATEGORIES.get(normalized_sport)
    if not subcategories:
        return PricingGroupResolution(
            sport_type=normalized_sport,
            subcategory_slug=FALLBACK_SUBCATEGORY_SLUG,
            matched_subcategory_slugs=(),
            reason="sport_not_in_storefront",
        )

    matches = tuple(
        subcategory.slug
        for subcategory in subcategories
        if normalized_l2 in subcategory.category_l2
    )
    if len(matches) == 1:
        return PricingGroupResolution(
            sport_type=normalized_sport,
            subcategory_slug=matches[0],
            matched_subcategory_slugs=matches,
        )

    reason = "multiple_storefront_groups" if matches else "no_storefront_group"
    return PricingGroupResolution(
        sport_type=normalized_sport,
        subcategory_slug=FALLBACK_SUBCATEGORY_SLUG,
        matched_subcategory_slugs=matches,
        reason=reason,
    )
