from dataclasses import dataclass

from src.models.pricing import MarginRule
from src.services.pricing.groups import (
    FALLBACK_SUBCATEGORY_SLUG,
    PricingGroupResolution,
    resolve_pricing_group,
)


@dataclass(frozen=True)
class ResolvedMarginRule:
    rule: MarginRule
    group: PricingGroupResolution
    category_key: str
    fallback_reason: str | None


# Собирает ключ pricing snapshot из спорта и storefront slug.
def pricing_category_key(sport_type: str, subcategory_slug: str) -> str:
    return f"{sport_type}:{subcategory_slug}"


# Разрешает активное exact-правило или fallback текущего спорта.
def resolve_margin_rule(
    sport_type: str | None,
    category_l2: str | None,
    rules: list[MarginRule],
) -> ResolvedMarginRule:
    group = resolve_pricing_group(sport_type, category_l2)
    active_by_key = {
        (rule.sport_type, rule.subcategory_slug): rule
        for rule in rules
        if rule.is_active
    }
    exact_rule = active_by_key.get((group.sport_type, group.subcategory_slug))
    if group.is_exact and exact_rule is not None:
        return ResolvedMarginRule(
            rule=exact_rule,
            group=group,
            category_key=pricing_category_key(
                exact_rule.sport_type, exact_rule.subcategory_slug
            ),
            fallback_reason=None,
        )

    fallback = active_by_key.get((group.sport_type, FALLBACK_SUBCATEGORY_SLUG))
    if fallback is None:
        raise ValueError(
            f"Активное fallback-правило не найдено для спорта {group.sport_type!r}"
        )
    reason = group.reason or "exact_rule_inactive"
    return ResolvedMarginRule(
        rule=fallback,
        group=group,
        category_key=pricing_category_key(
            fallback.sport_type, fallback.subcategory_slug
        ),
        fallback_reason=reason,
    )
