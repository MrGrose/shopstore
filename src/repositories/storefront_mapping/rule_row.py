from dataclasses import dataclass


@dataclass(frozen=True)
class MappingRuleRow:
    id: int
    sport_type: str
    category_l1: str | None
    category_l2: str | None
    category_l3: str | None
    match_mode: str
    priority: int
    outcome: str
    storefront_node_id: int | None
