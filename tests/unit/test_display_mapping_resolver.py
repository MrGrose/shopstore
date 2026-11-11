import pytest

from src.services.catalog.display.constants import (
    MATCH_MODE_EXACT,
    MATCH_MODE_L2_ANY_L3,
    OUTCOME_EXCLUDED,
    OUTCOME_MAPPED,
)
from src.services.catalog.display.resolver import DisplayMappingResolver, MappingRuleRow


def _rule(
    rule_id: int,
    *,
    outcome: str = OUTCOME_MAPPED,
    node_id: int | None = 1,
    l1: str | None = "Tennis",
    l2: str | None = "Grips",
    l3: str | None = "Overgrips",
    mode: str = MATCH_MODE_EXACT,
    priority: int = 0,
) -> MappingRuleRow:
    return MappingRuleRow(
        id=rule_id,
        sport_type="Tennis",
        category_l1=l1,
        category_l2=l2,
        category_l3=l3,
        match_mode=mode,
        priority=priority,
        outcome=outcome,
        storefront_node_id=node_id if outcome == OUTCOME_MAPPED else None,
    )


@pytest.fixture
def resolver() -> DisplayMappingResolver:
    return DisplayMappingResolver()


def test_tennis_overgrips_exact(resolver: DisplayMappingResolver) -> None:
    rules = (_rule(1, node_id=10),)
    result = resolver.resolve(
        1,
        "Tennis",
        "Tennis",
        "Grips",
        "Overgrips",
        rules,
    )
    assert result.status == "mapped"
    assert len(result.placements) == 1
    assert result.placements[0].storefront_node_id == 10


def test_l2_any_l3_coaching_equipment(resolver: DisplayMappingResolver) -> None:
    rules = (
        _rule(
            1,
            node_id=20,
            l2="Coaching equipment",
            l3=None,
            mode=MATCH_MODE_L2_ANY_L3,
        ),
    )
    result = resolver.resolve(
        1,
        "Tennis",
        "Tennis",
        "Coaching equipment",
        "Any subtype",
        rules,
    )
    assert result.status == "mapped"
    assert result.placements[0].storefront_node_id == 20


def test_excluded_beats_broad_mapped(resolver: DisplayMappingResolver) -> None:
    rules = (
        _rule(1, node_id=10, l2="Grips", l3="Overgrips", priority=10),
        _rule(
            2,
            outcome=OUTCOME_EXCLUDED,
            node_id=None,
            l2="Grips",
            l3="Overgrips",
            mode=MATCH_MODE_EXACT,
            priority=100,
        ),
    )
    result = resolver.resolve(1, "Tennis", "Tennis", "Grips", "Overgrips", rules)
    assert result.status == "excluded"
    assert result.placements == ()


def test_semantic_tie_mapping_error(resolver: DisplayMappingResolver) -> None:
    rules = (
        _rule(1, node_id=10, priority=5),
        _rule(
            2,
            outcome=OUTCOME_EXCLUDED,
            node_id=None,
            priority=5,
        ),
    )
    result = resolver.resolve(1, "Tennis", "Tennis", "Grips", "Overgrips", rules)
    assert result.status == "mapping_error"


def test_unmapped_no_rules(resolver: DisplayMappingResolver) -> None:
    result = resolver.resolve(1, "Tennis", "Tennis", "Unknown", None, ())
    assert result.status == "unmapped"


def test_one_path_many_nodes(resolver: DisplayMappingResolver) -> None:
    rules = (
        _rule(1, node_id=10, l2="Regular balls", l3=None, mode=MATCH_MODE_L2_ANY_L3),
        _rule(2, node_id=11, l2="Regular balls", l3=None, mode=MATCH_MODE_L2_ANY_L3),
    )
    result = resolver.resolve(1, "Tennis", "Tennis", "Regular balls", "X", rules)
    assert result.status == "mapped"
    assert len(result.placements) == 2


def test_exact_null_not_wildcard(resolver: DisplayMappingResolver) -> None:
    rules = (_rule(1, node_id=10, l3=None),)
    result = resolver.resolve(1, "Tennis", "Tennis", "Grips", "Overgrips", rules)
    assert result.status == "unmapped"
