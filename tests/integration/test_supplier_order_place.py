from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.order_limits import max_supplier_goods_eur
from src.main import app
from src.models.notification_outbox import NotificationOutbox
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderStatus,
    Shipment,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.repositories.session import async_session_maker
from src.schemas.order import AdminStartAssemblingUpdate
from src.services.notifications.customer_notification_keys import (
    assembly_notify_key,
    assembly_parcel_notify_key,
)
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import (
    SupplierOrderAllocationError,
    SupplierOrderService,
)
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)
from tests.integration.test_order_availability_sync import _create_processing_order
from tests.integration.test_supplier_order_packing import (
    _UNIT,
    _create_packing_order,
    _set_delivery_fee,
)

pytestmark = pytest.mark.integration


# Считает Shipment по заказу после place.
async def _shipment_count(session: AsyncSession, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Shipment)
            .where(Shipment.order_id == order_id)
        )
        or 0
    )


# Оплата после packing: freeze N = actual, чтобы create_draft уже не звать.
async def _mark_paid_for_place(session: AsyncSession, order_id: int) -> None:
    order = await session.get(Order, order_id)
    assert order is not None
    headers = (
        await session.scalars(
            select(SupplierOrder).where(SupplierOrder.order_id == order_id)
        )
    ).all()
    actual = sum(
        1 for header in headers if str(header.status) != SupplierOrderStatus.CANCELLED
    )
    order.payment_paid_at = utc_now_naive()
    order.availability_confirmation_status = AvailabilityConfirmationStatus.NOT_REQUIRED
    order.status = OrderStatus.PROCESSING
    order.paid_supplier_order_count = actual
    await session.commit()


# Считает события assembling у заказа.
async def _assembly_event_count(session: AsyncSession, order_id: int) -> int:
    rows = (
        await session.scalars(
            select(OrderEvent).where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == "assembly_started",
            )
        )
    ).all()
    return len(rows)


# Возвращает outbox keys packing-notify для одной посылки.
async def _parcel_outbox_keys(
    session: AsyncSession, order_id: int, supplier_order_id: int
) -> list[str]:
    base = assembly_parcel_notify_key(order_id, supplier_order_id)
    return list(
        (
            await session.scalars(
                select(NotificationOutbox.idempotency_key).where(
                    NotificationOutbox.idempotency_key.in_(
                        [base, f"{base}:email", f"{base}:telegram"]
                    )
                )
            )
        ).all()
    )


# Возвращает outbox keys legacy assembly-notify для заказа.
async def _assembly_outbox_keys(session: AsyncSession, order_id: int) -> list[str]:
    base = assembly_notify_key(order_id)
    return list(
        (
            await session.scalars(
                select(NotificationOutbox.idempotency_key).where(
                    NotificationOutbox.idempotency_key.in_(
                        [base, f"{base}:email", f"{base}:telegram"]
                    )
                )
            )
        ).all()
    )


# Считает все outbox rows с assembly-notify prefix (cross-path idempotency).
async def _assembly_outbox_row_count(session: AsyncSession, order_id: int) -> int:
    prefix = assembly_notify_key(order_id)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(NotificationOutbox)
            .where(NotificationOutbox.idempotency_key.startswith(prefix))
        )
        or 0
    )


@pytest.mark.asyncio
async def test_place_draft_sets_external_id_and_status(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-{suffix}-100"
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = order.id
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        header_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        placed = await service.place_draft(order.id, header.id, f"  {tp_id}  ")
        assert placed.status == SupplierOrderStatus.PLACED
        assert placed.external_id == tp_id
        stored = await session.get(Order, order_id)
        assert stored is not None
        assert stored.supplier_order_id is None
        so = await session.get(SupplierOrder, header_id)
        assert so is not None
        assert so.status == SupplierOrderStatus.PLACED


@pytest.mark.asyncio
async def test_place_empty_draft_rejected(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, _items = await _create_packing_order(session, suffix, Decimal("40.00"))
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        header_id = header.id
        with pytest.raises(SupplierOrderAllocationError, match="пустой"):
            await service.place_draft(order.id, header.id, f"TP-{suffix}-EMPTY")
        stored = await session.get(SupplierOrder, header_id)
        assert stored is not None
        assert stored.status == SupplierOrderStatus.DRAFT
        assert stored.external_id is None


@pytest.mark.asyncio
async def test_place_over_allocation_rejected(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = order.id
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        header_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        line = await session.scalar(
            select(SupplierOrderLine).where(
                SupplierOrderLine.supplier_order_id == header.id
            )
        )
        assert line is not None
        line.quantity = 9
        await session.commit()
        with pytest.raises(SupplierOrderAllocationError):
            await service.place_draft(order.id, header.id, f"TP-{suffix}-OVER")
        stored = await session.get(SupplierOrder, header_id)
        order_row = await session.get(Order, order_id)
        assert stored is not None and order_row is not None
        assert stored.status == SupplierOrderStatus.DRAFT
        assert order_row.supplier_order_id is None


@pytest.mark.asyncio
async def test_place_goods_cap_boundary(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    cap = max_supplier_goods_eur()
    async with async_session_maker() as session:
        order, items = await _create_packing_order(session, suffix, cap, quantity=1)
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 1})
        placed = await service.place_draft(order.id, header.id, f"TP-{suffix}-CAP-OK")
        assert placed.status == SupplierOrderStatus.PLACED

        over_order, over_items = await _create_packing_order(
            session, suffix + 1, cap + Decimal("0.01"), quantity=1
        )
        over_order_id = over_order.id
        over_item = over_items[0].id
        over_header = await service.create_draft(over_order_id)
        over_header_id = over_header.id
        session.add(
            SupplierOrderLine(
                supplier_order_id=over_header_id,
                order_item_id=over_item,
                quantity=1,
                unit_supplier_eur=cap + Decimal("0.01"),
            )
        )
        await session.commit()
        with pytest.raises(SupplierOrderAllocationError, match="лимит"):
            await service.place_draft(
                over_order_id, over_header_id, f"TP-{suffix}-CAP-BAD"
            )
        stored = await session.get(SupplierOrder, over_header_id)
        assert stored is not None
        assert stored.status == SupplierOrderStatus.DRAFT


@pytest.mark.asyncio
async def test_place_idempotent_same_tp_rejects_other_tp(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-{suffix}-100"
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        header_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        first = await service.place_draft(order.id, header.id, tp_id)
        again = await service.place_draft(order.id, header.id, tp_id)
        assert again.id == first.id
        assert again.external_id == tp_id
        with pytest.raises(SupplierOrderAllocationError, match="нельзя изменить"):
            await service.place_draft(order.id, header.id, f"TP-{suffix}-999")
        stored = await session.get(SupplierOrder, header_id)
        assert stored is not None
        assert stored.external_id == tp_id


@pytest.mark.asyncio
async def test_place_rejects_duplicate_external_id_on_other_so(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-{suffix}-DUP"
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        first = await service.create_draft(order.id)
        second = await service.create_draft(order.id)
        second_id = second.id
        await service.save_draft_lines(order.id, first.id, {item_id: 2})
        await service.save_draft_lines(order.id, second.id, {item_id: 3})
        await service.place_draft(order.id, first.id, tp_id)
        with pytest.raises(SupplierOrderAllocationError, match="уже использован"):
            await service.place_draft(order.id, second.id, tp_id)
        stored = await session.get(SupplierOrder, second_id)
        assert stored is not None
        assert stored.status == SupplierOrderStatus.DRAFT
        assert stored.external_id is None


@pytest.mark.asyncio
async def test_placed_so_cannot_change_lines(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await service.place_draft(order.id, header.id, f"TP-{suffix}-IMM")
        with pytest.raises(SupplierOrderAllocationError, match="оформленного"):
            await service.save_draft_lines(order.id, header.id, {item_id: 1})


@pytest.mark.asyncio
async def test_place_copy_uses_so_qty(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        first = await service.create_draft(order.id)
        second = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, first.id, {item_id: 2})
        await service.save_draft_lines(order.id, second.id, {item_id: 3})
        views = await service.list_for_order(order.id)
        by_id = {view.id: view for view in views}
        assert by_id[first.id].place_copy_text is not None
        assert "× 2 ×" in by_id[first.id].place_copy_text
        assert "× 3 ×" in by_id[second.id].place_copy_text
        assert "× 5 ×" not in by_id[first.id].place_copy_text
        assert "× 5 ×" not in by_id[second.id].place_copy_text


@pytest.mark.asyncio
async def test_first_place_does_not_write_order_supplier_id(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        first = await service.create_draft(order.id)
        second = await service.create_draft(order.id)
        second_id = second.id
        await service.save_draft_lines(order.id, first.id, {item_id: 2})
        await service.save_draft_lines(order.id, second.id, {item_id: 3})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(order.id, first.id, f"TP-{suffix}-100")
        stored = await session.get(Order, order_id)
        assert stored is not None
        assert stored.supplier_order_id is None
        assert stored.status == OrderStatus.ASSEMBLING
        await service.place_draft(order.id, second.id, f"TP-{suffix}-200")
        stored = await session.get(Order, order_id)
        second_row = await session.get(SupplierOrder, second_id)
        assert stored is not None and second_row is not None
        assert stored.supplier_order_id is None
        assert second_row.external_id == f"TP-{suffix}-200"


@pytest.mark.asyncio
async def test_first_place_invokes_assembling_once(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        first = await service.create_draft(order_id)
        second = await service.create_draft(order_id)
        await service.save_draft_lines(order_id, first.id, {item_id: 2})
        await service.save_draft_lines(order_id, second.id, {item_id: 3})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(order_id, first.id, f"TP-{suffix}-A")
        assert await _assembly_event_count(session, order_id) == 1
        await service.place_draft(order_id, second.id, f"TP-{suffix}-B")
        assert await _assembly_event_count(session, order_id) == 1
        stored = await session.get(Order, order_id)
        assert stored is not None
        assert stored.status == OrderStatus.ASSEMBLING
        assert stored.supplier_tracking_json is None
        assert stored.supplier_tracking_next_check_at is not None


@pytest.mark.asyncio
async def test_place_does_not_leave_partial_state_on_mirror_conflict(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order.supplier_order_id = f"TP-{suffix}-LEGACY"
        await session.commit()
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        header_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        with pytest.raises(SupplierOrderAllocationError, match="другой номер"):
            await service.place_draft(order.id, header.id, f"TP-{suffix}-NEW")
        stored = await session.get(SupplierOrder, header_id)
        order_row = await session.get(Order, order_id)
        assert stored is not None and order_row is not None
        assert stored.status == SupplierOrderStatus.DRAFT
        assert stored.external_id is None
        assert order_row.supplier_order_id == f"TP-{suffix}-LEGACY"


@pytest.mark.asyncio
async def test_admin_place_http_flow(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-TEST-{suffix}-1001"
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = order.id
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        so_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await _mark_paid_for_place(session, order_id)
        _, admin_token = await create_admin_access_token(session, suffix + 11)

    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert "Оформить у поставщика" in detail.text
            assert "Посылка №1 оформлена у поставщика" in detail.text
            assert "Сообщение клиенту" in detail.text
            assert "2 шт ×" in detail.text
            placed = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/place",
                data={"external_id": tp_id},
                headers=headers,
            )
            assert placed.status_code == 303
            assert "error=" not in placed.headers.get("location", "")
            again = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/place",
                data={"external_id": tp_id},
                headers=headers,
            )
            assert again.status_code == 303
            assert "error=" not in again.headers.get("location", "")
            other = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/place",
                data={"external_id": f"TP-OTHER-{suffix}"},
                headers=headers,
            )
            assert "error=" in other.headers.get("location", "")
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert tp_id in detail.text
            assert "Оформить у поставщика" not in detail.text
            assert "Передан в сборку у поставщика" not in detail.text
        async with async_session_maker() as session:
            order = await session.get(Order, order_id)
            so = await session.get(SupplierOrder, so_id)
            assert order is not None and so is not None
            assert so.status == SupplierOrderStatus.PLACED
            assert so.external_id == tp_id
            assert order.supplier_order_id is None
            assert order.status == OrderStatus.ASSEMBLING
            assert await _assembly_outbox_keys(session, order_id) == []
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_place_creates_shipment_and_repeat_is_idempotent(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-{suffix}-SHIP"
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        placed = await service.place_draft(order.id, header.id, tp_id)
        assert await _shipment_count(session, order.id) == 1
        again = await service.place_draft(order.id, header.id, tp_id)
        assert again.id == placed.id
        assert await _shipment_count(session, order.id) == 1


@pytest.mark.asyncio
async def test_second_place_creates_second_shipment(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        service = SupplierOrderService(session)
        first = await service.create_draft(order.id)
        second = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, first.id, {item_id: 2})
        await service.save_draft_lines(order.id, second.id, {item_id: 3})
        await _mark_paid_for_place(session, order.id)
        await service.place_draft(order.id, first.id, f"TP-{suffix}-100")
        await service.place_draft(order.id, second.id, f"TP-{suffix}-200")
        assert await _shipment_count(session, order.id) == 2


@pytest.mark.asyncio
async def test_first_place_enqueues_assembly_notify_when_requested(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(
            order.id,
            header.id,
            f"TP-{suffix}-NOTIFY",
            notify_customer=True,
        )
        keys = await _parcel_outbox_keys(session, order_id, header.id)
        assert f"{assembly_parcel_notify_key(order_id, header.id)}:telegram" in keys


@pytest.mark.asyncio
async def test_first_place_skips_assembly_notify_by_default(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(order.id, header.id, f"TP-{suffix}-SILENT")
        assert await _parcel_outbox_keys(session, order_id, header.id) == []


@pytest.mark.asyncio
async def test_second_place_enqueues_own_assembly_parcel_notify(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=5
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        first = await service.create_draft(order_id)
        second = await service.create_draft(order_id)
        await service.save_draft_lines(order_id, first.id, {item_id: 2})
        await service.save_draft_lines(order_id, second.id, {item_id: 3})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(
            order_id,
            first.id,
            f"TP-{suffix}-A",
            notify_customer=True,
        )
        keys_after_first = await _parcel_outbox_keys(session, order_id, first.id)
        assert (
            f"{assembly_parcel_notify_key(order_id, first.id)}:telegram"
            in keys_after_first
        )
        await service.place_draft(
            order_id,
            second.id,
            f"TP-{suffix}-B",
            notify_customer=True,
        )
        keys_second = await _parcel_outbox_keys(session, order_id, second.id)
        assert (
            f"{assembly_parcel_notify_key(order_id, second.id)}:telegram" in keys_second
        )
        keys_first_again = await _parcel_outbox_keys(session, order_id, first.id)
        assert keys_first_again == keys_after_first


@pytest.mark.asyncio
async def test_idempotent_re_place_does_not_duplicate_assembly_notify(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix
    tp_id = f"TP-{suffix}-IDEM"
    async with async_session_maker() as session:
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        item_id = items[0].id
        order_id = order.id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await _mark_paid_for_place(session, order_id)
        await service.place_draft(
            order.id,
            header.id,
            tp_id,
            notify_customer=True,
        )
        keys_after_first = await _parcel_outbox_keys(session, order_id, header.id)
        await service.place_draft(order.id, header.id, tp_id, notify_customer=True)
        keys_after_repeat = await _parcel_outbox_keys(session, order_id, header.id)
        assert keys_after_repeat == keys_after_first


@pytest.mark.asyncio
async def test_admin_place_http_with_notify_enqueues_outbox(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix
    tp_id = f"TP-HTTP-NOTIFY-{suffix}"
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = order.id
        item_id = items[0].id
        service = SupplierOrderService(session)
        header = await service.create_draft(order.id)
        so_id = header.id
        await service.save_draft_lines(order.id, header.id, {item_id: 2})
        await _mark_paid_for_place(session, order_id)
        _, admin_token = await create_admin_access_token(session, suffix + 17)

    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            placed = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/place",
                data={"external_id": tp_id, "notify_customer": "1"},
                headers=headers,
            )
            assert placed.status_code == 303
            assert "error=" not in placed.headers.get("location", "")
        async with async_session_maker() as session:
            keys = await _parcel_outbox_keys(session, order_id, so_id)
            assert f"{assembly_parcel_notify_key(order_id, so_id)}:telegram" in keys
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_legacy_assembling_keeps_order_key_place_adds_parcel_key(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    suffix = merge_unique_suffix
    tp_id = f"SUP-CROSS-{suffix}"
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = utc_now_naive()
        order.paid_supplier_order_count = 1
        await session.commit()
        order_id = order.id
        item_id = items[0].id

        await OrderService(session).start_order_assembling(
            order_id,
            AdminStartAssemblingUpdate(
                supplier_order_id=tp_id,
                notify_customer=True,
            ),
            actor=buyer,
        )
        keys_after_legacy = await _assembly_outbox_keys(session, order_id)
        assert f"{assembly_notify_key(order_id)}:telegram" in keys_after_legacy

        so_service = SupplierOrderService(session)
        header = await so_service.create_draft(order_id)
        await so_service.save_draft_lines(
            order_id, header.id, {item_id: int(items[0].quantity or 0)}
        )
        await so_service.place_draft(
            order_id,
            header.id,
            tp_id,
            notify_customer=True,
        )
        assert await _assembly_outbox_keys(session, order_id) == keys_after_legacy
        parcel_keys = await _parcel_outbox_keys(session, order_id, header.id)
        parcel_key = assembly_parcel_notify_key(order_id, header.id)
        assert f"{parcel_key}:telegram" in parcel_keys
