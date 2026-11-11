from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.catalog.display.placement_service import StorefrontPlacementService
from src.services.catalog.display.resolver import MappingRuleRow


@pytest.mark.asyncio
async def test_recompute_batch_loads_rules_once() -> None:
    session = MagicMock()
    svc = StorefrontPlacementService(session)
    rules = (
        MappingRuleRow(
            id=1,
            sport_type="Tennis",
            category_l1="Tennis",
            category_l2="Grips",
            category_l3=None,
            match_mode="l2_any_l3",
            priority=10,
            outcome="mapped",
            storefront_node_id=5,
        ),
    )
    svc.repo.load_rule_rows = AsyncMock(return_value=rules)
    passed_rules: list = []

    async def _spy(release_id: int, product_id: int, rules=None):
        passed_rules.append(rules)

    svc.recompute_product = _spy

    count = await svc.recompute_batch(1, [10, 11, 12])
    assert count == 3
    svc.repo.load_rule_rows.assert_awaited_once_with(1)
    assert len(passed_rules) == 3
    assert passed_rules[0] is rules
    assert passed_rules[1] is rules
