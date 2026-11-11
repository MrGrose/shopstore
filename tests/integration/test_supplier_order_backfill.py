from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from src.main import app
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderItem,
    OrderStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.repositories.session import async_session_maker
from src.schemas.order import AdminStartAssemblingUpdate
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import BACKFILL_PLACED_BY, SupplierOrderService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)
from tests.integration.test_order_availability_sync import _create_processing_order

pytestmark = pytest.mark.integration


# Считает SupplierOrder и lines по заказу.
async def _supplier_counts(session, order_id: int) -> tuple[int, int]:
    so_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SupplierOrder)
            .where(SupplierOrder.order_id == order_id)
        )
        or 0
    )
    line_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SupplierOrderLine)
            .join(
                SupplierOrder, SupplierOrder.id == SupplierOrderLine.supplier_order_id
            )
            .where(SupplierOrder.order_id == order_id)
        )
        or 0
    )
    return so_count, line_count


# Добавляет вторую позицию и фиксирует закупочные цены для backfill.
async def _prepare_legacy_items(
    session,
    order: Order,
    items: list[OrderItem],
    suffix: int,
) -> None:
    product_id = await pick_active_product_id(session)
    line_spec = await resolve_product_line_spec(session, product_id, Decimal("80"), 2)
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=line_spec[0],
            variant_id=line_spec[1],
            quantity=line_spec[3],
            unit_price=line_spec[2],
            product_title_captured="Second item",
            supplier_price_eur_captured=Decimal("20.00"),
        )
    )
    for item in items:
        item.supplier_price_eur_captured = Decimal("10.50")
        item.product_title_captured = item.product_title_captured or "First item"
    order.supplier_order_id = f"TP-3A-{suffix}"
    order.status = OrderStatus.ASSEMBLING
    await session.commit()


@pytest.mark.asyncio
async def test_backfill_creates_one_placed_so_and_is_idempotent(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        await _prepare_legacy_items(session, order, items, suffix)
        order_id = order.id
        tp_id = order.supplier_order_id
        item_count = int(
            await session.scalar(
                select(func.count())
                .select_from(OrderItem)
                .where(OrderItem.order_id == order_id)
            )
            or 0
        )
        service = SupplierOrderService(session)
        first = await service.backfill_legacy(order_id=order_id)
        assert first.created_orders == 1
        assert first.created_lines == item_count

    async with async_session_maker() as session:
        so_count, line_count = await _supplier_counts(session, order_id)
        assert so_count == 1
        assert line_count == item_count
        header = await session.scalar(
            select(SupplierOrder).where(SupplierOrder.order_id == order_id)
        )
        assert header is not None
        assert header.seq == 1
        assert header.status == SupplierOrderStatus.PLACED
        assert header.external_id == tp_id
        assert header.placed_by == BACKFILL_PLACED_BY
        assert header.supplier_shipping_eur == Decimal("29.99")
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.supplier_order_id == tp_id
        service = SupplierOrderService(session)
        second = await service.backfill_legacy(order_id=order_id)
        assert second.created_orders == 0
        assert second.skipped == 1
        so_count_again, line_count_again = await _supplier_counts(session, order_id)
        assert so_count_again == 1
        assert line_count_again == item_count


@pytest.mark.asyncio
async def test_backfill_skips_order_without_legacy_tp_id(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order_id = order.id
        assert not order.supplier_order_id
        await SupplierOrderService(session).backfill_legacy(order_id=order_id)
        so_count, line_count = await _supplier_counts(session, order_id)
        assert so_count == 0
        assert line_count == 0


@pytest.mark.asyncio
async def test_start_assembling_does_not_create_supplier_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    now = utc_now_naive()
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.payment_paid_at = now
        await session.commit()
        order_id = order.id
        result = await OrderService(session).start_order_assembling(
            order_id,
            AdminStartAssemblingUpdate(supplier_order_id=f"SUP-3A-LIFE-{suffix}"),
            actor=buyer,
        )
        assert result.status == OrderStatus.ASSEMBLING
        so_count, _line_count = await _supplier_counts(session, order_id)
        assert so_count == 0
        persisted = await session.get(Order, order_id)
        assert persisted is not None
        assert persisted.supplier_order_id == f"SUP-3A-LIFE-{suffix}"
        assert persisted.status == OrderStatus.ASSEMBLING


@pytest.mark.asyncio
async def test_admin_order_detail_shows_readonly_supplier_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        await _prepare_legacy_items(session, order, items, suffix)
        order_id = order.id
        product_id = items[0].product_id
        tp_id = str(order.supplier_order_id)
        await SupplierOrderService(session).backfill_legacy(order_id=order_id)
        _, admin_token = await create_admin_access_token(session, suffix + 1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            f"/internal/admin/orders?id={order_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    body = response.text
    assert "Поставщик" in body
    assert "Посылка" in body
    assert tp_id in body
    assert "29.99" in body
    assert f"/internal/admin/products?id={product_id}" in body
    assert "order-summary-mock-line__title--link" in body


@pytest.mark.asyncio
async def test_list_item_allocations_after_backfill_is_fully_allocated(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        await _prepare_legacy_items(session, order, items, suffix)
        order_id = order.id
        service = SupplierOrderService(session)
        await service.backfill_legacy(order_id=order_id)
        views = await service.list_item_allocations(order_id)
        assert views
        assert all(view.remaining_qty == 0 for view in views)
        assert all(view.allocated_qty == view.ordered_qty for view in views)
