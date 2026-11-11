import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.content.admin_texts import (
    delivered_alert_snapshot_hash,
    format_admin_delivered_alert_message,
    placed_delivered_alert_snapshot_hash,
)
from src.integrations.telegram_client import TelegramSendResult
from src.models.order import OrderStatus, ShipmentStatus
from src.services.admin_notification_service import (
    ADMIN_DELIVERED_ALERT_KEY,
    AdminNotificationService,
    sync_delivered_alert_after_tracking_check,
    sync_shipment_delivered_alert,
)
from src.services.orders.shipments import build_dhl_public_tracking_url
from src.services.orders.supplier_tracking import SupplierTrackingService
from src.services.orders.supplier_tracking_shape import has_terminal_delivered_signal

ADMIN = "src.services.admin_notification_service"
SUPPLIER = "src.services.orders.supplier_tracking"


def _tracking_with_delivered(
    *,
    parcellab: bool = False,
    dhl: bool = False,
    alert_state: dict | None = None,
) -> dict:
    data: dict = {
        "store_events": [],
        "supplier_events": [],
        "carrier_events": [],
    }
    if parcellab:
        data["supplier_events"] = [
            {
                "key": "pl-delivered",
                "at": "2026-07-11T13:05:00",
                "stage": "delivered",
                "source": "parcellab",
            }
        ]
    if dhl:
        data["carrier_events"] = [
            {
                "key": "dhl-delivered",
                "at": "2026-07-11T12:20:00",
                "stage": "delivered",
                "source": "dhl",
            }
        ]
    if alert_state:
        data[ADMIN_DELIVERED_ALERT_KEY] = alert_state
    return data


def _delivery_order(**overrides) -> MagicMock:
    order = MagicMock()
    order.id = overrides.get("id", 1500)
    order.status = overrides.get("status", OrderStatus.DELIVERY)
    order.supplier_order_id = overrides.get("supplier_order_id", "TP-123456")
    order.supplier_tracking_id = overrides.get("supplier_tracking_id", "CJ123456789DE")
    order.supplier_tracking_json = overrides.get(
        "supplier_tracking_json",
        _tracking_with_delivered(parcellab=True),
    )
    return order


@pytest.fixture
def admin_notify() -> AdminNotificationService:
    session = AsyncMock()
    service = AdminNotificationService(session)
    service.order_service = MagicMock()
    service.order_service.order_crud = AsyncMock()
    service.order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[]
    )
    service.dispatcher = MagicMock()
    service.dispatcher.telegram_client = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_snapshot_text_both_sources(
    admin_notify: AdminNotificationService,
) -> None:
    text = format_admin_delivered_alert_message(
        order_id=1500,
        supplier_order_id="TP-123456",
        tracking_id="CJ123456789DE",
        parcellab_confirmed=True,
        parcellab_at="2026-07-11T13:05:00",
        dhl_confirmed=True,
        dhl_at="2026-07-11T12:20:00",
        checked_at=datetime(2026, 7, 11, 13, 7),
    )
    assert "Заказ #1500 · Возможно доставлен" in text
    assert "ParcelLab: доставлен" in text
    assert "DHL: доставлен" in text
    assert "ещё не подтвердил доставку" not in text
    assert "TP-123456" in text
    assert "CJ123456789DE" in text


def _mock_order_crud(
    admin_notify: AdminNotificationService,
    order: MagicMock,
) -> None:
    row_lock = asyncio.Lock()

    async def get_by_id_for_update(_order_id: int) -> MagicMock:
        await row_lock.acquire()
        order._row_lock = row_lock
        return order

    admin_notify.order_service.order_crud.get_by_id_for_update = get_by_id_for_update

    async def commit() -> None:
        lock = getattr(order, "_row_lock", None)
        if lock is not None and lock.locked():
            lock.release()

    admin_notify.session.commit = AsyncMock(side_effect=commit)


@pytest.mark.asyncio
async def test_concurrent_sync_sends_only_once(
    admin_notify: AdminNotificationService,
) -> None:
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(parcellab=True),
    )
    _mock_order_crud(admin_notify, order)
    send_count = 0

    async def send_message(**kwargs: object) -> TelegramSendResult:
        nonlocal send_count
        send_count += 1
        await asyncio.sleep(0.05)
        snapshot_hash = delivered_alert_snapshot_hash(
            parcellab_confirmed=True,
            parcellab_at="2026-07-11T13:05:00",
            dhl_confirmed=False,
            dhl_at=None,
        )
        order.supplier_tracking_json = _tracking_with_delivered(
            parcellab=True,
            alert_state={
                "chat_id": 100,
                "message_id": 9001,
                "snapshot_hash": snapshot_hash,
            },
        )
        return TelegramSendResult(ok=True, message_id=9001)

    admin_notify.telegram_client.send_message = send_message
    admin_notify.telegram_client.edit_message_text = AsyncMock(return_value=False)
    checked_at = datetime(2026, 7, 11, 13, 7)

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        results = await asyncio.gather(
            admin_notify.sync_delivered_alert(order.id, checked_at=checked_at),
            admin_notify.sync_delivered_alert(order.id, checked_at=checked_at),
        )

    assert send_count == 1
    assert results == [True, True]


@pytest.mark.asyncio
async def test_dhl_first_send(admin_notify: AdminNotificationService) -> None:
    order = _delivery_order(supplier_tracking_json=_tracking_with_delivered(dhl=True))
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=9010)
    )

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    text = admin_notify.telegram_client.send_message.await_args.kwargs["text"]
    assert "DHL: доставлен" in text
    assert "ParcelLab: ещё не подтвердил доставку" in text


@pytest.mark.asyncio
async def test_parcellab_first_send(admin_notify: AdminNotificationService) -> None:
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(parcellab=True),
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=9001)
    )

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    admin_notify.telegram_client.send_message.assert_awaited_once()
    assert order.supplier_tracking_json[ADMIN_DELIVERED_ALERT_KEY]["message_id"] == 9001
    assert order.status == OrderStatus.DELIVERY


@pytest.mark.asyncio
async def test_dhl_updates_same_message(admin_notify: AdminNotificationService) -> None:
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(
            parcellab=True,
            dhl=True,
            alert_state={
                "chat_id": 100,
                "message_id": 9001,
                "snapshot_hash": delivered_alert_snapshot_hash(
                    parcellab_confirmed=True,
                    parcellab_at="2026-07-11T13:05:00",
                    dhl_confirmed=False,
                    dhl_at=None,
                ),
            },
        )
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.edit_message_text = AsyncMock(return_value=True)

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    admin_notify.telegram_client.edit_message_text.assert_awaited_once()
    admin_notify.telegram_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_snapshot_skips_edit(admin_notify: AdminNotificationService) -> None:
    snapshot_hash = delivered_alert_snapshot_hash(
        parcellab_confirmed=True,
        parcellab_at="2026-07-11T13:05:00",
        dhl_confirmed=False,
        dhl_at=None,
    )
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(
            parcellab=True,
            alert_state={
                "chat_id": 100,
                "message_id": 9001,
                "snapshot_hash": snapshot_hash,
            },
        )
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.edit_message_text = AsyncMock(return_value=True)
    admin_notify.telegram_client.send_message = AsyncMock()

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 14, 0),
        )

    admin_notify.telegram_client.edit_message_text.assert_not_awaited()
    admin_notify.telegram_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_edit_failure_sends_replacement(
    admin_notify: AdminNotificationService,
) -> None:
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(
            parcellab=True,
            dhl=True,
            alert_state={
                "chat_id": 100,
                "message_id": 9001,
                "snapshot_hash": "old-hash",
            },
        )
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.edit_message_text = AsyncMock(return_value=False)
    admin_notify.telegram_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=9002)
    )

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    admin_notify.telegram_client.send_message.assert_awaited_once()
    assert order.supplier_tracking_json[ADMIN_DELIVERED_ALERT_KEY]["message_id"] == 9002


@pytest.mark.asyncio
async def test_order_level_a_skips_completed_order(
    admin_notify: AdminNotificationService,
) -> None:
    tracking = _tracking_with_delivered(
        parcellab=True,
        alert_state={
            "chat_id": 100,
            "message_id": 9001,
            "snapshot_hash": "old-hash",
        },
    )
    order = _delivery_order(
        status=OrderStatus.COMPLETED,
        supplier_tracking_json=tracking,
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.edit_message_text = AsyncMock(return_value=True)
    admin_notify.telegram_client.send_message = AsyncMock()

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        ok = await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    assert ok is False
    admin_notify.telegram_client.edit_message_text.assert_not_awaited()
    admin_notify.telegram_client.send_message.assert_not_awaited()
    assert order.supplier_tracking_json[ADMIN_DELIVERED_ALERT_KEY]["snapshot_hash"] == (
        "old-hash"
    )


@pytest.mark.asyncio
async def test_tg_failure_schedules_retry(
    admin_notify: AdminNotificationService,
) -> None:
    order = _delivery_order(
        supplier_tracking_json=_tracking_with_delivered(parcellab=True),
    )
    _mock_order_crud(admin_notify, order)
    admin_notify.telegram_client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=False, message_id=None)
    )

    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        ok = await admin_notify.sync_delivered_alert(
            order.id,
            checked_at=datetime(2026, 7, 11, 13, 7),
        )

    assert ok is False
    alert = order.supplier_tracking_json[ADMIN_DELIVERED_ALERT_KEY]
    assert alert["pending_retry"] is True
    assert alert["next_retry_at"]


@pytest.mark.asyncio
async def test_manual_delivered_does_not_trigger_alert() -> None:
    tracking = _tracking_with_delivered()
    tracking["store_events"] = [
        {
            "key": "manual-delivered",
            "at": "2026-07-11T13:05:00",
            "stage": "delivered",
            "source": "manual",
        }
    ]
    assert has_terminal_delivered_signal(tracking) is False


@pytest.mark.asyncio
async def test_sync_order_keeps_delivery_status() -> None:
    session = AsyncMock()
    service = SupplierTrackingService(session)
    order = _delivery_order()
    order.supplier_tracking_sync_state = "delivered"
    service._apply_parcellab_payload = MagicMock(return_value=True)
    service._maybe_start_delivery = AsyncMock()
    service._apply_dhl_fetch = MagicMock(
        return_value={"status": "delivered", "changed": True, "error": None}
    )
    service._apply_russian_post_fetch = MagicMock(
        return_value={"status": "ok", "changed": False, "error": None}
    )
    crud = AsyncMock()
    crud.get_by_id = AsyncMock(return_value=order)
    crud.get_by_id_for_update = AsyncMock(return_value=order)
    crud.list_placed_supplier_orders = AsyncMock(return_value=[])
    with (
        patch(f"{SUPPLIER}.fetch_supplier_tracking", AsyncMock(return_value={"x": 1})),
        patch(f"{SUPPLIER}.fetch_dhl_tracking", AsyncMock(return_value={"events": []})),
        patch(
            f"{SUPPLIER}.fetch_pochta_tracking", AsyncMock(return_value={"events": []})
        ),
        patch(
            f"{SUPPLIER}.sync_delivered_alert_after_tracking_check",
            AsyncMock(),
        ) as sync_alert,
        patch(f"{SUPPLIER}.CrudOrder", return_value=crud),
    ):
        result = await service.sync_order(1500)

    assert order.status == OrderStatus.DELIVERY
    assert result["status"] == "delivered"
    sync_alert.assert_awaited_once()


class _SessionFactory:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False


def _shipment_row(**overrides: object) -> MagicMock:
    row = MagicMock()
    row.id = overrides.get("id", 160)
    row.order_id = overrides.get("order_id", 188)
    row.supplier_order_id = overrides.get("supplier_order_id", 10)
    row.status = overrides.get("status", ShipmentStatus.DELIVERED)
    row.supplier_tracking_number = overrides.get("cj", "CJ687974145DE")
    row.delivered_alert = overrides.get("delivered_alert")
    return row


def _delivery_order_row(order_id: int = 188) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.status = OrderStatus.DELIVERY
    return order


def _wire_shipment_crud(
    session: MagicMock, row: MagicMock, order: MagicMock, header: MagicMock
) -> MagicMock:
    crud = MagicMock()
    crud.get_shipment_by_id = AsyncMock(return_value=row)
    crud.get_shipment_by_id_for_update = AsyncMock(return_value=row)
    crud.get_by_id = AsyncMock(return_value=order)
    session.get = AsyncMock(return_value=header)
    session.commit = AsyncMock()
    return crud


async def _sync_shipment(
    row: MagicMock,
    order: MagicMock,
    header: MagicMock,
    client: AsyncMock,
) -> bool:
    session = MagicMock()
    crud = _wire_shipment_crud(session, row, order, header)
    dispatcher = MagicMock()
    dispatcher.telegram_client = client
    with (
        patch(f"{ADMIN}.CrudOrder", return_value=crud),
        patch(f"{ADMIN}.notification_dispatcher", return_value=dispatcher),
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        return await sync_shipment_delivered_alert(
            int(row.id),
            datetime(2026, 9, 10, 12, 0),
            session_factory=_SessionFactory(session),
        )


@pytest.mark.asyncio
async def test_placed_one_delivered_sends_tp_and_cj() -> None:
    row = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    client = AsyncMock()
    client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=11)
    )
    ok = await _sync_shipment(
        row,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2864070"),
        client,
    )
    assert ok is True
    text = client.send_message.await_args.kwargs["text"]
    assert "Заказ #186 · Возможно доставлен" in text
    assert "TP-2864070" in text
    assert "CJ688083128DE" in text
    assert "Доставлен" in text
    keyboard = client.send_message.await_args.kwargs["reply_markup"]
    assert build_dhl_public_tracking_url("CJ688083128DE") in str(keyboard)
    assert row.delivered_alert["message_id"] == 11


@pytest.mark.asyncio
async def test_placed_second_shipment_sends_independent_message() -> None:
    row_a = _shipment_row(
        id=1,
        order_id=186,
        cj="CJ688083128DE",
        delivered_alert={
            "chat_id": 100,
            "message_id": 11,
            "snapshot_hash": placed_delivered_alert_snapshot_hash(
                "TP-2864070", "CJ688083128DE"
            ),
            "pending_retry": False,
            "next_retry_at": None,
        },
    )
    row_b = _shipment_row(id=2, order_id=186, cj="CJ688186312DE")
    client_a = AsyncMock()
    client_a.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=11)
    )
    client_b = AsyncMock()
    client_b.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=22)
    )
    ok_a = await _sync_shipment(
        row_a,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2864070"),
        client_a,
    )
    ok_b = await _sync_shipment(
        row_b,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2885732"),
        client_b,
    )
    assert ok_a is True and ok_b is True
    client_a.send_message.assert_not_awaited()
    client_b.send_message.assert_awaited_once()
    text_b = client_b.send_message.await_args.kwargs["text"]
    assert "TP-2885732" in text_b
    assert "CJ688186312DE" in text_b
    assert row_a.delivered_alert["message_id"] == 11
    assert row_b.delivered_alert["message_id"] == 22


@pytest.mark.asyncio
async def test_placed_in_transit_does_not_alert() -> None:
    row = _shipment_row(
        id=2,
        order_id=186,
        status=ShipmentStatus.IN_TRANSIT,
        cj="CJ688186312DE",
    )
    client = AsyncMock()
    client.send_message = AsyncMock()
    ok = await _sync_shipment(
        row,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2885732"),
        client,
    )
    assert ok is False
    client.send_message.assert_not_awaited()
    assert row.delivered_alert is None


@pytest.mark.asyncio
async def test_placed_repeated_sync_is_noop() -> None:
    snapshot_hash = placed_delivered_alert_snapshot_hash("TP-2839107", "CJ687974145DE")
    row = _shipment_row(
        id=160,
        delivered_alert={
            "chat_id": 100,
            "message_id": 9,
            "snapshot_hash": snapshot_hash,
            "pending_retry": False,
        },
    )
    client = AsyncMock()
    client.send_message = AsyncMock()
    client.edit_message_text = AsyncMock()
    ok = await _sync_shipment(
        row, _delivery_order_row(188), MagicMock(external_id="TP-2839107"), client
    )
    assert ok is True
    client.send_message.assert_not_awaited()
    client.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_placed_cj_appears_edits_existing_message() -> None:
    first_hash = placed_delivered_alert_snapshot_hash("TP-2839107", None)
    row = _shipment_row(
        id=160,
        cj=None,
        delivered_alert={
            "chat_id": 100,
            "message_id": 9,
            "snapshot_hash": first_hash,
            "pending_retry": False,
        },
    )
    row.supplier_tracking_number = "CJ687974145DE"
    client = AsyncMock()
    client.edit_message_text = AsyncMock(return_value=True)
    client.send_message = AsyncMock()
    ok = await _sync_shipment(
        row, _delivery_order_row(188), MagicMock(external_id="TP-2839107"), client
    )
    assert ok is True
    client.edit_message_text.assert_awaited_once()
    client.send_message.assert_not_awaited()
    text = client.edit_message_text.await_args.kwargs["text"]
    assert "CJ687974145DE" in text
    assert row.delivered_alert["message_id"] == 9


@pytest.mark.asyncio
async def test_placed_retry_only_failed_shipment() -> None:
    row_a = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    row_b = _shipment_row(id=2, order_id=186, cj="CJ688186312DE")
    client_a = AsyncMock()
    client_a.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=False, message_id=None)
    )
    client_b = AsyncMock()
    client_b.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=22)
    )
    ok_a = await _sync_shipment(
        row_a,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2864070"),
        client_a,
    )
    ok_b = await _sync_shipment(
        row_b,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2885732"),
        client_b,
    )
    assert ok_a is False
    assert row_a.delivered_alert["pending_retry"] is True
    assert ok_b is True
    assert row_b.delivered_alert["message_id"] == 22
    assert row_b.delivered_alert.get("pending_retry") is False


@pytest.mark.asyncio
async def test_placed_skips_order_level_json_alert() -> None:
    session = AsyncMock()
    order = _delivery_order()
    crud = MagicMock()
    crud.list_shipments_for_order = AsyncMock(return_value=[MagicMock(id=1)])
    with (
        patch(f"{ADMIN}.CrudOrder", return_value=crud),
        patch.object(
            AdminNotificationService, "sync_delivered_alert", new_callable=AsyncMock
        ) as sync_mock,
    ):
        await sync_delivered_alert_after_tracking_check(
            session, order, datetime(2026, 9, 10, 12, 0)
        )
    sync_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_placed_order_186_one_then_two_alerts() -> None:
    delivered = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    pending = _shipment_row(
        id=2,
        order_id=186,
        status=ShipmentStatus.IN_TRANSIT,
        cj="CJ688186312DE",
    )
    client_first = AsyncMock()
    client_first.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=11)
    )
    client_skip = AsyncMock()
    client_skip.send_message = AsyncMock()
    ok_delivered = await _sync_shipment(
        delivered,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2864070"),
        client_first,
    )
    ok_pending = await _sync_shipment(
        pending,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2885732"),
        client_skip,
    )
    assert ok_delivered is True
    assert ok_pending is False
    client_first.send_message.assert_awaited_once()
    client_skip.send_message.assert_not_awaited()
    text = client_first.send_message.await_args.kwargs["text"]
    assert "TP-2864070" in text
    assert "CJ688083128DE" in text

    pending.status = ShipmentStatus.DELIVERED
    client_second = AsyncMock()
    client_second.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=22)
    )
    ok_second = await _sync_shipment(
        pending,
        _delivery_order_row(186),
        MagicMock(external_id="TP-2885732"),
        client_second,
    )
    assert ok_second is True
    assert delivered.delivered_alert["message_id"] == 11
    assert pending.delivered_alert["message_id"] == 22
    text_b = client_second.send_message.await_args.kwargs["text"]
    assert "TP-2885732" in text_b
    assert "CJ688186312DE" in text_b


@pytest.mark.asyncio
async def test_placed_concurrent_claim_sends_only_once() -> None:
    row = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    order = _delivery_order_row(186)
    header = MagicMock(external_id="TP-2864070")
    lock = asyncio.Lock()
    send_count = 0
    session = MagicMock()
    crud = MagicMock()

    async def get_for_update(shipment_id: int) -> MagicMock:
        del shipment_id
        await lock.acquire()
        return row

    async def commit() -> None:
        if lock.locked():
            lock.release()

    crud.get_shipment_by_id_for_update = get_for_update
    crud.get_by_id = AsyncMock(return_value=order)
    session.get = AsyncMock(return_value=header)
    session.commit = AsyncMock(side_effect=commit)

    async def send_message(**kwargs: object) -> TelegramSendResult:
        del kwargs
        nonlocal send_count
        send_count += 1
        await asyncio.sleep(0.05)
        return TelegramSendResult(ok=True, message_id=11)

    client = AsyncMock()
    client.send_message = send_message
    client.edit_message_text = AsyncMock(return_value=False)
    dispatcher = MagicMock()
    dispatcher.telegram_client = client
    with (
        patch(f"{ADMIN}.CrudOrder", return_value=crud),
        patch(f"{ADMIN}.notification_dispatcher", return_value=dispatcher),
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        checked_at = datetime(2026, 9, 10, 12, 0)
        results = await asyncio.gather(
            sync_shipment_delivered_alert(
                1, checked_at, session_factory=_SessionFactory(session)
            ),
            sync_shipment_delivered_alert(
                1, checked_at, session_factory=_SessionFactory(session)
            ),
        )
    assert send_count == 1
    assert results == [True, True]


@pytest.mark.asyncio
async def test_order_completed_alert_lists_shipments_and_skips_edit() -> None:
    from src.content.admin_texts import format_order_completed_alert_message
    from src.services.admin_notification_service import sync_order_completed_admin_alert

    order = MagicMock()
    order.id = 186
    order.status = OrderStatus.COMPLETED
    order.supplier_order_id = None
    order.supplier_tracking_id = None
    order.supplier_tracking_json = {}
    ship_a = MagicMock()
    ship_a.supplier_order_id = 1
    ship_a.supplier_tracking_number = "CJ688083128DE"
    ship_b = MagicMock()
    ship_b.supplier_order_id = 2
    ship_b.supplier_tracking_number = "CJ688186312DE"
    so_a = MagicMock(id=1, external_id="TP-2864070")
    so_b = MagicMock(id=2, external_id="TP-2885732")
    session = MagicMock()
    crud = MagicMock()
    crud.get_by_id_for_update = AsyncMock(return_value=order)
    crud.list_shipments_for_order = AsyncMock(return_value=[ship_a, ship_b])
    crud.list_placed_supplier_orders = AsyncMock(return_value=[so_a, so_b])
    session.commit = AsyncMock()
    client = AsyncMock()
    client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=77)
    )
    client.edit_message_text = AsyncMock(return_value=True)
    dispatcher = MagicMock()
    dispatcher.telegram_client = client
    with (
        patch(f"{ADMIN}.CrudOrder", return_value=crud),
        patch(f"{ADMIN}.notification_dispatcher", return_value=dispatcher),
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        ok = await sync_order_completed_admin_alert(
            186,
            datetime(2026, 9, 10, 12, 0),
            session_factory=_SessionFactory(session),
        )
    assert ok is True
    client.edit_message_text.assert_not_awaited()
    text = client.send_message.await_args.kwargs["text"]
    assert "Завершён администратором" in text
    assert "TP-2864070" in text
    assert "TP-2885732" in text
    assert "CJ688083128DE" in text
    expected = format_order_completed_alert_message(
        186,
        [("TP-2864070", "CJ688083128DE"), ("TP-2885732", "CJ688186312DE")],
        datetime(2026, 9, 10, 12, 0),
    )
    assert "Посылки:" in expected


@pytest.mark.asyncio
async def test_order_level_a_skips_when_shipments_exist(
    admin_notify: AdminNotificationService,
) -> None:
    order = _delivery_order()
    _mock_order_crud(admin_notify, order)
    admin_notify.order_service.order_crud.list_shipments_for_order = AsyncMock(
        return_value=[MagicMock(id=1)]
    )
    admin_notify.telegram_client.send_message = AsyncMock()
    with (
        patch(f"{ADMIN}.settings.TG_ORDERS_CHAT_ID", 100),
        patch(f"{ADMIN}.settings.TG_BOT_SHOP", "token"),
    ):
        ok = await admin_notify.sync_delivered_alert(
            order.id, checked_at=datetime(2026, 7, 11, 13, 7)
        )
    assert ok is True
    admin_notify.telegram_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_placed_a_still_sends_after_order_completed() -> None:
    order = _delivery_order_row(186)
    order.status = OrderStatus.COMPLETED
    row = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    client = AsyncMock()
    client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=42)
    )
    ok = await _sync_shipment(row, order, MagicMock(external_id="TP-2864070"), client)
    assert ok is True
    client.send_message.assert_awaited_once()
    text = client.send_message.await_args.kwargs["text"]
    assert "Возможно доставлен" in text
    assert "Завершён администратором" not in text


@pytest.mark.asyncio
async def test_placed_a_after_completed_is_idempotent() -> None:
    order = _delivery_order_row(186)
    order.status = OrderStatus.COMPLETED
    row = _shipment_row(id=1, order_id=186, cj="CJ688083128DE")
    header = MagicMock(external_id="TP-2864070")
    client = AsyncMock()
    client.send_message = AsyncMock(
        return_value=TelegramSendResult(ok=True, message_id=42)
    )
    client.edit_message_text = AsyncMock()
    first = await _sync_shipment(row, order, header, client)
    second = await _sync_shipment(row, order, header, client)
    assert first is True
    assert second is True
    client.send_message.assert_awaited_once()
    client.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_placed_a_skips_cancelled_order() -> None:
    order = _delivery_order_row(186)
    order.status = OrderStatus.CANCELLED
    row = _shipment_row(id=1, order_id=186)
    client = AsyncMock()
    client.send_message = AsyncMock()
    ok = await _sync_shipment(row, order, MagicMock(external_id="TP-2864070"), client)
    assert ok is False
    client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_retry_skips_completed_and_shipment_orders() -> None:
    from src.jobs.orders.delivered_alert_retry_job import run_delivered_alert_retry

    order = _delivery_order(status=OrderStatus.COMPLETED)
    session = MagicMock()
    session.get = AsyncMock(return_value=order)
    crud = MagicMock()
    crud.list_shipments_for_order = AsyncMock(return_value=[])

    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_job.async_session_maker",
            _SessionFactory(session),
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_job.CrudOrder",
            return_value=crud,
        ),
    ):
        result = await run_delivered_alert_retry(1500)
    assert result["status"] == "skipped"
    assert result["reason"] == "status"

    order.status = OrderStatus.DELIVERY
    crud.list_shipments_for_order = AsyncMock(return_value=[MagicMock(id=9)])
    with (
        patch(
            "src.jobs.orders.delivered_alert_retry_job.async_session_maker",
            _SessionFactory(session),
        ),
        patch(
            "src.jobs.orders.delivered_alert_retry_job.CrudOrder",
            return_value=crud,
        ),
    ):
        result = await run_delivered_alert_retry(1500)
    assert result["status"] == "skipped"
    assert result["reason"] == "has_shipments"
