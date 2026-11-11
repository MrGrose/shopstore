from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import (
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    ORDER_EVENT_CANCELLED_BY_CUSTOMER,
    OrderStatus,
)
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from src.web.admin_labels import CANCELLATION_REASON_LABELS, ORDER_EVENT_LABELS
from tests.unit.test_payment_attempts import _attempt, _order

RAIL_STEP_BODY_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src/templates/site/admin/partials/_order_action_rail_step_body.html"
)


def test_admin_labels_include_customer_cancel() -> None:
    assert CANCELLATION_REASON_LABELS["customer_request"] == "Отменён клиентом"
    assert ORDER_EVENT_LABELS["order_cancelled_by_customer"] == "Клиент отменил заказ"


def test_admin_order_detail_template_shows_customer_cancellation_reason() -> None:
    content = RAIL_STEP_BODY_TEMPLATE.read_text(encoding="utf-8")
    assert "customer_request" in content
    assert "отменён клиентом" in content


def test_evaluate_customer_cancel_allowed_for_unpaid_order() -> None:
    order = _order(status=OrderStatus.CREATED)
    allowed, reason = OrderService.evaluate_customer_cancel_allowed(order)
    assert allowed is True
    assert reason is None


def test_evaluate_customer_cancel_blocked_for_alive_qr() -> None:
    order = _order(status=OrderStatus.PROCESSING)
    alive = _attempt(provider_status="QRCDATA_CREATED")
    allowed, reason = OrderService.evaluate_customer_cancel_allowed(
        order,
        latest_attempt=alive,
    )
    assert allowed is False
    assert reason is not None
    assert "QR" in reason


def test_evaluate_customer_cancel_not_allowed_for_paid_order() -> None:
    order = _order(payment_paid_at=utc_now_naive())
    allowed, reason = OrderService.evaluate_customer_cancel_allowed(order)
    assert allowed is False
    assert reason is None


@pytest.mark.asyncio
async def test_cancel_order_by_customer_sets_status_and_reason() -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    service.session = AsyncMock()
    order = _order(status=OrderStatus.CREATED, user_id=10)
    order.id = 42
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.create_order_event = AsyncMock()
    service.order_crud.commit_order = AsyncMock()
    service._build_order_items = AsyncMock(return_value=[])
    service.session.get = AsyncMock(return_value=MagicMock(name="User"))
    service._build_order_schema = MagicMock(return_value=MagicMock())

    with patch("src.services.orders.order_service.CatalogStockService") as stock_cls:
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=MagicMock(boundary_flipped_ids=[])
        )
        with patch(
            "src.services.orders.order_service.invalidate_if_catalog_boundary_changed"
        ):
            await service.cancel_order_by_customer(order_id=42, user_id=10)

    assert order.status == OrderStatus.CANCELLED
    assert order.cancellation_reason == CANCELLATION_REASON_CUSTOMER_REQUEST
    service.order_crud.create_order_event.assert_awaited_once()
    event_kwargs = service.order_crud.create_order_event.await_args.kwargs
    assert event_kwargs["event_type"] == ORDER_EVENT_CANCELLED_BY_CUSTOMER
    assert event_kwargs["created_by"] == "user:10"


@pytest.mark.asyncio
async def test_cancel_order_by_customer_rejects_active_payment() -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    order = _order(status=OrderStatus.PROCESSING, user_id=10)
    order.id = 42
    alive = _attempt(provider_status="IN_PROCESS")
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=alive)

    with pytest.raises(ValueError, match="QR"):
        await service.cancel_order_by_customer(order_id=42, user_id=10)


@pytest.mark.asyncio
async def test_cancel_order_by_customer_rejects_wrong_user() -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="не найден"):
        await service.cancel_order_by_customer(order_id=42, user_id=10)


@pytest.mark.asyncio
async def test_cancel_order_by_customer_allows_after_qr_expired() -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    service.session = AsyncMock()
    order = _order(status=OrderStatus.CREATED, user_id=10)
    order.id = 42
    expired = _attempt(
        provider_status="QRCDATA_CREATED",
        qr_expires_at=utc_now_naive() - timedelta(minutes=1),
    )
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=expired)
    service.order_crud.count_payment_attempts = AsyncMock(return_value=1)
    service.order_crud.create_order_event = AsyncMock()
    service.order_crud.commit_order = AsyncMock()
    service._build_order_items = AsyncMock(return_value=[])
    service.session.get = AsyncMock(return_value=MagicMock(name="User"))
    service._build_order_schema = MagicMock(return_value=MagicMock())

    with patch("src.services.orders.order_service.CatalogStockService") as stock_cls:
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=MagicMock(boundary_flipped_ids=[])
        )
        with patch(
            "src.services.orders.order_service.invalidate_if_catalog_boundary_changed"
        ):
            await service.cancel_order_by_customer(order_id=42, user_id=10)

    assert order.status == OrderStatus.CANCELLED


@pytest.mark.parametrize(
    "boundary_flipped_ids",
    [
        pytest.param([], id="positive_stock"),
        pytest.param([42], id="restored_from_zero"),
    ],
)
@pytest.mark.asyncio
async def test_order_cancellation_does_not_run_pricing(
    boundary_flipped_ids: list[int],
) -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    service.session = AsyncMock()
    service.pricing_service = MagicMock(
        apply_pricing_to_product=AsyncMock(),
        verify_storefront_price=AsyncMock(),
    )
    order = _order(status=OrderStatus.CREATED, user_id=10)
    order.id = 42
    service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.create_order_event = AsyncMock()
    service.order_crud.commit_order = AsyncMock()
    service._build_order_items = AsyncMock(return_value=[])
    service.session.get = AsyncMock(return_value=MagicMock(name="User"))
    service._build_order_schema = MagicMock(return_value=MagicMock())

    with (
        patch("src.services.orders.order_service.CatalogStockService") as stock_cls,
        patch(
            "src.services.orders.order_service.invalidate_if_catalog_boundary_changed"
        ),
    ):
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=MagicMock(boundary_flipped_ids=boundary_flipped_ids)
        )
        await service.cancel_order_by_customer(order_id=42, user_id=10)

    service.pricing_service.apply_pricing_to_product.assert_not_awaited()
    service.pricing_service.verify_storefront_price.assert_not_awaited()
