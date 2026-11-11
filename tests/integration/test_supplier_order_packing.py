from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.order_limits import max_supplier_goods_eur
from src.main import app
from src.models.order import (
    Order,
    OrderItem,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.schemas.order import AdminOrderItemsUpdate, AdminOrderItemUpdate
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import (
    SupplierOrderAllocationError,
    SupplierOrderService,
)
from src.services.payment_service import PaymentService
from src.services.pricing.service import PricingService
from tests.fixtures.sbp_callback import (
    build_sbp_accepted_payload,
    ensure_sbp_payment_attempt,
)
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
    set_product_available_stock,
)

pytestmark = pytest.mark.integration


# True, если блок packing вложен в form сохранения состава.
def _packing_nested_in_items_form(html: str) -> bool:
    marker = 'id="order-supplier-orders"'
    idx = html.find(marker)
    if idx < 0:
        return False
    form_open = html.rfind("<form", 0, idx)
    if form_open < 0:
        return False
    if html.find("</form>", form_open, idx) != -1:
        return False
    tag_end = html.find(">", form_open)
    tag = html[form_open : tag_end + 1]
    return "/items" in tag and "supplier-orders" not in tag


_UNIT = Decimal("34.00")
_RATE = Decimal("100")


# Выставляет клиентский unit доставки и возвращает предыдущее значение.
async def _set_delivery_fee(session: AsyncSession, value: Decimal) -> Decimal:
    row = await PricingService(session).get_settings()
    previous = Decimal(str(row.delivery_fee_eur))
    row.delivery_fee_eur = value
    await session.commit()
    return previous


# Собирает неоплаченный заказ с заданной закупочной EUR.
async def _create_packing_order(
    session: AsyncSession,
    suffix: int,
    supplier_eur: Decimal,
    quantity: int = 1,
) -> tuple[Order, list[OrderItem]]:
    buyer = await create_telegram_user(session, suffix)
    product_id = await pick_active_product_id(session)
    await set_product_available_stock(session, product_id, 100)
    line_spec = await resolve_product_line_spec(
        session, product_id, Decimal("1000"), quantity
    )
    goods = supplier_eur * quantity
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.create_order_with_items(
        user_id=buyer.id,
        total_amount=Decimal("4340"),
        items_subtotal_amount=Decimal("1000"),
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=_UNIT,
        delivery_fee_amount=_UNIT * _RATE,
        eur_rate_snapshot=_RATE,
        promo_code_applied=None,
        supplier_cost_eur_snapshot=goods,
        items_payload=[
            {
                "product_id": line_spec[0],
                "variant_id": line_spec[1],
                "quantity": quantity,
                "unit_price": line_spec[2],
                "product_title_captured": "Packing item",
                "supplier_price_eur_captured": supplier_eur,
            }
        ],
        idempotency_key=f"packing-3c-{suffix}",
    )
    items = await order_crud.get_order_items(order.id)
    for item in items:
        item.supplier_price_eur_captured = supplier_eur
        item.product_title_captured = item.product_title_captured or "Packing item"
    await session.commit()
    return order, items


# Считает active SO (draft+placed).
async def _actual_count(session: AsyncSession, order_id: int) -> int:
    headers = (
        await session.scalars(
            select(SupplierOrder).where(SupplierOrder.order_id == order_id)
        )
    ).all()
    return sum(
        1 for header in headers if str(header.status) != SupplierOrderStatus.CANCELLED
    )


@pytest.mark.asyncio
async def test_draft_create_delete_and_empty_counts_as_actual(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, _items = await _create_packing_order(
                session, suffix, Decimal("200.00")
            )
            service = SupplierOrderService(session)
            first = await service.create_draft(order.id)
            await session.refresh(order)
            assert await _actual_count(session, order.id) == 1
            assert order.delivery_fee_eur_snapshot == Decimal("34.00")
            second = await service.create_draft(order.id)
            third = await service.create_draft(order.id)
            await session.refresh(order)
            assert await _actual_count(session, order.id) == 3
            assert order.delivery_fee_eur_snapshot == Decimal("102.00")
            await service.delete_draft(order.id, second.id)
            await session.refresh(order)
            assert await _actual_count(session, order.id) == 2
            assert order.delivery_fee_eur_snapshot == Decimal("68.00")
            assert first.id != third.id
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_split_allocation_and_over_allocation(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            item_id = items[0].id
            service = SupplierOrderService(session)
            so1 = await service.create_draft(order.id)
            so1_id = int(so1.id)
            so2 = await service.create_draft(order.id)
            so2_id = int(so2.id)
            await service.save_draft_lines(order.id, so1_id, {item_id: 2})
            await service.save_draft_lines(order.id, so2_id, {item_id: 3})
            views = await service.list_item_allocations(order.id)
            assert views[0].allocated_qty == 5
            assert views[0].remaining_qty == 0
            with pytest.raises(SupplierOrderAllocationError):
                await service.save_draft_lines(order.id, so2_id, {item_id: 4})
            lines = (
                await session.scalars(
                    select(SupplierOrderLine).where(
                        SupplierOrderLine.supplier_order_id == so2_id
                    )
                )
            ).all()
            assert [int(line.quantity) for line in lines] == [3]
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_leftover_and_goods_cap(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("270.01"), quantity=1
            )
            item_id = items[0].id
            service = SupplierOrderService(session)
            header = await service.create_draft(order.id)
            await service.save_draft_lines(order.id, header.id, {item_id: 1})
            await session.refresh(header)
            assert header.goods_eur == Decimal("270.01")
            order2, _items2 = await _create_packing_order(
                session, suffix + 1, Decimal("270.02"), quantity=1
            )
            # Единица выше капа: sync в create_draft идёт через пакер и бросает
            # ту же ошибку. Это не смена текста ошибки.
            with pytest.raises(SupplierOrderAllocationError, match="дороже лимита"):
                await service.create_draft(order2.id)
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_delivery_follows_billed_n_without_opening_packing_ui(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("250.00"), quantity=1
            )
            service = SupplierOrderService(session)
            await service.create_draft(order.id)
            await session.refresh(order)
            assert order.delivery_fee_eur_snapshot == Decimal("34.00")
            _result, _warning = await OrderService(session).edit_order_composition(
                order.id,
                AdminOrderItemsUpdate(
                    items=[
                        AdminOrderItemUpdate(
                            id=items[0].id, quantity=2, unit_price=Decimal("1000")
                        )
                    ],
                    notify_customer=False,
                ),
            )
            await session.refresh(order)
            assert Decimal(str(order.supplier_cost_eur_snapshot)) == Decimal("500.00")
            assert order.delivery_fee_eur_snapshot == Decimal("68.00")
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_composition_rejects_qty_below_allocated(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            order_id = int(order.id)
            item_id = int(items[0].id)
            so_service = SupplierOrderService(session)
            header = await so_service.create_draft(order_id)
            header_id = int(header.id)
            await so_service.save_draft_lines(order_id, header_id, {item_id: 3})
            with pytest.raises(SupplierOrderAllocationError, match="ниже"):
                await OrderService(session).edit_order_composition(
                    order_id,
                    AdminOrderItemsUpdate(
                        items=[
                            AdminOrderItemUpdate(
                                id=item_id, quantity=2, unit_price=Decimal("1000")
                            )
                        ],
                        notify_customer=False,
                    ),
                )
            with pytest.raises(SupplierOrderAllocationError, match="удалить"):
                await OrderService(session).edit_order_composition(
                    order_id,
                    AdminOrderItemsUpdate(
                        remove_item_ids=[item_id], notify_customer=False
                    ),
                )
            fresh_item = await session.get(OrderItem, item_id)
            assert fresh_item is not None
            assert fresh_item.quantity == 5
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_delete_unallocated_item_still_allowed(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=1
            )
            product_id = await pick_active_product_id(session)
            extra = await resolve_product_line_spec(
                session, product_id, Decimal("100"), 1
            )
            extra_item = OrderItem(
                order_id=order.id,
                product_id=extra[0],
                variant_id=extra[1],
                quantity=1,
                unit_price=extra[2],
                product_title_captured="Unallocated",
                supplier_price_eur_captured=Decimal("10.00"),
            )
            session.add(extra_item)
            await session.commit()
            extra_id = extra_item.id
            await OrderService(session).edit_order_composition(
                order.id,
                AdminOrderItemsUpdate(
                    remove_item_ids=[extra_id], notify_customer=False
                ),
            )
            gone = await session.get(OrderItem, extra_id)
            assert gone is None
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_payment_freezes_paid_n_and_blocks_fourth_so(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            # Unit <= cap: sync не должен падать. Freeze проверяет actual, не over-cap.
            order, _items = await _create_packing_order(
                session, suffix, Decimal("200.00")
            )
            service = SupplierOrderService(session)
            await service.create_draft(order.id)
            await service.create_draft(order.id)
            await service.create_draft(order.id)
            await session.refresh(order)
            assert order.paid_supplier_order_count is None
            snapshot = order.delivery_fee_eur_snapshot
            attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
            await session.commit()
            await PaymentService(session).handle_sbp_callback(
                build_sbp_accepted_payload(provider_id, attempt)
            )
            await session.refresh(order)
            assert order.paid_supplier_order_count == 3
            assert order.delivery_fee_eur_snapshot == snapshot
            row = await PricingService(session).get_settings()
            row.delivery_fee_eur = Decimal("40.00")
            await session.commit()
            await session.refresh(order)
            assert order.paid_supplier_order_count == 3
            with pytest.raises(SupplierOrderAllocationError, match="После оплаты"):
                await service.create_draft(order.id)
            await session.refresh(order)
            assert order.delivery_fee_eur_snapshot == snapshot
            assert await _actual_count(session, order.id) == 3
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_placed_immutable_and_cancelled_excluded(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            order_id = int(order.id)
            item_id = int(items[0].id)
            service = SupplierOrderService(session)
            placed = await service.create_draft(order_id)
            cancelled = await service.create_draft(order_id)
            placed_id = int(placed.id)
            cancelled_id = int(cancelled.id)
            await service.save_draft_lines(order_id, placed_id, {item_id: 2})
            placed_row = await session.get(SupplierOrder, placed_id)
            cancelled_row = await session.get(SupplierOrder, cancelled_id)
            assert placed_row is not None and cancelled_row is not None
            placed_row.status = SupplierOrderStatus.PLACED
            cancelled_row.status = SupplierOrderStatus.CANCELLED
            await session.commit()
            with pytest.raises(SupplierOrderAllocationError, match="оформленного"):
                await service.save_draft_lines(order_id, placed_id, {item_id: 1})
            views = await service.list_item_allocations(order_id)
            assert views[0].allocated_qty == 2
            packing = await service.packing_context(order_id)
            assert packing["actual_count"] == 1
            assert packing["goods_cap_eur"] == max_supplier_goods_eur()
            row = packing["remaining_rows"][0]
            assert row["ordered_qty"] >= row["allocated_qty"]
            assert row["unit_supplier_eur"] is not None
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_invalid_packing_does_not_change_delivery(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            item_id = items[0].id
            service = SupplierOrderService(session)
            header = await service.create_draft(order.id)
            await service.save_draft_lines(order.id, header.id, {item_id: 2})
            await session.refresh(order)
            await session.refresh(header)
            delivery = order.delivery_fee_eur_snapshot
            total = order.total_amount
            goods = header.goods_eur
            with pytest.raises(SupplierOrderAllocationError):
                await service.save_draft_lines(order.id, header.id, {item_id: 9})
            await session.refresh(order)
            await session.refresh(header)
            assert order.delivery_fee_eur_snapshot == delivery
            assert order.total_amount == total
            assert header.goods_eur == goods
            lines = (
                await session.scalars(
                    select(SupplierOrderLine).where(
                        SupplierOrderLine.supplier_order_id == header.id
                    )
                )
            ).all()
            assert [int(line.quantity) for line in lines] == [2]
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_packing_http_flow(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("250.00"), quantity=1
        )
        order_id = order.id
        item_id = items[0].id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            created = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders",
                data={},
                headers=headers,
            )
            assert created.status_code == 303
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert "Сборка посылок" in detail.text
            assert "Пересчитать рекомендацию" in detail.text
            assert "order-supplier-orders" in detail.text

            async with async_session_maker() as session:
                so = await session.scalar(
                    select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                )
                assert so is not None
                so_id = so.id

            saved = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "1"},
                headers=headers,
            )
            assert saved.status_code == 303
            assert "error=" not in saved.headers.get("location", "")

            await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders",
                data={},
                headers=headers,
            )
            await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders",
                data={},
                headers=headers,
            )
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert "102.00" in detail.text or "102" in detail.text

            over = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "9"},
                headers=headers,
            )
            assert over.status_code == 303
            assert "error=" in over.headers.get("location", "")
            location_error = parse_qs(urlparse(over.headers["location"]).query).get(
                "error", [""]
            )[0]
            assert location_error

            compose = await client.post(
                f"/internal/admin/orders/{order_id}/items",
                data={
                    f"item_{item_id}_qty": "2",
                    f"item_{item_id}_price": "1000",
                },
                headers=headers,
            )
            assert compose.status_code == 303

        async with async_session_maker() as session:
            order = await session.get(Order, order_id)
            assert order is not None
            assert order.delivery_fee_eur_snapshot >= Decimal("68.00")
            assert await _actual_count(session, order_id) == 3
            item = await session.get(OrderItem, item_id)
            assert item is not None
            assert item.quantity == 2
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_packing_html_not_nested_in_composition_form(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, _items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=1
        )
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert 'id="order-supplier-orders"' in detail.text
            assert "Ручная сборка" in detail.text
            assert "Рекомендовать сборку" in detail.text
            assert not _packing_nested_in_items_form(detail.text)
            assert (
                f"/internal/admin/orders/{order_id}/start-assembling" not in detail.text
            )
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_paid_assembly_shows_packing_not_legacy_cta(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, _items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=1
        )
        order_id = order.id
        attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await PaymentService(session).handle_sbp_callback(
            build_sbp_accepted_payload(provider_id, attempt)
        )
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert 'id="order-supplier-orders"' in detail.text
            assert "Ручная сборка" in detail.text
            assert "Добавьте посылку" in detail.text
            assert not _packing_nested_in_items_form(detail.text)
            assert (
                f"/internal/admin/orders/{order_id}/start-assembling" not in detail.text
            )
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_save_lines_refreshes_goods_in_html(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("64.62"), quantity=3
        )
        order_id = order.id
        item_id = items[0].id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            created = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders",
                data={},
                headers=headers,
            )
            assert created.status_code == 303
            async with async_session_maker() as session:
                so = await session.scalar(
                    select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                )
                assert so is not None
                so_id = so.id
            saved = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "1"},
                headers=headers,
            )
            assert saved.status_code == 303
            assert "error=" not in saved.headers.get("location", "")
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert "64.62 € / 270.01 €" in detail.text
            assert "205.39" in detail.text
            assert 'aria-valuenow="24"' in detail.text
            assert f'name="line_{item_id}_qty"' in detail.text
            assert "Черновик" in detail.text
            assert "Сборка посылок" in detail.text
            assert "Не распределено: 2" in detail.text
            assert "1 шт × 64.62 €" in detail.text
            assert "Заказано:" not in detail.text
            assert "Доступные товары" not in detail.text
            async with async_session_maker() as session:
                so = await session.get(SupplierOrder, so_id)
                assert so is not None
                assert str(so.status) == SupplierOrderStatus.DRAFT
                so.goods_eur = Decimal("0.00")
                await session.commit()
            stale = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert "64.62 € / 270.01 €" in stale.text
            over = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "9"},
                headers=headers,
            )
            assert over.status_code == 303
            assert "error=" in over.headers.get("location", "")
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_packing_recommendation_preview_apply_and_rerun(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, _items = await _create_packing_order(
            session, suffix, Decimal("100.00"), quantity=5
        )
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            preview = await client.get(
                f"/internal/admin/orders?id={order_id}&packing_preview=1",
                headers=headers,
            )
            assert preview.status_code == 200
            assert "Рекомендация сборки" in preview.text
            assert "Оптимально:" in preview.text
            assert "3" in preview.text
            assert "Packing item" in preview.text
            assert "2 × 100.00 €" in preview.text
            assert "Осталось:" in preview.text
            assert "270.01" in preview.text
            assert "Применить рекомендацию" in preview.text
            assert 'name="line_' not in preview.text
            assert "+ Добавить посылку" not in preview.text
            async with async_session_maker() as session:
                assert await _actual_count(session, order_id) == 0
            applied = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/recommend",
                data={},
                headers=headers,
            )
            assert applied.status_code == 303
            assert "error=" not in applied.headers.get("location", "")
            async with async_session_maker() as session:
                rows = (
                    await session.scalars(
                        select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                    )
                ).all()
                drafts = [
                    row for row in rows if str(row.status) == SupplierOrderStatus.DRAFT
                ]
                assert len(drafts) == 3
                goods = sorted(Decimal(str(row.goods_eur)) for row in drafts)
                assert goods == [
                    Decimal("100.00"),
                    Decimal("200.00"),
                    Decimal("200.00"),
                ]
                for row in drafts:
                    assert Decimal(str(row.goods_eur)) <= max_supplier_goods_eur()
                lines = (await session.scalars(select(SupplierOrderLine))).all()
                by_so = {}
                for line in lines:
                    if line.supplier_order_id in {row.id for row in drafts}:
                        by_so.setdefault(line.supplier_order_id, []).append(
                            int(line.quantity)
                        )
                qty_sets = sorted(tuple(sorted(q)) for q in by_so.values())
                assert qty_sets == [(1,), (2,), (2,)]
            again = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/recommend",
                data={},
                headers=headers,
            )
            assert again.status_code == 303
            assert "error=" not in again.headers.get("location", "")
            async with async_session_maker() as session:
                assert await _actual_count(session, order_id) == 3
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert "200.00 € / 270.01 €" in detail.text
            assert "100.00 € / 270.01 €" in detail.text
            assert "Все товары распределены" in detail.text
            assert "Распределено:" in detail.text
            assert "Заказано:" not in detail.text
            assert "Доступные товары" not in detail.text
            assert "Пересчитать рекомендацию" in detail.text
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_apply_recommendation_does_not_change_placed(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            order_id = int(order.id)
            item_id = int(items[0].id)
            service = SupplierOrderService(session)
            placed = await service.create_draft(order_id)
            await service.save_draft_lines(order_id, placed.id, {item_id: 2})
            placed_row = await session.get(SupplierOrder, placed.id)
            assert placed_row is not None
            placed_row.status = SupplierOrderStatus.PLACED
            await session.commit()
            preview = await service.packing_recommendation(order_id)
            assert preview.can_apply is True
            assert len(preview.parcels) == 1
            await service.apply_packing_recommendation(order_id)
            rows = (
                await session.scalars(
                    select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                )
            ).all()
            placed_after = [
                row for row in rows if str(row.status) == SupplierOrderStatus.PLACED
            ]
            drafts = [
                row for row in rows if str(row.status) == SupplierOrderStatus.DRAFT
            ]
            assert len(placed_after) == 1
            assert placed_after[0].id == placed.id
            lines = await session.scalars(
                select(SupplierOrderLine).where(
                    SupplierOrderLine.supplier_order_id == placed.id
                )
            )
            assert [int(line.quantity) for line in lines] == [2]
            assert len(drafts) == 1
            views = await service.list_item_allocations(order_id)
            assert views[0].allocated_qty == 5
            assert views[0].remaining_qty == 0
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_apply_recommendation_does_not_change_cancelled(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=5
            )
            order_id = int(order.id)
            service = SupplierOrderService(session)
            cancelled = await service.create_draft(order_id)
            cancelled_id = int(cancelled.id)
            cancelled_row = await session.get(SupplierOrder, cancelled_id)
            assert cancelled_row is not None
            cancelled_row.status = SupplierOrderStatus.CANCELLED
            await session.commit()
            preview = await service.packing_recommendation(order_id)
            assert preview.can_apply is True
            await service.apply_packing_recommendation(order_id)
            cancelled_after = await session.get(SupplierOrder, cancelled_id)
            assert cancelled_after is not None
            assert cancelled_after.id == cancelled_id
            assert str(cancelled_after.status) == SupplierOrderStatus.CANCELLED
            rows = (
                await session.scalars(
                    select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                )
            ).all()
            drafts = [
                row for row in rows if str(row.status) == SupplierOrderStatus.DRAFT
            ]
            assert len(drafts) >= 1
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_recommendation_paid_n_matches_packer_for_split_units(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, _items = await _create_packing_order(
            session, suffix, Decimal("200.00"), quantity=5
        )
        order_id = int(order.id)
        service = SupplierOrderService(session)
        leftover_draft = await service.create_draft(order_id)
        leftover_id = int(leftover_draft.id)
        attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await PaymentService(session).handle_sbp_callback(
            build_sbp_accepted_payload(provider_id, attempt)
        )
        await session.refresh(order)
        # 5×200: ceil давал 4, пакер — 5. Меняется billing N, не алгоритм раскладки.
        paid_n = int(order.paid_supplier_order_count or 0)
        preview = await service.packing_recommendation(order_id)
        assert paid_n == 5
        assert preview.needed_count == paid_n
        assert preview.paid_n_blocked is False
        assert preview.can_apply is True
        assert "оплачено только" not in (preview.block_reason or "")
        still = await session.get(SupplierOrder, leftover_id)
        assert still is not None
        assert str(still.status) == SupplierOrderStatus.DRAFT
        assert await _actual_count(session, order_id) == 1
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            html = await client.get(
                f"/internal/admin/orders?id={order_id}&packing_preview=1",
                headers=headers,
            )
            assert html.status_code == 200
            assert "Нельзя применить рекомендацию" not in html.text
            assert "Применить рекомендацию" in html.text
        async with async_session_maker() as session:
            assert await _actual_count(session, order_id) == 1
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_recommendation_paid_n_allows_when_within_cap(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, _items = await _create_packing_order(
                session, suffix, Decimal("100.00"), quantity=2
            )
            order_id = int(order.id)
            attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
            await session.commit()
            await PaymentService(session).handle_sbp_callback(
                build_sbp_accepted_payload(provider_id, attempt)
            )
            await session.refresh(order)
            assert int(order.paid_supplier_order_count or 0) >= 1
            service = SupplierOrderService(session)
            preview = await service.packing_recommendation(order_id)
            assert preview.can_apply is True
            assert preview.paid_n_blocked is False
            assert preview.needed_count <= int(order.paid_supplier_order_count or 0)
            await service.apply_packing_recommendation(order_id)
            assert await _actual_count(session, order_id) == len(preview.parcels)
        finally:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_manual_plus_disabled_when_next_unit_exceeds_cap(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("255.33"), quantity=2
        )
        order_id = order.id
        item_id = items[0].id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            created = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders",
                data={},
                headers=headers,
            )
            assert created.status_code == 303
            async with async_session_maker() as session:
                so = await session.scalar(
                    select(SupplierOrder).where(SupplierOrder.order_id == order_id)
                )
                assert so is not None
                so_id = so.id
            saved = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "1"},
                headers=headers,
            )
            assert saved.status_code == 303
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert "Не помещается в эту посылку" in detail.text
            assert "Доступно:" in detail.text
            assert "14.68" in detail.text
            assert 'data-qty-plus aria-label="Больше" disabled' in detail.text
            assert 'max="1"' in detail.text
            over = await client.post(
                f"/internal/admin/orders/{order_id}/supplier-orders/{so_id}/lines",
                data={f"line_{item_id}_qty": "2"},
                headers=headers,
            )
            assert over.status_code == 303
            assert "error=" in over.headers.get("location", "")
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_packing_manual_shows_available_list_not_on_result(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, _items = await _create_packing_order(
            session, suffix, Decimal("64.62"), quantity=3
        )
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            result = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert result.status_code == 200
            assert "Доступные товары" not in result.text
            assert "Не распределено: 3" in result.text
            manual = await client.get(
                f"/internal/admin/orders?id={order_id}&packing_manual=1",
                headers=headers,
            )
            assert manual.status_code == 200
            assert "Доступные товары" in manual.text
            assert "Заказано: 3" in manual.text
            assert "Распределено: 0" in manual.text
            assert "Осталось: 3" in manual.text
            assert "+ Добавить посылку" in manual.text
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_preview_does_not_mutate_existing_drafts(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        try:
            order, items = await _create_packing_order(
                session, suffix, Decimal("40.00"), quantity=2
            )
            order_id = int(order.id)
            item_id = int(items[0].id)
            service = SupplierOrderService(session)
            draft = await service.create_draft(order_id)
            draft_id = int(draft.id)
            await service.save_draft_lines(order_id, draft_id, {item_id: 1})
            _, admin_token = await create_admin_access_token(session, suffix + 9)
        finally:
            await _set_delivery_fee(session, previous)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        headers = {"Authorization": f"Bearer {admin_token}"}
        preview = await client.get(
            f"/internal/admin/orders?id={order_id}&packing_preview=1",
            headers=headers,
        )
        assert preview.status_code == 200
        assert "Рекомендация сборки" in preview.text
        assert 'name="line_' not in preview.text
    async with async_session_maker() as session:
        row = await session.get(SupplierOrder, draft_id)
        assert row is not None
        assert str(row.status) == SupplierOrderStatus.DRAFT
        assert await _actual_count(session, order_id) == 1
        lines = (
            await session.scalars(
                select(SupplierOrderLine).where(
                    SupplierOrderLine.supplier_order_id == draft_id
                )
            )
        ).all()
        assert [int(line.quantity) for line in lines] == [1]


@pytest.mark.asyncio
async def test_placed_parcel_has_no_edit_controls(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = int(order.id)
        item_id = int(items[0].id)
        service = SupplierOrderService(session)
        placed = await service.create_draft(order_id)
        placed_id = int(placed.id)
        await service.save_draft_lines(order_id, placed_id, {item_id: 2})
        await service.place_draft(order_id, placed_id, f"TP-{suffix}")
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert "Оформлен" in detail.text
            assert f"TP-{suffix}" in detail.text
            assert f'name="line_{item_id}_qty"' not in detail.text
            assert "Сохранить состав" not in detail.text
            assert "Удалить черновик" not in detail.text
            assert "Все товары распределены" in detail.text
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_leftover_after_first_place_stays_assembly(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("40.00"), quantity=2
        )
        order_id = int(order.id)
        item_id = int(items[0].id)
        attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await PaymentService(session).handle_sbp_callback(
            build_sbp_accepted_payload(provider_id, attempt)
        )
        service = SupplierOrderService(session)
        draft = await service.create_draft(order_id)
        await service.save_draft_lines(order_id, int(draft.id), {item_id: 1})
        tp = f"TP-{suffix}"
        await service.place_draft(order_id, int(draft.id), tp)
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": "Bearer " + admin_token}
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            assert detail.status_code == 200
            assert 'id="order-action-now-assembly"' in detail.text
            assert tp in detail.text
            assert "Проверить все посылки" not in detail.text
            assert "Сверить с Supplier-Demo" not in detail.text
            assert 'name="supplier_tracking_id"' not in detail.text
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)


@pytest.mark.asyncio
async def test_admin_two_placed_shows_independent_delivery_cards(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    previous = _UNIT
    async with async_session_maker() as session:
        previous = await _set_delivery_fee(session, _UNIT)
        order, items = await _create_packing_order(
            session, suffix, Decimal("200.00"), quantity=2
        )
        order_id = int(order.id)
        item_id = int(items[0].id)
        attempt, provider_id = await ensure_sbp_payment_attempt(session, order)
        await session.commit()
        await PaymentService(session).handle_sbp_callback(
            build_sbp_accepted_payload(provider_id, attempt)
        )
        service = SupplierOrderService(session)
        first = await service.create_draft(order_id)
        await service.save_draft_lines(order_id, int(first.id), {item_id: 1})
        tp1 = f"TP-{suffix}-A"
        await service.place_draft(order_id, int(first.id), tp1)
        second = await service.create_draft(order_id)
        await service.save_draft_lines(order_id, int(second.id), {item_id: 1})
        tp2 = f"TP-{suffix}-B"
        await service.place_draft(order_id, int(second.id), tp2)
        ships = (
            await session.scalars(select(Shipment).where(Shipment.order_id == order_id))
        ).all()
        assert len(ships) == 2
        ships[0].supplier_tracking_number = "CJ-AAA"
        ships[0].supplier_carrier = "DHL"
        ships[0].status = ShipmentStatus.DELIVERED
        ships[1].supplier_tracking_number = "CJ-BBB"
        ships[1].status = ShipmentStatus.IN_TRANSIT
        await session.commit()
        _, admin_token = await create_admin_access_token(session, suffix + 9)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            headers = {"Authorization": "Bearer " + admin_token}
            detail = await client.get(
                f"/internal/admin/orders?id={order_id}", headers=headers
            )
            html = detail.text
            assert detail.status_code == 200
            assert "Проверить все посылки" in html
            assert "Сверить с Supplier-Demo" not in html
            assert 'name="supplier_tracking_id"' not in html
            assert tp1 in html
            assert tp2 in html
            assert "CJ-AAA" in html
            assert "CJ-BBB" in html
            assert "Доставлена" in html
            assert "В пути" in html
            assert "Сборка завершена" in html
            assert html.count("Проверить все посылки") == 1
            assert "/internal/admin/orders/" + str(order_id) + "/tracking/check" in html
    finally:
        async with async_session_maker() as session:
            await _set_delivery_fee(session, previous)
