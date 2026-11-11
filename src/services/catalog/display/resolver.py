import hashlib
import json
from dataclasses import dataclass

from src.repositories.storefront_mapping.rule_row import MappingRuleRow
from src.services.catalog.display.constants import (
    MATCH_MODE_EXACT,
    MATCH_MODE_L2_ANY_L3,
    OUTCOME_EXCLUDED,
    OUTCOME_MAPPED,
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_MAPPING_ERROR,
    RESOLUTION_UNMAPPED,
    RESOLVER_VERSION,
)


@dataclass(frozen=True)
class ChipPlacement:
    storefront_node_id: int
    mapping_rule_id: int


@dataclass(frozen=True)
class ResolverResult:
    status: str
    placements: tuple[ChipPlacement, ...]
    reason: str | None
    resolver_hash: str


def _null_safe_equal(rule_val: str | None, product_val: str | None) -> bool:
    if rule_val is None:
        return product_val is None
    return rule_val == product_val


# Считает specificity rule по non-NULL path fields.
def rule_specificity(rule: MappingRuleRow) -> int:
    count = 1
    if rule.category_l1 is not None:
        count += 1
    if rule.category_l2 is not None:
        count += 1
    if rule.category_l3 is not None:
        count += 1
    return count


# Проверяет match rule с product path.
def rule_matches_product(
    rule: MappingRuleRow,
    sport_type: str,
    category_l1: str | None,
    category_l2: str | None,
    category_l3: str | None,
) -> bool:
    if rule.sport_type != sport_type:
        return False
    if rule.match_mode == MATCH_MODE_EXACT:
        return (
            _null_safe_equal(rule.category_l1, category_l1)
            and _null_safe_equal(rule.category_l2, category_l2)
            and _null_safe_equal(rule.category_l3, category_l3)
        )
    if rule.match_mode == MATCH_MODE_L2_ANY_L3:
        if rule.category_l3 is not None:
            return False
        return _null_safe_equal(rule.category_l1, category_l1) and _null_safe_equal(
            rule.category_l2, category_l2
        )
    return False


def _semantic_rank(rule: MappingRuleRow) -> tuple[int, int]:
    return (rule_specificity(rule), rule.priority)


def _rule_sort_key(rule: MappingRuleRow) -> tuple[int, int, int]:
    spec, prio = _semantic_rank(rule)
    return (spec, prio, rule.id)


# Строит resolver_hash для release rules snapshot + product path.
def build_resolver_hash(
    release_id: int,
    rules: tuple[MappingRuleRow, ...],
    sport_type: str,
    category_l1: str | None,
    category_l2: str | None,
    category_l3: str | None,
) -> str:
    payload = {
        "version": RESOLVER_VERSION,
        "release_id": release_id,
        "path": [sport_type, category_l1, category_l2, category_l3],
        "rules": [
            (
                r.id,
                r.sport_type,
                r.match_mode,
                r.outcome,
                r.category_l1,
                r.category_l2,
                r.category_l3,
                r.storefront_node_id,
                r.priority,
            )
            for r in rules
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DisplayMappingResolver:
    # Резолвит supplier path в chip placements и mapping status.
    def resolve(
        self,
        release_id: int,
        sport_type: str,
        category_l1: str | None,
        category_l2: str | None,
        category_l3: str | None,
        rules: tuple[MappingRuleRow, ...],
    ) -> ResolverResult:
        active_rules = tuple(r for r in rules if r.sport_type == sport_type)
        resolver_hash = build_resolver_hash(
            release_id,
            active_rules,
            sport_type,
            category_l1,
            category_l2,
            category_l3,
        )
        matching = tuple(
            r
            for r in active_rules
            if rule_matches_product(
                r, sport_type, category_l1, category_l2, category_l3
            )
        )
        if not matching:
            return ResolverResult(
                status=RESOLUTION_UNMAPPED,
                placements=(),
                reason="no matching rules",
                resolver_hash=resolver_hash,
            )

        mapped_rules = [r for r in matching if r.outcome == OUTCOME_MAPPED]
        excluded_rules = [r for r in matching if r.outcome == OUTCOME_EXCLUDED]

        best_by_node: dict[int, MappingRuleRow] = {}
        for rule in mapped_rules:
            if rule.storefront_node_id is None:
                continue
            node_id = rule.storefront_node_id
            prev = best_by_node.get(node_id)
            if prev is None or _rule_sort_key(rule) > _rule_sort_key(prev):
                best_by_node[node_id] = rule

        best_mapped_semantic: tuple[int, int] | None = None
        if best_by_node:
            best_mapped_semantic = max(_semantic_rank(r) for r in best_by_node.values())

        best_excluded: MappingRuleRow | None = None
        if excluded_rules:
            best_excluded = max(excluded_rules, key=_rule_sort_key)
        excluded_semantic = _semantic_rank(best_excluded) if best_excluded else None

        if best_excluded and best_mapped_semantic is None:
            return ResolverResult(
                status=RESOLUTION_EXCLUDED,
                placements=(),
                reason=f"excluded by rule {best_excluded.id}",
                resolver_hash=resolver_hash,
            )

        if (
            best_excluded
            and excluded_semantic is not None
            and best_mapped_semantic is not None
        ):
            if excluded_semantic > best_mapped_semantic:
                return ResolverResult(
                    status=RESOLUTION_EXCLUDED,
                    placements=(),
                    reason=f"excluded by rule {best_excluded.id}",
                    resolver_hash=resolver_hash,
                )
            if excluded_semantic == best_mapped_semantic:
                return ResolverResult(
                    status=RESOLUTION_MAPPING_ERROR,
                    placements=(),
                    reason="mapped/excluded semantic rank tie",
                    resolver_hash=resolver_hash,
                )

        if best_by_node:
            placements = tuple(
                ChipPlacement(
                    storefront_node_id=node_id,
                    mapping_rule_id=rule.id,
                )
                for node_id, rule in sorted(best_by_node.items())
            )
            return ResolverResult(
                status=RESOLUTION_MAPPED,
                placements=placements,
                reason=None,
                resolver_hash=resolver_hash,
            )

        return ResolverResult(
            status=RESOLUTION_UNMAPPED,
            placements=(),
            reason="no mapped nodes after precedence",
            resolver_hash=resolver_hash,
        )
