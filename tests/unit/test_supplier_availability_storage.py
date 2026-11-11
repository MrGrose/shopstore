import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import settings
from src.services.orders.supplier_availability.client import StorageStateStatus
from src.services.orders.supplier_availability.service import (
    VERDICT_MANUAL,
    SupplierAvailabilityService,
    _ItemCheckTarget,
    compute_order_verdict,
)


def _target() -> _ItemCheckTarget:
    return _ItemCheckTarget(
        order_item_id=1,
        product_id=10,
        product_title=None,
        variant_label=None,
        product_url="https://www.supplier-demo.com/products/demo",
        variant_id="910001",
        sku="SKU-1",
        quantity=1,
        captured_price_eur=None,
    )


def test_manual_rows_when_storage_state_missing() -> None:
    service = SupplierAvailabilityService(MagicMock())
    targets = [_target()]
    rows = service._manual_rows_for_targets(
        targets,
        StorageStateStatus(ok=False, reason="storage_state_missing"),
    )
    assert compute_order_verdict(rows) == VERDICT_MANUAL
    assert rows[0]["check"].html_validation == "storage_state_missing"


def test_validate_storage_state_missing() -> None:
    from src.services.orders.supplier_availability.client import validate_storage_state

    with patch(
        "src.services.orders.supplier_availability.client.resolve_storage_state_path",
        return_value=None,
    ):
        status = validate_storage_state()
    assert status.ok is False
    assert status.reason == "storage_state_missing"


@pytest.mark.parametrize(
    "reason",
    ["storage_state_missing", "storage_state_corrupt", "storage_state_stale"],
)
def test_required_storage_state_failure_does_not_start_http(reason: str) -> None:
    service = SupplierAvailabilityService(MagicMock())
    with (
        patch.object(settings, "SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE", True),
        patch(
            "src.services.orders.supplier_availability.service.validate_storage_state",
            return_value=StorageStateStatus(ok=False, reason=reason),
        ),
        patch(
            "src.services.orders.supplier_availability.service.AsyncStealthSession"
        ) as session_factory,
    ):
        rows = asyncio.run(service._fetch_item_checks([_target()]))

    session_factory.assert_not_called()
    assert compute_order_verdict(rows) == VERDICT_MANUAL
    assert rows[0]["check"].html_validation == reason


def test_fetch_item_checks_without_storage_when_not_required() -> None:
    from src.services.orders.supplier_availability.client import (
        SupplierVariantCheckResult,
    )

    service = SupplierAvailabilityService(MagicMock())
    targets = [_target()]
    ok_check = SupplierVariantCheckResult(
        product_url=targets[0].product_url or "",
        requested_variant_id="910001",
        requested_sku="SKU-1",
        found=True,
        snapshot=None,
        session_valid=True,
        html_validation=None,
        http_status=200,
        latency_ms=10,
        challenge=None,
        error=None,
    )

    with (
        patch.object(settings, "SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE", False),
        patch(
            "src.services.orders.supplier_availability.service.validate_storage_state",
        ) as mock_validate,
        patch.object(
            service,
            "_fetch_single_item",
            new=AsyncMock(return_value=ok_check),
        ),
    ):
        rows = asyncio.run(service._fetch_item_checks(targets))

    mock_validate.assert_not_called()
    assert len(rows) == 1
    assert rows[0]["check"] is ok_check


def test_kill_switch_stops_before_order_or_http_access() -> None:
    service = SupplierAvailabilityService(MagicMock())
    service.order_crud.get_by_id_for_update = AsyncMock()
    with (
        patch.object(settings, "SUPPLIER_AVAILABILITY_ENABLED", False),
        patch(
            "src.services.orders.supplier_availability.service.AsyncStealthSession"
        ) as session_factory,
    ):
        result = asyncio.run(service.check_order(55))

    assert result == {"status": "disabled", "order_id": 55}
    service.order_crud.get_by_id_for_update.assert_not_awaited()
    session_factory.assert_not_called()
