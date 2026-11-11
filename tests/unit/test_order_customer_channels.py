from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import Order
from src.models.user import User
from src.schemas.order import AdminOrderStatusUpdate, DeliveryAddressCreate
from src.services.orders.order_service import OrderService

OS = "src.services.orders.order_service"
NO_TELEGRAM_MSG = "У заказа нет привязанного Telegram"


def _order_stub(
    order_id: int = 1,
    user_id: int = 10,
    status: str = "created",
    customer_data_json: dict | None = None,
) -> Order:
    order = MagicMock(spec=Order)
    order.id = order_id
    order.user_id = user_id
    order.status = status
    order.availability_confirmation_status = "not_required"
    order.customer_data_json = customer_data_json
    order.total_amount = Decimal("100")
    order.items_subtotal_amount = Decimal("100")
    order.discount_items_amount = Decimal("0")
    order.delivery_fee_amount = Decimal("0")
    order.eur_rate_snapshot = Decimal("100")
    order.promo_code_applied = None
    order.last_name = None
    order.first_name = None
    order.street = None
    order.house = None
    order.apartment = None
    order.city = None
    order.postal_code = None
    order.phone = "+79991234567"
    order.notification_channels = ["telegram"]
    order.notification_email = None
    order.payment_provider = None
    order.payment_order_id = None
    order.payment_status = None
    order.payment_qr_id = None
    order.payment_qr_payload = None
    order.payment_paid_at = None
    order.payment_due_at = None
    order.payment_meta_json = {}
    order.cancellation_reason = None
    order.supplier_order_id = None
    order.supplier_tracking_id = None
    order.failed_from_status = None
    order.created_at = None
    order.updated_at = None
    return order


@pytest.fixture
def order_service() -> OrderService:
    session = AsyncMock()
    service = OrderService(session)
    service.order_crud = AsyncMock()
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    return service


@pytest.mark.asyncio
async def test_build_customer_data_json_uses_profile_email(
    order_service: OrderService,
) -> None:
    user = User(id=10, email="profile@test", name="User")
    order_service.session.get = AsyncMock(return_value=user)

    with (
        patch(
            f"{OS}.IdentityService.get_telegram_id_for_user",
            new_callable=AsyncMock,
            return_value=123,
        ),
        patch(
            f"{OS}.IdentityService.get_telegram_username_for_user",
            new_callable=AsyncMock,
            return_value="tg_user",
        ),
    ):
        snapshot = await order_service._build_customer_data_json(
            10,
            DeliveryAddressCreate(
                last_name="Ivanov",
                first_name="Ivan",
                street="Test",
                house="1",
                city="Moscow",
                postal_code="101000",
                phone="+79991234567",
            ),
        )

    assert snapshot is not None
    assert snapshot["email"] == "profile@test"
    assert snapshot["telegram_id"] == 123
    assert snapshot["telegram_username"] == "tg_user"


def test_build_order_schema_exposes_telegram_fields(
    order_service: OrderService,
) -> None:
    order = _order_stub()
    user = User(id=10, email="profile@test", name="User")

    schema = order_service._build_order_schema(
        order,
        [],
        user=user,
        user_telegram_id=123456,
        user_telegram_username="tg_user",
    )

    assert schema.user_name == "User"
    assert schema.user_telegram_id == 123456
    assert schema.user_telegram_username == "tg_user"


@pytest.mark.asyncio
async def test_send_customer_telegram_message_without_telegram_raises(
    order_service: OrderService,
) -> None:
    order = _order_stub()
    order_service.order_crud.get_by_id.return_value = order
    user = User(id=10, email="e@test", name="User")
    order_service.session.get = AsyncMock(return_value=user)

    with patch(
        f"{OS}.IdentityService.get_telegram_id_for_user",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(ValueError, match=NO_TELEGRAM_MSG):
            await order_service.send_customer_telegram_message(1, "Привет")


@pytest.mark.asyncio
async def test_send_customer_telegram_message_with_telegram_calls_notify(
    order_service: OrderService,
) -> None:
    order = _order_stub()
    order_service.order_crud.get_by_id.return_value = order
    user = User(id=10, email="e@test", name="User")
    order_service.session.get = AsyncMock(return_value=user)
    order_service._build_admin_created_by = AsyncMock(return_value="admin")

    enqueue_mock = AsyncMock(return_value=True)
    commit_mock = AsyncMock()

    with (
        patch(
            f"{OS}.IdentityService.get_telegram_id_for_user",
            new_callable=AsyncMock,
            return_value=123456,
        ),
        patch(f"{OS}.notification_dispatcher") as dispatcher_cls,
        patch.object(order_service, "_commit_enqueued_notifications", commit_mock),
    ):
        dispatcher_cls.return_value.enqueue = enqueue_mock
        await order_service.send_customer_telegram_message(1, "Привет")

    enqueue_mock.assert_awaited_once()
    dispatch = enqueue_mock.await_args.args[1]
    assert dispatch.template == "customer.manual"
    assert dispatch.payload["order_id"] == 1
    assert dispatch.payload["message"] == "Привет"
    assert dispatch.payload["force_channel"] == "telegram"
    assert dispatch.record_order_event is not None
    assert dispatch.record_order_event.event_message == "Ручное сообщение клиенту"
    assert dispatch.record_order_event.payload_json == {
        "manual": True,
        "channel": "telegram",
    }
    commit_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_order_status_notify_without_telegram_does_not_raise(
    order_service: OrderService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order_stub(status="created")
    order_service.order_crud.get_by_id.return_value = order
    order_service._build_order_items = AsyncMock(return_value=[])
    order_service._build_admin_created_by = AsyncMock(return_value="admin")
    order_service._telegram_fields_for_user = AsyncMock(return_value=(None, None))
    monkeypatch.setattr(
        "src.services.orders.order_service.IdentityService.get_phone_e164_for_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        f"{OS}.DeliveryProfileService",
        lambda session: MagicMock(get_profile=AsyncMock(return_value=None)),
    )
    order_service.session.get = AsyncMock(
        return_value=User(id=10, email="e@test", name="User")
    )
    order_service.session.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    order_service._telegram_fields_for_user = AsyncMock(return_value=(None, None))

    notify_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(
        f"{OS}.CatalogStockService",
        lambda session: MagicMock(refresh_for_order=AsyncMock()),
    )
    monkeypatch.setattr(
        f"{OS}.CustomerNotificationService",
        lambda session: MagicMock(notify_order_status=notify_mock),
    )

    result = await order_service.update_order_status(
        1,
        AdminOrderStatusUpdate(status="cancelled", notify_customer=True),
    )

    assert result.user_telegram_id is None
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_order_status_same_status_saves_admin_comment(
    order_service: OrderService,
) -> None:
    order = _order_stub(status="processing")
    order_service.order_crud.get_by_id.return_value = order
    order_service._build_order_items = AsyncMock(return_value=[])
    order_service._build_admin_created_by = AsyncMock(return_value="admin")
    order_service._build_order_schema_with_user = AsyncMock(return_value=MagicMock())
    order_service.session.get = AsyncMock(
        return_value=User(id=10, email="e@test", name="User")
    )

    await order_service.update_order_status(
        1,
        AdminOrderStatusUpdate(
            status="processing",
            event_message="Позвонил поставщику",
        ),
    )

    order_service.order_crud.create_order_event.assert_awaited_once()
    call = order_service.order_crud.create_order_event.await_args.kwargs
    assert call["event_type"] == "admin_comment"
    assert call["event_message"] == "Позвонил поставщику"
    order_service.session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_send_customer_telegram_message_rejects_cancelled_order(
    order_service: OrderService,
) -> None:
    order = _order_stub(status="cancelled")
    order_service.order_crud.get_by_id = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="финальном статусе"):
        await order_service.send_customer_telegram_message(
            1,
            message="Повторное сообщение",
            actor=None,
        )


@pytest.mark.asyncio
async def test_add_admin_order_comment_persists_event(
    order_service: OrderService,
) -> None:
    order = _order_stub(status="processing")
    order_service.order_crud.get_by_id.return_value = order
    order_service._build_admin_created_by = AsyncMock(return_value="admin")

    await order_service.add_admin_order_comment(1, "  Заметка  ")

    order_service.order_crud.create_order_event.assert_awaited_once()
    assert (
        order_service.order_crud.create_order_event.await_args.kwargs["event_message"]
        == "Заметка"
    )
    order_service.session.commit.assert_awaited()
