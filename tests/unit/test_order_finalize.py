from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import OrderStatus
from src.schemas.order import AdminOrderStatusUpdate
from src.services.catalog.stock.service import RefreshStockResult
from src.services.orders.order_service import (
    ORDER_FINALIZE_CUSTOMER_NOTIFY_KEY,
    OrderService,
)

OS = "src.services.orders.order_service"
REFERRAL = f"{OS}.ReferralService"
NOTIFY = f"{OS}.CustomerNotificationService"


def _delivery_order(order_id: int = 42, user_id: int = 10) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.user_id = user_id
    order.status = OrderStatus.DELIVERY
    order.availability_confirmation_status = "confirmed"
    order.total_amount = Decimal("1000")
    order.items_subtotal_amount = Decimal("1000")
    order.discount_items_amount = Decimal("0")
    order.delivery_fee_amount = Decimal("0")
    order.eur_rate_snapshot = Decimal("100")
    order.promo_code_applied = None
    order.payment_paid_at = None
    order.payment_provider = None
    order.payment_order_id = None
    order.payment_status = None
    order.payment_qr_id = None
    order.payment_qr_payload = None
    order.payment_due_at = None
    order.payment_meta_json = {}
    order.cancellation_reason = None
    order.supplier_order_id = "TP-1"
    order.supplier_tracking_id = "CJ-1"
    order.failed_from_status = None
    order.created_at = None
    order.updated_at = None
    order.last_name = None
    order.first_name = None
    order.street = None
    order.house = None
    order.apartment = None
    order.city = None
    order.postal_code = None
    order.phone = "+79991234567"
    order.customer_data_json = None
    return order


@pytest.fixture
def order_service() -> OrderService:
    session = AsyncMock()
    service = OrderService(session)
    service.order_crud = AsyncMock()
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    service._build_order_items = AsyncMock(return_value=[])
    service._build_order_schema_with_user = AsyncMock(return_value=MagicMock())
    service._build_admin_created_by = AsyncMock(return_value="admin@test")
    service.session.get = AsyncMock(return_value=MagicMock(id=10))
    return service


@pytest.mark.asyncio
async def test_finalize_success_from_delivery(order_service: OrderService) -> None:
    order = _delivery_order()
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    notify_mock = AsyncMock(return_value=True)
    accrue_mock = AsyncMock(return_value=None)
    stock_mock = MagicMock(
        refresh_for_order=AsyncMock(return_value=RefreshStockResult())
    )

    with (
        patch(f"{OS}.CatalogStockService", return_value=stock_mock),
        patch(REFERRAL) as referral_cls,
        patch(NOTIFY) as notify_cls,
        patch(
            f"{OS}.sync_order_completed_admin_alert", AsyncMock(return_value=True)
        ) as completed_alert,
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
    ):
        referral_cls.return_value.accrue_for_order = accrue_mock
        notify_cls.return_value.notify_order_status = notify_mock
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED, notify_customer=True),
        )

    assert order.status == OrderStatus.COMPLETED
    order_service.order_crud.create_order_event.assert_awaited_once()
    event_kwargs = order_service.order_crud.create_order_event.await_args.kwargs
    assert event_kwargs["event_type"] == "delivered_to_customer"
    accrue_mock.assert_awaited_once_with(order)
    notify_mock.assert_awaited_once()
    assert notify_mock.await_args.kwargs["idempotency_key"] == (
        ORDER_FINALIZE_CUSTOMER_NOTIFY_KEY.format(order_id=42)
    )
    order_service.session.commit.assert_awaited_once()
    completed_alert.assert_awaited_once()
    order_service.order_crud.get_by_id.assert_awaited()
    assert order_service.order_crud.get_by_id.await_count >= 2


@pytest.mark.asyncio
async def test_build_order_schema_refreshes_expired_order_before_sync_build(
    order_service: OrderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _delivery_order()
    order_service._telegram_fields_for_user = AsyncMock(return_value=(None, None))
    order_service._build_order_schema = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(
        "src.services.orders.order_service.IdentityService.get_phone_e164_for_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        f"{OS}.DeliveryProfileService",
        lambda session: MagicMock(get_profile=AsyncMock(return_value=None)),
    )

    await OrderService._build_order_schema_with_user(
        order_service,
        order,
        [],
        MagicMock(id=order.user_id),
        payment_attempts_used=0,
    )

    order_service.session.refresh.assert_awaited_once_with(order)
    order_service._build_order_schema.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_refetches_order_after_commit(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    build_schema_mock = AsyncMock(return_value=MagicMock())

    with (
        patch(f"{OS}.CatalogStockService") as stock_cls,
        patch(REFERRAL) as referral_cls,
        patch(NOTIFY) as notify_cls,
        patch(f"{OS}.sync_order_completed_admin_alert", AsyncMock(return_value=True)),
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
        patch.object(
            order_service,
            "_build_order_schema_for_user",
            build_schema_mock,
        ),
    ):
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=RefreshStockResult()
        )
        referral_cls.return_value.accrue_for_order = AsyncMock(return_value=None)
        notify_cls.return_value.notify_order_status = AsyncMock(return_value=True)
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED),
        )

    build_schema_mock.assert_awaited_once_with(42, 10)


@pytest.mark.asyncio
async def test_finalize_rejects_non_delivery(order_service: OrderService) -> None:
    order = _delivery_order()
    order.status = OrderStatus.ASSEMBLING
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="доставке"):
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED),
        )


@pytest.mark.asyncio
async def test_finalize_idempotent_when_already_completed(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.COMPLETED
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    build_schema_mock = AsyncMock(return_value=MagicMock())
    order_service._build_order_schema_for_user = build_schema_mock

    with patch(NOTIFY) as notify_cls:
        notify_cls.return_value.notify_order_status = AsyncMock(return_value=True)
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED, notify_customer=False),
        )

    order_service.order_crud.create_order_event.assert_not_awaited()
    notify_cls.return_value.notify_order_status.assert_not_awaited()
    build_schema_mock.assert_awaited_once_with(42, 10)


@pytest.mark.asyncio
async def test_finalize_idempotent_rejects_repeat_notify(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.COMPLETED
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="уже выполнен"):
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED, notify_customer=True),
        )


@pytest.mark.asyncio
async def test_finalize_idempotent_without_notify_skips_commit(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.COMPLETED
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)

    await order_service.update_order_status(
        42,
        AdminOrderStatusUpdate(status=OrderStatus.COMPLETED, notify_customer=False),
    )

    order_service.order_crud.create_order_event.assert_not_awaited()
    order_service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_notify_checkbox_off(order_service: OrderService) -> None:
    order = _delivery_order()
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    notify_mock = AsyncMock(return_value=True)

    with (
        patch(f"{OS}.CatalogStockService") as stock_cls,
        patch(REFERRAL) as referral_cls,
        patch(NOTIFY) as notify_cls,
        patch(f"{OS}.sync_order_completed_admin_alert", AsyncMock(return_value=True)),
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
    ):
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=RefreshStockResult()
        )
        referral_cls.return_value.accrue_for_order = AsyncMock(return_value=None)
        notify_cls.return_value.notify_order_status = notify_mock
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED, notify_customer=False),
        )

    notify_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_outbox_enqueue_error_rolls_back(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)

    with (
        patch(f"{OS}.CatalogStockService") as stock_cls,
        patch(REFERRAL) as referral_cls,
        patch(NOTIFY) as notify_cls,
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
    ):
        stock_cls.return_value.refresh_for_order = AsyncMock(
            return_value=RefreshStockResult()
        )
        referral_cls.return_value.accrue_for_order = AsyncMock(return_value=None)
        notify_cls.return_value.notify_order_status = AsyncMock(
            side_effect=RuntimeError("outbox down")
        )
        with pytest.raises(RuntimeError, match="outbox down"):
            await order_service.update_order_status(
                42,
                AdminOrderStatusUpdate(
                    status=OrderStatus.COMPLETED,
                    notify_customer=True,
                ),
            )

    assert order.status == OrderStatus.COMPLETED
    order_service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_failed_delivery_then_finalize(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.FAILED
    order.failed_from_status = OrderStatus.DELIVERY
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.commit_order = AsyncMock(return_value=order)
    order_service.order_crud.create_order_event = AsyncMock()
    stock_mock = MagicMock(
        refresh_for_order=AsyncMock(return_value=RefreshStockResult())
    )

    with (
        patch(f"{OS}.CatalogStockService", return_value=stock_mock),
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
    ):
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.DELIVERY),
        )

    assert order.status == OrderStatus.DELIVERY
    assert order.failed_from_status is None

    order_service.order_crud.get_by_id = AsyncMock(return_value=order)
    order_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    with (
        patch(f"{OS}.CatalogStockService", return_value=stock_mock),
        patch(REFERRAL) as referral_cls,
        patch(NOTIFY) as notify_cls,
        patch(f"{OS}.sync_order_completed_admin_alert", AsyncMock(return_value=True)),
        patch(f"{OS}.invalidate_if_catalog_boundary_changed"),
    ):
        referral_cls.return_value.accrue_for_order = AsyncMock(return_value=None)
        notify_cls.return_value.notify_order_status = AsyncMock(return_value=True)
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(status=OrderStatus.COMPLETED),
        )

    assert order.status == OrderStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancelled_order_rejects_repeat_status_notify(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.CANCELLED
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="финальном статусе"):
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(
                status=OrderStatus.CANCELLED,
                notify_customer=True,
            ),
        )


@pytest.mark.asyncio
async def test_failed_order_rejects_repeat_status_notify(
    order_service: OrderService,
) -> None:
    order = _delivery_order()
    order.status = OrderStatus.FAILED
    order.failed_from_status = OrderStatus.DELIVERY
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="финальном статусе"):
        await order_service.update_order_status(
            42,
            AdminOrderStatusUpdate(
                status=OrderStatus.FAILED,
                notify_customer=True,
            ),
        )
