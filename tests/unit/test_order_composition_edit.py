from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.schemas.order import AdminAvailabilityItemDecision
from src.services.orders.order_service import OrderService


def test_supplier_cost_eur_from_items_uses_captured_prices() -> None:
    items = [
        type(
            "Item", (), {"supplier_price_eur_captured": Decimal("100"), "quantity": 2}
        )(),
        type(
            "Item", (), {"supplier_price_eur_captured": Decimal("15.5"), "quantity": 1}
        )(),
    ]
    assert OrderService._supplier_cost_eur_from_items(items) == Decimal("215.50")


@pytest.mark.asyncio
async def test_validate_availability_decisions_rejects_partial() -> None:
    service = OrderService.__new__(OrderService)
    service._resolve_pending_availability_rows = AsyncMock(
        return_value=[
            {"order_item": type("Item", (), {"id": 10})()},
            {"order_item": type("Item", (), {"id": 11})()},
        ]
    )
    with pytest.raises(ValueError, match="каждой проверяемой"):
        await service._validate_availability_decisions(
            1,
            [AdminAvailabilityItemDecision(order_item_id=10, confirmed=True)],
        )


@pytest.mark.asyncio
async def test_validate_availability_decisions_rejects_foreign_item() -> None:
    service = OrderService.__new__(OrderService)
    service._resolve_pending_availability_rows = AsyncMock(
        return_value=[{"order_item": type("Item", (), {"id": 10})()}]
    )
    with pytest.raises(ValueError, match="не входит"):
        await service._validate_availability_decisions(
            1,
            [AdminAvailabilityItemDecision(order_item_id=99, confirmed=True)],
        )
