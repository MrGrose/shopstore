from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.orders.supplier_availability.client import (
    SupplierVariantCheckResult,
    SupplierVariantSnapshot,
    fetch_supplier_variant,
)
from src.services.orders.supplier_availability.service import (
    SupplierAvailabilityService,
    _ItemCheckTarget,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "supplier_availability"


def _success_check() -> SupplierVariantCheckResult:
    return SupplierVariantCheckResult(
        product_url="https://www.supplier-demo.com/products/demo",
        requested_variant_id="910001",
        requested_sku="SKU-1",
        found=True,
        snapshot=SupplierVariantSnapshot(
            variant_id="910001",
            sku="SKU-1",
            available=True,
            inventory_quantity=4,
            current_price_eur="129.90",
            member_price_eur="119.90",
        ),
        session_valid=True,
        html_validation=None,
        http_status=200,
        latency_ms=120,
        challenge=None,
        error=None,
    )


@pytest.mark.asyncio
async def test_fetch_single_item_awaits_http_fetch() -> None:
    target = _ItemCheckTarget(
        order_item_id=1,
        product_id=10,
        product_title=None,
        variant_label=None,
        product_url="https://www.supplier-demo.com/products/demo",
        variant_id="910001",
        sku="SKU-1",
        quantity=1,
        captured_price_eur=Decimal("119.90"),
    )
    expected = _success_check()
    with patch(
        "src.services.orders.supplier_availability.service.fetch_supplier_variant",
        new_callable=AsyncMock,
    ) as fetch_mock:
        fetch_mock.return_value = expected
        result = await SupplierAvailabilityService._fetch_single_item(
            target,
            http_session=MagicMock(),
            retries=1,
            retry_pause_seconds=0,
        )
    assert result.found is True
    assert result.snapshot is not None
    fetch_mock.assert_awaited_once_with(
        product_url=target.product_url,
        variant_id="910001",
        sku="SKU-1",
        session=fetch_mock.await_args.kwargs["session"],
        use_storage_state=False,
    )


@pytest.mark.asyncio
async def test_fetch_single_item_uses_configured_retry_pause() -> None:
    target = _ItemCheckTarget(
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
    failed = SupplierVariantCheckResult(
        product_url=target.product_url or "",
        requested_variant_id=target.variant_id,
        requested_sku=target.sku,
        found=False,
        snapshot=None,
        session_valid=False,
        html_validation=None,
        http_status=None,
        latency_ms=10,
        challenge=None,
        error="TimeoutError",
    )
    with (
        patch(
            "src.services.orders.supplier_availability.service.fetch_supplier_variant",
            new_callable=AsyncMock,
        ) as fetch_mock,
        patch(
            "src.services.orders.supplier_availability.service.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep_mock,
    ):
        fetch_mock.side_effect = [failed, _success_check()]
        result = await SupplierAvailabilityService._fetch_single_item(
            target,
            http_session=MagicMock(),
            retries=2,
            retry_pause_seconds=0.25,
        )

    assert result.found is True
    sleep_mock.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_fetch_supplier_variant_without_storage_uses_no_cookies() -> None:
    product_json = (FIXTURES / "product_ok.json").read_text(encoding="utf-8")
    html = (FIXTURES / "pdp_ok.html").read_text(encoding="utf-8")
    json_response = MagicMock(status_code=200, text=product_json)
    html_response = MagicMock(status_code=200, text=html)
    http_session = MagicMock()
    http_session.get = AsyncMock(side_effect=[json_response, html_response])

    with patch(
        "src.services.orders.supplier_availability.client.load_storage_state_cookies"
    ) as load_cookies:
        result = await fetch_supplier_variant(
            product_url="https://www.supplier-demo.com/products/demo",
            variant_id="910001",
            sku="SKU-1",
            session=http_session,
            use_storage_state=False,
        )

    load_cookies.assert_not_called()
    assert http_session.get.await_count == 2
    assert result.found is True
