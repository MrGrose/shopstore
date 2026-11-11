from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import (
    Order,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.orders.shipments import ShipmentError, ShipmentService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
    set_product_available_stock,
)

pytestmark = pytest.mark.integration

_UNIT = Decimal("34.00")
_RATE = Decimal("100")


# Заказ без packing/place — только Order + опциональный TP.
async def _create_order(
    session: AsyncSession, suffix: int, supplier_eur: Decimal = Decimal("50.00")
) -> Order:
    buyer = await create_telegram_user(session, suffix)
    product_id = await pick_active_product_id(session)
    await set_product_available_stock(session, product_id, 100)
    line_spec = await resolve_product_line_spec(session, product_id, Decimal("1000"), 1)
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
        supplier_cost_eur_snapshot=supplier_eur,
        items_payload=[
            {
                "product_id": line_spec[0],
                "variant_id": line_spec[1],
                "quantity": 1,
                "unit_price": line_spec[2],
                "product_title_captured": "Shipment item",
                "supplier_price_eur_captured": supplier_eur,
            }
        ],
        idempotency_key=f"ship-3ea-{suffix}",
    )
    await session.commit()
    return order


# Вставляет SupplierOrder с заданным status/seq/TP.
async def _add_supplier_order(
    session: AsyncSession,
    order_id: int,
    seq: int,
    status: str,
    external_id: str | None,
) -> SupplierOrder:
    header = SupplierOrder(
        order_id=order_id,
        seq=seq,
        external_id=external_id,
        status=status,
        goods_eur=Decimal("50.00"),
        supplier_shipping_eur=Decimal("29.99"),
        placed_at=utc_now_naive() if status == SupplierOrderStatus.PLACED else None,
        placed_by="test:3ea" if status == SupplierOrderStatus.PLACED else None,
    )
    session.add(header)
    await session.commit()
    await session.refresh(header)
    return header


# Считает Shipment по заказу.
async def _shipment_count(session: AsyncSession, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Shipment)
            .where(Shipment.order_id == order_id)
        )
        or 0
    )


@pytest.mark.asyncio
async def test_create_from_placed_so_only(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        placed = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EA-{suffix}"
        )
        draft = await _add_supplier_order(
            session, order.id, 2, SupplierOrderStatus.DRAFT, None
        )
        cancelled = await _add_supplier_order(
            session, order.id, 3, SupplierOrderStatus.CANCELLED, f"TP-3EA-C-{suffix}"
        )
        service = ShipmentService(session)
        created = await service.create_from_placed_supplier_order(order.id, placed.id)
        assert created.order_id == order.id
        assert created.supplier_order_id == placed.id
        assert created.status == ShipmentStatus.PREPARING
        assert created.supplier_tracking_url is None
        with pytest.raises(ShipmentError):
            await service.create_from_placed_supplier_order(order.id, draft.id)
        with pytest.raises(ShipmentError):
            await service.create_from_placed_supplier_order(order.id, cancelled.id)
        again = await service.create_from_placed_supplier_order(order.id, placed.id)
        assert again.id == created.id
        assert await _shipment_count(session, order.id) == 1


@pytest.mark.asyncio
async def test_rejects_foreign_supplier_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order_a = await _create_order(session, suffix)
        order_b = await _create_order(session, suffix + 1)
        header = await _add_supplier_order(
            session, order_b.id, 1, SupplierOrderStatus.PLACED, f"TP-3EA-F-{suffix}"
        )
        service = ShipmentService(session)
        with pytest.raises(ShipmentError, match="другому заказу"):
            await service.create_from_placed_supplier_order(order_a.id, header.id)
        assert await _shipment_count(session, order_a.id) == 0
        assert await _shipment_count(session, order_b.id) == 0


@pytest.mark.asyncio
async def test_two_placed_one_cancelled_yields_two_shipments(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        so1 = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EA-A-{suffix}"
        )
        so2 = await _add_supplier_order(
            session, order.id, 2, SupplierOrderStatus.PLACED, f"TP-3EA-B-{suffix}"
        )
        await _add_supplier_order(
            session, order.id, 3, SupplierOrderStatus.CANCELLED, f"TP-3EA-X-{suffix}"
        )
        service = ShipmentService(session)
        stats = await service.backfill_legacy(order_id=order.id)
        assert stats.created == 2
        assert stats.skipped_existing == 0
        views = await service.list_for_order(order.id)
        assert {view.supplier_order_id for view in views} == {so1.id, so2.id}
        assert await _shipment_count(session, order.id) == 2


@pytest.mark.asyncio
async def test_backfill_legacy_cases_and_idempotent(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        matched = await _create_order(session, suffix)
        matched.supplier_order_id = f"TP-3EA-M-{suffix}"
        matched.supplier_tracking_id = f"CJ-3EA-{suffix}"
        matched.supplier_tracking_json = {"current_stage": "in_transit"}
        await session.commit()
        so = await _add_supplier_order(
            session,
            matched.id,
            1,
            SupplierOrderStatus.PLACED,
            f"TP-3EA-M-{suffix}",
        )
        missing = await _create_order(session, suffix + 1)
        missing.supplier_order_id = f"TP-3EA-MISS-{suffix}"
        await session.commit()
        draft_only = await _create_order(session, suffix + 2)
        await _add_supplier_order(
            session, draft_only.id, 1, SupplierOrderStatus.DRAFT, None
        )
        other = await _create_order(session, suffix + 3)
        await _add_supplier_order(
            session,
            other.id,
            1,
            SupplierOrderStatus.PLACED,
            f"TP-3EA-O-{suffix}",
        )
        service = ShipmentService(session)
        first = await service.backfill_legacy(order_id=matched.id)
        assert first.created == 1
        assert first.skipped_missing_so == 0
        views = await service.list_for_order(matched.id)
        assert len(views) == 1
        assert views[0].supplier_order_id == so.id
        assert views[0].supplier_tracking_number == f"CJ-3EA-{suffix}"
        assert views[0].supplier_tracking_url is None
        assert views[0].status == ShipmentStatus.PREPARING
        await session.refresh(matched)
        assert matched.supplier_order_id == f"TP-3EA-M-{suffix}"
        assert matched.supplier_tracking_id == f"CJ-3EA-{suffix}"
        assert matched.supplier_tracking_json == {"current_stage": "in_transit"}
        second = await service.backfill_legacy(order_id=matched.id)
        assert second.created == 0
        assert second.skipped_existing == 1
        assert await _shipment_count(session, matched.id) == 1
        miss_stats = await service.backfill_legacy(order_id=missing.id)
        assert miss_stats.created == 0
        assert miss_stats.skipped_missing_so == 1
        assert await _shipment_count(session, missing.id) == 0
        draft_stats = await service.backfill_legacy(order_id=draft_only.id)
        assert draft_stats.created == 0
        assert await _shipment_count(session, draft_only.id) == 0
        assert await _shipment_count(session, other.id) == 0
        await service.backfill_legacy(order_id=other.id)
        assert await _shipment_count(session, other.id) == 1
        assert await _shipment_count(session, matched.id) == 1
