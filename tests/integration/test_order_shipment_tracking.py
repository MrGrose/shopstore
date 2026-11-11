from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jobs.supplier_tracking_scheduler import tracking_due_filters
from src.models.order import (
    Order,
    OrderStatus,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderStatus,
)
from src.repositories.session import async_session_maker
from src.services.orders.pochta_tracking import PochtaTrackingFetchError
from src.services.orders.shipments import ShipmentService
from src.services.orders.supplier_tracking import SupplierTrackingService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.test_order_shipments import _add_supplier_order, _create_order

pytestmark = pytest.mark.integration


# True если scheduler считает заказ due.
async def _order_is_due(session: AsyncSession, order_id: int, now: datetime) -> bool:
    found = await session.scalar(
        select(Order.id).where(Order.id == order_id, *tracking_due_filters(now))
    )
    return found is not None


# ParcelLab payload с одним header/body для TP → CJ.
def _parcellab_payload(tp_id: str, cj: str, status: str = "InTransit") -> dict:
    return {
        "header": [
            {
                "id": tp_id,
                "tracking_number": cj,
                "courier": {
                    "prettyname": "DHL",
                    "trackingurl": f"https://example.test/{cj}",
                    "destination_courier": {"prettyname": "Russian Post"},
                },
                "last_delivery_status": {"code": status},
            }
        ],
        "body": {
            tp_id: [
                {
                    "shown": True,
                    "id": f"{tp_id}-evt",
                    "timestamp": "2026-08-01T10:00:00Z",
                    "status": status,
                    "status_details": status,
                }
            ]
        },
    }


# Нормализованный DHL snapshot для mock fetch_dhl_tracking.
def _dhl_normalized(cj: str, stage: str) -> dict:
    return {
        "tracking_number": cj,
        "carrier_label": "DHL",
        "carrier_source": "dhl",
        "current_stage": stage,
        "events": [
            {
                "key": f"dhl|{cj}|{stage}",
                "at": "2026-08-01T11:00:00Z",
                "stage": stage,
                "title": stage,
                "source": "dhl",
            }
        ],
    }


# Нормализованный snapshot Почты для mock fetch_pochta_tracking.
def _pochta_normalized(cj: str, stage: str) -> dict:
    return {
        "tracking_number": cj,
        "carrier_label": "Почта России",
        "carrier_source": "pochta",
        "carrier_url": f"https://www.pochta.ru/tracking?barcode={cj}",
        "current_stage": stage,
        "common_status": stage,
        "events": [],
    }


# Два placed SO и Shipment; новый flow без Order.supplier_*.
async def _two_placed(
    session: AsyncSession, suffix: int
) -> tuple[Order, SupplierOrder, SupplierOrder, Shipment, Shipment]:
    order = await _create_order(session, suffix)
    tp1 = f"TP-3EB-A-{suffix}"
    tp2 = f"TP-3EB-B-{suffix}"
    so1 = await _add_supplier_order(
        session, order.id, 1, SupplierOrderStatus.PLACED, tp1
    )
    so2 = await _add_supplier_order(
        session, order.id, 2, SupplierOrderStatus.PLACED, tp2
    )
    order.status = OrderStatus.ASSEMBLING
    await session.commit()
    svc = ShipmentService(session)
    ship1 = await svc.create_from_placed_supplier_order(order.id, so1.id)
    ship2 = await svc.create_from_placed_supplier_order(order.id, so2.id)
    return order, so1, so2, ship1, ship2


@pytest.mark.asyncio
async def test_sync_two_so_writes_separate_shipments_not_order_blob(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix
    pl_calls: list[str] = []
    dhl_calls: list[str] = []
    pochta_calls: list[str] = []

    async def fake_pl(supplier_order_id: str) -> dict:
        pl_calls.append(supplier_order_id)
        mapping = {
            f"TP-3EB-A-{suffix}": ("CJ-1", "InTransit"),
            f"TP-3EB-B-{suffix}": ("CJ-2", "InTransit"),
        }
        cj, status = mapping[supplier_order_id]
        return _parcellab_payload(supplier_order_id, cj, status)

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        dhl_calls.append(piececode)
        stage = "in_transit" if piececode == "CJ-1" else "last_mile"
        return _dhl_normalized(piececode, stage)

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        pochta_calls.append(barcode)
        stage = "in_transit" if barcode == "CJ-1" else "last_mile"
        return _pochta_normalized(barcode, stage)

    from src.services.orders import supplier_tracking as st_mod

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order, so1, so2, ship1, ship2 = await _two_placed(session, suffix)
        result = await SupplierTrackingService(session).sync_order(order.id)
        assert result["error"] is None
        await session.refresh(ship1)
        await session.refresh(ship2)
        await session.refresh(order)
        assert ship1.supplier_tracking_number == "CJ-1"
        assert ship2.supplier_tracking_number == "CJ-2"
        assert ship1.customer_tracking_number == "CJ-1"
        assert ship2.customer_tracking_number == "CJ-2"
        assert ship1.customer_carrier == "Почта России"
        assert ship2.customer_carrier == "Почта России"
        assert ship1.status == ShipmentStatus.IN_TRANSIT
        assert ship2.status == ShipmentStatus.IN_TRANSIT
        assert order.supplier_tracking_id is None
        assert order.supplier_order_id is None
        assert order.supplier_tracking_json is None
        assert order.status == OrderStatus.DELIVERY
        assert set(pl_calls) == {f"TP-3EB-A-{suffix}", f"TP-3EB-B-{suffix}"}
        assert set(dhl_calls) == {"CJ-1", "CJ-2"}
        assert set(pochta_calls) == {"CJ-1", "CJ-2"}


@pytest.mark.asyncio
async def test_mismatch_tp_does_not_update_order_legacy_fields(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix

    async def fake_pl(supplier_order_id: str) -> dict:
        return _parcellab_payload(supplier_order_id, "CJ-NEW", "InTransit")

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        return _dhl_normalized(piececode, "in_transit")

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        return _pochta_normalized(barcode, "in_transit")

    from src.services.orders import supplier_tracking as st_mod

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        order.supplier_order_id = f"TP-OLD-{suffix}"
        order.supplier_tracking_id = "CJ-OLD"
        order.supplier_tracking_json = {"current_stage": "preparing"}
        await session.commit()
        so = await _add_supplier_order(
            session,
            order.id,
            1,
            SupplierOrderStatus.PLACED,
            f"TP-NEW-{suffix}",
        )
        ship = await ShipmentService(session).create_from_placed_supplier_order(
            order.id, so.id
        )
        await SupplierTrackingService(session).sync_order(order.id)
        await session.refresh(order)
        await session.refresh(ship)
        assert ship.supplier_tracking_number == "CJ-NEW"
        assert order.supplier_tracking_id == "CJ-OLD"
        assert order.supplier_order_id == f"TP-OLD-{suffix}"
        assert order.supplier_tracking_json == {"current_stage": "preparing"}


@pytest.mark.asyncio
async def test_pochta_failure_keeps_dhl_on_shipment(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix

    async def fake_pl(supplier_order_id: str) -> dict:
        return _parcellab_payload(supplier_order_id, "CJ-1", "InTransit")

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        return _dhl_normalized(piececode, "in_transit")

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        raise PochtaTrackingFetchError("provider_error", "Почта недоступна")

    from src.services.orders import supplier_tracking as st_mod

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order, so1, _so2, ship1, _ship2 = await _two_placed(session, suffix)
        await SupplierTrackingService(session).sync_order(order.id)
        await session.refresh(ship1)
        await session.refresh(order)
        assert ship1.supplier_tracking_number == "CJ-1"
        assert ship1.customer_tracking_number == "CJ-1"
        assert ship1.customer_carrier is None
        assert order.supplier_tracking_id is None
        assert order.supplier_tracking_json is None


@pytest.mark.asyncio
async def test_unknown_stage_does_not_overwrite_and_delivered_is_sticky(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix
    stages = {"first": "Delivered", "second": "Exception"}

    async def fake_pl(supplier_order_id: str) -> dict:
        status = stages["first"] if not hasattr(fake_pl, "once") else stages["second"]
        fake_pl.once = True  # type: ignore[attr-defined]
        return _parcellab_payload(supplier_order_id, "CJ-1", status)

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        return _dhl_normalized(piececode, "delivered")

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        return _pochta_normalized(barcode, "delivered")

    from src.services.orders import supplier_tracking as st_mod

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        tp = f"TP-3EB-D-{suffix}"
        so = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, tp
        )
        order.supplier_order_id = tp
        await session.commit()
        ship = await ShipmentService(session).create_from_placed_supplier_order(
            order.id, so.id
        )
        await SupplierTrackingService(session).sync_order(order.id)
        await session.refresh(ship)
        assert ship.status == ShipmentStatus.DELIVERED
        delivered_at = ship.delivered_at
        stages["first"] = "Exception"
        await SupplierTrackingService(session).sync_order(order.id)
        await session.refresh(ship)
        assert ship.status == ShipmentStatus.DELIVERED
        assert ship.delivered_at == delivered_at


@pytest.mark.asyncio
async def test_due_when_one_delivered_and_not_when_all_delivered(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, _so1, _so2, ship1, ship2 = await _two_placed(session, suffix)
        now = utc_now_naive()
        order.status = "processing"
        order.supplier_tracking_next_check_at = None
        ship1.status = ShipmentStatus.DELIVERED
        ship2.status = ShipmentStatus.IN_TRANSIT
        await session.commit()
        assert await _order_is_due(session, order.id, now)
        ship2.status = ShipmentStatus.DELIVERED
        order.supplier_tracking_next_check_at = None
        await session.commit()
        assert not await _order_is_due(session, order.id, now)


@pytest.mark.asyncio
async def test_future_next_check_skips_undelivered_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order, _so1, _so2, ship1, _ship2 = await _two_placed(session, suffix)
        now = utc_now_naive()
        order.status = "processing"
        order.supplier_tracking_next_check_at = now + timedelta(hours=12)
        ship1.status = ShipmentStatus.IN_TRANSIT
        await session.commit()
        assert not await _order_is_due(session, order.id, now)
        order.supplier_tracking_next_check_at = now - timedelta(minutes=1)
        await session.commit()
        assert await _order_is_due(session, order.id, now)


@pytest.mark.asyncio
async def test_customer_list_orders_includes_synced_shipments(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix

    async def fake_pl(supplier_order_id: str) -> dict:
        mapping = {
            f"TP-3EB-A-{suffix}": "CJ-1",
            f"TP-3EB-B-{suffix}": "CJ-2",
        }
        return _parcellab_payload(
            supplier_order_id, mapping[supplier_order_id], "InTransit"
        )

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        return _dhl_normalized(piececode, "in_transit")

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        return _pochta_normalized(barcode, "in_transit")

    from src.services.orders import supplier_tracking as st_mod
    from src.services.orders.order_service import OrderService

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order, _so1, _so2, _ship1, _ship2 = await _two_placed(session, suffix)
        user_id = int(order.user_id)
        await SupplierTrackingService(session).sync_order(order.id)
        listed = await OrderService(session).list_orders(
            user_id=user_id, page=1, page_size=20
        )
        found = next(item for item in listed if int(item.id) == int(order.id))
        assert len(found.shipments) == 2
        by_seq = {row.seq: row for row in found.shipments}
        assert by_seq[1].supplier_tracking.tracking_number == "CJ-1"
        assert by_seq[2].supplier_tracking.tracking_number == "CJ-2"
        assert found.supplier_order_id is None
        assert found.supplier_tracking_id is None


@pytest.mark.asyncio
async def test_legacy_sync_without_so_still_writes_order_blob(
    merge_unique_suffix: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = merge_unique_suffix
    tp_id = f"TP-LEGACY-{suffix}"

    async def fake_pl(supplier_order_id: str) -> dict:
        assert supplier_order_id == tp_id
        return _parcellab_payload(supplier_order_id, "CJ-LEGACY", "InTransit")

    async def fake_dhl(
        piececode: str, language: str = "ru", proxy_url: str | None = None
    ):
        return _dhl_normalized(piececode, "in_transit")

    async def fake_pochta(barcode: str, proxy_url: str | None = None) -> dict:
        return _pochta_normalized(barcode, "in_transit")

    from src.services.orders import supplier_tracking as st_mod

    monkeypatch.setattr(st_mod, "fetch_supplier_tracking", fake_pl)
    monkeypatch.setattr(st_mod, "fetch_dhl_tracking", fake_dhl)
    monkeypatch.setattr(st_mod, "fetch_pochta_tracking", fake_pochta)

    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        order.status = OrderStatus.ASSEMBLING
        order.supplier_order_id = tp_id
        await session.commit()
        await SupplierTrackingService(session).sync_order(order.id)
        await session.refresh(order)
        assert order.supplier_order_id == tp_id
        assert order.supplier_tracking_id == "CJ-LEGACY"
        assert order.supplier_tracking_json is not None
        assert order.status == OrderStatus.DELIVERY
