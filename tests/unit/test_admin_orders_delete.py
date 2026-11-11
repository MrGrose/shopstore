import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models.order import (
    Order,
    OrderItem,
    OrderStatus,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService
from src.services.user_service import UserService
from tests.integration.helpers.order_admin import create_telegram_user


# Минимальный payload позиции для create_order_with_items.
def _item_payload() -> dict[str, int | Decimal | str | None]:
    return {
        "product_id": 1,
        "product_external_id": "ext-delete-test",
        "product_title": "Test",
        "variant_id": None,
        "variant_external_id": None,
        "variant_sku": None,
        "option1": None,
        "option2": None,
        "option3": None,
        "quantity": 1,
        "unit_price": 1000,
        "supplier_price_eur": 10,
    }


# Собирает заказ с N одинаковыми позициями.
async def _create_order(
    session,
    suffix: int,
    item_count: int = 1,
) -> tuple[User, Order, list[OrderItem]]:
    user = await create_telegram_user(session, suffix)
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.create_order_with_items(
        user_id=int(user.id),
        total_amount=1000 * item_count,
        items_subtotal_amount=1000 * item_count,
        discount_items_amount=0,
        delivery_fee_eur_snapshot=0,
        delivery_fee_amount=0,
        eur_rate_snapshot=100,
        promo_code_applied=None,
        items_payload=[_item_payload() for _ in range(item_count)],
        status=OrderStatus.COMPLETED.value,
        idempotency_key=f"admin-del-{suffix}-{uuid.uuid4().hex[:8]}",
    )
    items = list(await order_crud.get_order_items(int(order.id)))
    return user, order, items


# Добавляет SupplierOrder и опционально lines/Shipment только для этого order_id.
async def _add_supplier_graph(
    session,
    order_id: int,
    seq: int,
    item_ids: list[int],
    placed: bool,
    token: str,
) -> tuple[SupplierOrder, list[SupplierOrderLine], Shipment | None]:
    header = SupplierOrder(
        order_id=order_id,
        seq=seq,
        status=(
            SupplierOrderStatus.PLACED.value
            if placed
            else SupplierOrderStatus.DRAFT.value
        ),
        external_id=token if placed else None,
        goods_eur=Decimal("10.00"),
        supplier_shipping_eur=Decimal("29.99"),
    )
    session.add(header)
    await session.flush()
    lines: list[SupplierOrderLine] = []
    for item_id in item_ids:
        line = SupplierOrderLine(
            supplier_order_id=int(header.id),
            order_item_id=item_id,
            quantity=1,
            unit_supplier_eur=Decimal("10.00"),
        )
        session.add(line)
        lines.append(line)
    shipment = None
    if placed:
        shipment = Shipment(
            order_id=order_id,
            supplier_order_id=int(header.id),
            status=ShipmentStatus.PREPARING.value,
        )
        session.add(shipment)
    await session.flush()
    return header, lines, shipment


# Число SO / lines / Shipment, привязанных к заказу.
async def _graph_counts(session, order_id: int) -> tuple[int, int, int]:
    so_ids = list(
        await session.scalars(
            select(SupplierOrder.id).where(SupplierOrder.order_id == order_id)
        )
    )
    line_count = 0
    if so_ids:
        line_count = len(
            list(
                await session.scalars(
                    select(SupplierOrderLine.id).where(
                        SupplierOrderLine.supplier_order_id.in_(so_ids)
                    )
                )
            )
        )
    shipment_count = len(
        list(
            await session.scalars(
                select(Shipment.id).where(Shipment.order_id == order_id)
            )
        )
    )
    return len(so_ids), line_count, shipment_count


@pytest.mark.asyncio
async def test_admin_delete_orders_by_ids_removes_order() -> None:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, 99001)
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=int(user.id),
            total_amount=1000,
            items_subtotal_amount=1000,
            discount_items_amount=0,
            delivery_fee_eur_snapshot=0,
            delivery_fee_amount=0,
            eur_rate_snapshot=100,
            promo_code_applied=None,
            items_payload=[
                {
                    "product_id": 1,
                    "product_external_id": "ext-delete-test",
                    "product_title": "Test",
                    "variant_id": None,
                    "variant_external_id": None,
                    "variant_sku": None,
                    "option1": None,
                    "option2": None,
                    "option3": None,
                    "quantity": 1,
                    "unit_price": 1000,
                    "supplier_price_eur": 10,
                }
            ],
            status=OrderStatus.COMPLETED.value,
        )
        order_id = int(order.id)
        service = OrderService(session)
        deleted = await service.admin_delete_orders_by_ids([order_id])
        assert deleted == 1
        assert await order_crud.get_by_id(order_id) is None
        items = await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        assert list(items.all()) == []


@pytest.mark.asyncio
async def test_admin_delete_orders_by_ids_requires_selection() -> None:
    async with async_session_maker() as session:
        service = OrderService(session)
        with pytest.raises(ValueError, match="Не выбраны заказы"):
            await service.admin_delete_orders_by_ids([])


@pytest.mark.asyncio
async def test_admin_delete_order_with_draft_supplier_order() -> None:
    suffix = uuid.uuid4().int % 90_000_000 + 200_000
    async with async_session_maker() as session:
        _user, order, _items = await _create_order(session, suffix)
        order_id = int(order.id)
        await _add_supplier_graph(
            session, order_id, seq=1, item_ids=[], placed=False, token=""
        )
        await session.commit()
        deleted = await OrderService(session).admin_delete_orders_by_ids([order_id])
        assert deleted == 1
        assert await session.get(Order, order_id) is None
        assert await _graph_counts(session, order_id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_admin_delete_order_with_placed_so_lines_and_shipment() -> None:
    suffix = uuid.uuid4().int % 90_000_000 + 200_000
    token = f"del-so-{suffix}"
    async with async_session_maker() as session:
        _user, order, items = await _create_order(session, suffix, item_count=2)
        order_id = int(order.id)
        await _add_supplier_graph(
            session,
            order_id,
            seq=1,
            item_ids=[int(items[0].id), int(items[1].id)],
            placed=True,
            token=token,
        )
        await session.commit()
        deleted = await OrderService(session).admin_delete_orders_by_ids([order_id])
        assert deleted == 1
        assert await session.get(Order, order_id) is None
        assert await _graph_counts(session, order_id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_admin_delete_order_with_several_so_and_shipments() -> None:
    suffix = uuid.uuid4().int % 90_000_000 + 200_000
    async with async_session_maker() as session:
        _user, order, items = await _create_order(session, suffix, item_count=2)
        order_id = int(order.id)
        await _add_supplier_graph(
            session,
            order_id,
            seq=1,
            item_ids=[int(items[0].id)],
            placed=True,
            token=f"del-so-{suffix}-1",
        )
        await _add_supplier_graph(
            session,
            order_id,
            seq=2,
            item_ids=[int(items[1].id)],
            placed=True,
            token=f"del-so-{suffix}-2",
        )
        await session.commit()
        assert await _graph_counts(session, order_id) == (2, 2, 2)
        deleted = await OrderService(session).admin_delete_orders_by_ids([order_id])
        assert deleted == 1
        assert await session.get(Order, order_id) is None
        assert await _graph_counts(session, order_id) == (0, 0, 0)


@pytest.mark.asyncio
async def test_admin_delete_order_a_leaves_order_b_graph() -> None:
    suffix_a = uuid.uuid4().int % 90_000_000 + 200_000
    suffix_b = suffix_a + 1
    async with async_session_maker() as session:
        _user_a, order_a, items_a = await _create_order(session, suffix_a, item_count=2)
        _user_b, order_b, items_b = await _create_order(session, suffix_b, item_count=1)
        order_a_id = int(order_a.id)
        order_b_id = int(order_b.id)
        header_a, _lines_a, shipment_a = await _add_supplier_graph(
            session,
            order_a_id,
            seq=1,
            item_ids=[int(items_a[0].id), int(items_a[1].id)],
            placed=True,
            token=f"del-so-{suffix_a}",
        )
        header_b, lines_b, shipment_b = await _add_supplier_graph(
            session,
            order_b_id,
            seq=1,
            item_ids=[int(items_b[0].id)],
            placed=True,
            token=f"del-so-{suffix_b}",
        )
        await session.commit()
        so_b_id = int(header_b.id)
        line_b_id = int(lines_b[0].id)
        shipment_b_id = int(shipment_b.id) if shipment_b is not None else 0
        deleted = await OrderService(session).admin_delete_orders_by_ids([order_a_id])
        assert deleted == 1
        assert await session.get(Order, order_a_id) is None
        assert await session.get(SupplierOrder, int(header_a.id)) is None
        assert shipment_a is not None
        assert await session.get(Shipment, int(shipment_a.id)) is None
        assert await _graph_counts(session, order_a_id) == (0, 0, 0)
        assert await session.get(Order, order_b_id) is not None
        assert await session.get(SupplierOrder, so_b_id) is not None
        assert await session.get(SupplierOrderLine, line_b_id) is not None
        assert await session.get(Shipment, shipment_b_id) is not None
        assert await _graph_counts(session, order_b_id) == (1, 1, 1)


@pytest.mark.asyncio
async def test_admin_delete_orders_rollback_keeps_graph() -> None:
    suffix = uuid.uuid4().int % 90_000_000 + 200_000
    async with async_session_maker() as session:
        _user, order, items = await _create_order(session, suffix, item_count=1)
        order_id = int(order.id)
        header, lines, shipment = await _add_supplier_graph(
            session,
            order_id,
            seq=1,
            item_ids=[int(items[0].id)],
            placed=True,
            token=f"del-so-{suffix}",
        )
        await session.commit()
        so_id = int(header.id)
        line_id = int(lines[0].id)
        shipment_id = int(shipment.id) if shipment is not None else 0

        async def _fail_commit() -> None:
            raise RuntimeError("forced rollback")

        session.commit = _fail_commit  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="forced rollback"):
            await OrderService(session).admin_delete_orders_by_ids([order_id])

    async with async_session_maker() as session:
        assert await session.get(Order, order_id) is not None
        assert await session.get(SupplierOrder, so_id) is not None
        assert await session.get(SupplierOrderLine, line_id) is not None
        assert await session.get(Shipment, shipment_id) is not None
        assert await _graph_counts(session, order_id) == (1, 1, 1)


@pytest.mark.asyncio
async def test_admin_delete_customer_removes_order_so_lines_shipment() -> None:
    suffix = uuid.uuid4().int % 90_000_000 + 200_000
    suffix_other = suffix + 1
    async with async_session_maker() as session:
        user, order_a, items_a = await _create_order(session, suffix, item_count=2)
        order_crud = CrudOrder(session=session, model=Order)
        order_a2 = await order_crud.create_order_with_items(
            user_id=int(user.id),
            total_amount=1000,
            items_subtotal_amount=1000,
            discount_items_amount=0,
            delivery_fee_eur_snapshot=0,
            delivery_fee_amount=0,
            eur_rate_snapshot=100,
            promo_code_applied=None,
            items_payload=[_item_payload()],
            status=OrderStatus.COMPLETED.value,
            idempotency_key=f"admin-del-{suffix}-a2",
        )
        items_a2 = list(await order_crud.get_order_items(int(order_a2.id)))
        _other, order_b, items_b = await _create_order(
            session, suffix_other, item_count=1
        )
        user_id = int(user.id)
        order_a_id = int(order_a.id)
        order_a2_id = int(order_a2.id)
        order_b_id = int(order_b.id)
        await _add_supplier_graph(
            session,
            order_a_id,
            seq=1,
            item_ids=[int(items_a[0].id), int(items_a[1].id)],
            placed=True,
            token=f"del-so-{suffix}",
        )
        await _add_supplier_graph(
            session,
            order_a2_id,
            seq=1,
            item_ids=[int(items_a2[0].id)],
            placed=True,
            token=f"del-so-{suffix}-a2",
        )
        header_b, lines_b, shipment_b = await _add_supplier_graph(
            session,
            order_b_id,
            seq=1,
            item_ids=[int(items_b[0].id)],
            placed=True,
            token=f"del-so-{suffix_other}",
        )
        await session.commit()
        so_b_id = int(header_b.id)
        line_b_id = int(lines_b[0].id)
        shipment_b_id = int(shipment_b.id) if shipment_b is not None else 0
        await UserService(session).delete_admin_customer(user_id)
        assert await session.get(User, user_id) is None
        assert await session.get(Order, order_a_id) is None
        assert await session.get(Order, order_a2_id) is None
        assert await _graph_counts(session, order_a_id) == (0, 0, 0)
        assert await _graph_counts(session, order_a2_id) == (0, 0, 0)
        assert await session.get(Order, order_b_id) is not None
        assert await session.get(SupplierOrder, so_b_id) is not None
        assert await session.get(SupplierOrderLine, line_b_id) is not None
        assert await session.get(Shipment, shipment_b_id) is not None
        assert await _graph_counts(session, order_b_id) == (1, 1, 1)
