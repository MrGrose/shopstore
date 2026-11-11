from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.schemas.order import AdminAvailabilityItemDecision
from src.services.orders.order_service import OrderService
from src.web.routers.admin_orders_pages import parse_availability_decisions_from_form

ROOT = Path(__file__).resolve().parents[2]
ORDER_DETAIL_TEMPLATE = ROOT / "src/templates/site/admin/partials/order_detail.html"
RAIL_AVAILABILITY_STEP = (
    ROOT / "src/templates/site/admin/partials/_order_action_rail_step_body.html"
)
DELIVERY_STEP_PARTIAL = (
    ROOT / "src/templates/site/admin/partials/_order_action_rail_step_delivery.html"
)
AVAILABILITY_PARTIAL = (
    ROOT / "src/templates/site/admin/partials/_order_availability_stock_check.html"
)


def test_availability_radios_inside_availability_form() -> None:
    content = RAIL_AVAILABILITY_STEP.read_text(encoding="utf-8")
    pending_marker = (
        "{% elif order.status in ('created', 'processing') "
        "and order.availability_confirmation_status == 'pending' %}"
    )
    unavailable_marker = (
        "{% elif order.status in ('created', 'processing') "
        "and order.availability_confirmation_status == 'unavailable' %}"
    )
    pending_start = content.index(pending_marker)
    pending_block = content[pending_start : content.index(unavailable_marker)]
    form_open = pending_block.index('id="order-availability-form-{{ order.id }}"')
    include_pos = pending_block.index(
        '{% include "site/admin/partials/_order_availability_stock_check.html" %}'
    )
    form_close = pending_block.index("</form>", form_open)
    assert form_open < include_pos < form_close
    partial = AVAILABILITY_PARTIAL.read_text(encoding="utf-8")
    assert 'name="availability_item_' in partial
    assert 'form="{{ availability_form_id }}"' in partial
    assert "Наличие у поставщика подтверждено" in partial
    assert "Товара нет у поставщика — удалить из заказа" in partial


def test_parse_availability_decisions_from_form_confirmed_and_reject() -> None:
    form_items = [
        ("availability_item_10_decision", "confirmed"),
        ("availability_item_11_decision", "reject"),
        ("action", "save_check"),
    ]
    decisions = parse_availability_decisions_from_form(form_items)
    assert len(decisions) == 2
    by_id = {item.order_item_id: item.confirmed for item in decisions}
    assert by_id[10] is True
    assert by_id[11] is False


def test_parse_availability_decisions_from_form_multiple_positions() -> None:
    form_items = [
        ("availability_item_1_decision", "confirmed"),
        ("availability_item_2_decision", "confirmed"),
        ("availability_item_3_decision", "reject"),
    ]
    decisions = parse_availability_decisions_from_form(form_items)
    assert {d.order_item_id for d in decisions} == {1, 2, 3}


@pytest.mark.asyncio
async def test_validate_availability_decisions_accepts_full_set() -> None:
    service = OrderService.__new__(OrderService)
    service._resolve_pending_availability_rows = AsyncMock(
        return_value=[
            {"order_item": type("Item", (), {"id": 10})()},
            {"order_item": type("Item", (), {"id": 11})()},
        ]
    )
    result = await service._validate_availability_decisions(
        1,
        [
            AdminAvailabilityItemDecision(order_item_id=10, confirmed=True),
            AdminAvailabilityItemDecision(order_item_id=11, confirmed=False),
        ],
    )
    assert result[10].confirmed is True
    assert result[11].confirmed is False


def test_completed_order_hides_status_form_and_tracking_actions() -> None:
    detail = ORDER_DETAIL_TEMPLATE.read_text(encoding="utf-8")
    delivery = DELIVERY_STEP_PARTIAL.read_text(encoding="utf-8")
    assert "{% set order_is_completed = order.status == 'completed' %}" in detail
    assert (
        "{% set order_is_status_locked = order.status in ('completed', 'cancelled') %}"
        in detail
    )
    terminal_set = (
        "{% set order_is_terminal = order.status in "
        "('completed', 'cancelled', 'failed') %}"
    )
    assert terminal_set in detail
    assert "{% if order_is_status_locked %}" in detail
    assert "Заказ выполнен." in detail
    assert "Заказ отменён." in detail
    assert "Доставка выполнена." in delivery
    assert "admin_action_rail" in detail
    assert "{% if not order_is_terminal %}" in detail
    assert "{% if not order_is_completed %}" in delivery
    assert "Проверить все посылки" in delivery
    assert "Проверить сейчас" in delivery
    assert "Добавить ручной этап" not in delivery


@pytest.mark.asyncio
async def test_completed_status_notify_rejected() -> None:
    from src.schemas.order import AdminOrderStatusUpdate

    order = type("Order", (), {})()
    order.status = "completed"
    order.user_id = 1
    order.availability_confirmation_status = "confirmed"
    service = OrderService.__new__(OrderService)
    service.order_crud = AsyncMock()
    service.order_crud.get_by_id = AsyncMock(return_value=order)

    with pytest.raises(ValueError, match="уже выполнен"):
        await service.update_order_status(
            42,
            AdminOrderStatusUpdate(
                status="completed",
                notify_customer=True,
            ),
        )


@pytest.mark.asyncio
async def test_validate_availability_decisions_missing_position_raises() -> None:
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
