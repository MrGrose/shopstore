from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.orders.shipments import ShipmentError
from src.web.routers import admin_orders_pages as pages


def _delivered_view(*, order_id: int = 188, shipment_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        id=shipment_id,
        order_id=order_id,
        status="delivered",
        completed_at=None,
    )


@pytest.mark.asyncio
async def test_admin_complete_calls_complete_shipment_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _delivered_view()
    fake = MagicMock()
    fake.complete_shipment = AsyncMock(return_value=view)
    monkeypatch.setattr(pages, "ShipmentService", lambda _db: fake)
    monkeypatch.setattr(pages, "orders_return_from_form", lambda _form: {})
    captured: list[dict[str, object]] = []

    def _redirect(*_args: object, **kwargs: object) -> str:
        captured.append(kwargs)
        return "redirect"

    monkeypatch.setattr(pages, "_orders_redirect", _redirect)
    request = MagicMock()
    request.form = AsyncMock(return_value={})
    finalize = AsyncMock()
    notify = AsyncMock()
    completed_alert = AsyncMock()
    with (
        patch(
            "src.services.orders.order_service.OrderService.finalize_order_delivery",
            finalize,
        ),
        patch(
            "src.services.customer_notification_service."
            "CustomerNotificationService.notify_order_status",
            notify,
        ),
        patch(
            "src.services.admin_notification_service.sync_order_completed_admin_alert",
            completed_alert,
        ),
    ):
        result = await pages.admin_shipment_complete_submit(
            request,
            188,
            10,
            _admin_user=MagicMock(),
            db=MagicMock(),
        )
    assert result == "redirect"
    fake.complete_shipment.assert_awaited_once_with(10, 188)
    finalize.assert_not_called()
    notify.assert_not_called()
    completed_alert.assert_not_called()
    assert captured[0]["success"] == "Посылка завершена"


@pytest.mark.asyncio
async def test_admin_complete_wrong_order_does_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = MagicMock()
    fake.complete_shipment = AsyncMock(side_effect=ShipmentError("Посылка не найдена"))
    monkeypatch.setattr(pages, "ShipmentService", lambda _db: fake)
    monkeypatch.setattr(pages, "orders_return_from_form", lambda _form: {})
    captured: list[dict[str, object]] = []

    def _redirect(*_args: object, **kwargs: object) -> str:
        captured.append(kwargs)
        return "redirect"

    monkeypatch.setattr(pages, "_orders_redirect", _redirect)
    request = MagicMock()
    request.form = AsyncMock(return_value={})
    await pages.admin_shipment_complete_submit(
        request,
        188,
        10,
        _admin_user=MagicMock(),
        db=MagicMock(),
    )
    fake.complete_shipment.assert_awaited_once_with(10, 188)
    assert captured[0].get("error") == "Посылка не найдена"


@pytest.mark.asyncio
async def test_admin_notify_route_calls_notify_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_orders = MagicMock()
    fake_orders.notify_shipments_delivered = AsyncMock(return_value=1)
    monkeypatch.setattr(pages, "OrderService", lambda _db: fake_orders)
    fake_ship = MagicMock()
    fake_ship.complete_shipment = AsyncMock()
    monkeypatch.setattr(pages, "ShipmentService", lambda _db: fake_ship)
    monkeypatch.setattr(pages, "orders_return_from_form", lambda _form: {})
    captured: list[dict[str, object]] = []

    def _redirect(*_args: object, **kwargs: object) -> str:
        captured.append(kwargs)
        return "redirect"

    monkeypatch.setattr(pages, "_orders_redirect", _redirect)
    form = MagicMock()
    form.getlist = lambda _name: ["11"]
    form.get = lambda _name, default=None: "hello {seq}"
    request = MagicMock()
    request.form = AsyncMock(return_value=form)
    finalize = AsyncMock()
    completed_alert = AsyncMock()
    with (
        patch(
            "src.services.orders.order_service.OrderService.finalize_order_delivery",
            finalize,
        ),
        patch(
            "src.services.admin_notification_service.sync_order_completed_admin_alert",
            completed_alert,
        ),
    ):
        result = await pages.admin_shipments_notify_submit(
            request,
            188,
            admin_user=MagicMock(),
            db=MagicMock(),
        )
    assert result == "redirect"
    fake_orders.notify_shipments_delivered.assert_awaited_once()
    fake_ship.complete_shipment.assert_not_called()
    finalize.assert_not_called()
    completed_alert.assert_not_called()
    assert "очередь" in str(captured[0].get("success"))
