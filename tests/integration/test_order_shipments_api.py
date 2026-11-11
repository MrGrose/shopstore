from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.main import app
from src.models.order import (
    Order,
    OrderItem,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_engine, async_session_maker
from src.services.orders.shipments import ShipmentService
from src.services.orders.supplier_tracking import initialize_supplier_tracking
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
_FORBIDDEN_SHIPMENT_KEYS = {
    "external_id",
    "supplier_order_id",
    "unit_supplier_eur",
    "supplier_cost",
    "supplier_cost_eur",
    "supplier_shipping_eur",
    "supplier_tracking_json",
    "parcellab",
    "parcel_lab",
}


# Заказ с одной позицией для customer API.
async def _create_order(
    session: AsyncSession,
    suffix: int,
    quantity: int = 1,
    title: str = "Shipment item",
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
        supplier_cost_eur_snapshot=Decimal("50.00"),
        items_payload=[
            {
                "product_id": line_spec[0],
                "variant_id": line_spec[1],
                "quantity": quantity,
                "unit_price": line_spec[2],
                "product_title_captured": title,
                "variant_option1_captured": "Blue",
                "supplier_price_eur_captured": Decimal("50.00"),
            }
        ],
        idempotency_key=f"ship-3ec-{suffix}",
    )
    order.payment_due_at = utc_now_naive() + timedelta(hours=5)
    await session.commit()
    return order


# Вставляет placed/draft SupplierOrder.
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
        placed_by="test:3ec" if status == SupplierOrderStatus.PLACED else None,
    )
    session.add(header)
    await session.commit()
    await session.refresh(header)
    return header


# Allocation line без cost в customer JSON.
async def _add_line(
    session: AsyncSession,
    supplier_order_id: int,
    order_item_id: int,
    quantity: int,
) -> SupplierOrderLine:
    line = SupplierOrderLine(
        supplier_order_id=supplier_order_id,
        order_item_id=order_item_id,
        quantity=quantity,
        unit_supplier_eur=Decimal("50.00"),
    )
    session.add(line)
    await session.commit()
    return line


# Первая позиция заказа.
async def _first_item(session: AsyncSession, order_id: int) -> OrderItem:
    items = await CrudOrder(session=session, model=Order).get_order_items(order_id)
    assert items
    return items[0]


# GET /orders/my текущего пользователя.
async def _get_my_orders(token: str) -> list[dict[str, Any]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/orders/my?page=1&page_size=20",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    return payload


# Строка заказа из /orders/my.
def _row_for(rows: list[dict[str, Any]], order_id: int) -> dict[str, Any]:
    match = next((row for row in rows if row.get("id") == order_id), None)
    assert match is not None
    return match


# Рекурсивно собирает ключи JSON.
def _json_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value.keys())
        for child in value.values():
            keys.update(_json_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_json_keys(child))
    return keys


# Внутри shipments нет internal/TP/cost ключей.
def _assert_no_internal_shipment_fields(shipments: list[dict[str, Any]]) -> None:
    keys = _json_keys(shipments)
    leaked = keys & _FORBIDDEN_SHIPMENT_KEYS
    assert not leaked, leaked
    blob = str(shipments).lower()
    assert "parcellab" not in blob
    assert "unit_supplier_eur" not in blob
    for parcel in shipments:
        cj = str((parcel.get("supplier_tracking") or {}).get("tracking_number") or "")
        links = (parcel.get("customer_tracking") or {}).get("links") or []
        for link in links:
            url = str(link.get("url") or "")
            assert "parcellab" not in url.lower()
            assert "tp-" not in url.lower()
            if cj:
                assert cj in url


@pytest.mark.asyncio
async def test_my_orders_empty_shipments(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        token = create_access_token(order.user_id)
        order_id = order.id
    row = _row_for(await _get_my_orders(token), order_id)
    assert row["shipments"] == []
    assert "supplier_order_id" in row


@pytest.mark.asyncio
async def test_my_orders_one_shipment_seq_and_null_url(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        item = await _first_item(session, order.id)
        header = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-1-{suffix}"
        )
        await _add_line(session, header.id, item.id, 1)
        order.supplier_order_id = f"TP-3EC-1-{suffix}"
        shipment = await ShipmentService(session).create_from_placed_supplier_order(
            order.id, header.id
        )
        shipment.supplier_carrier = "DHL"
        shipment.supplier_tracking_number = f"CJ-3EC-{suffix}"
        shipment.supplier_tracking_url = "https://www.dhl.com/track?id=CJ-3EC"
        shipment.customer_carrier = "Почта России"
        shipment.customer_tracking_number = f"RP-3EC-{suffix}"
        shipment.customer_tracking_url = None
        shipment.status = ShipmentStatus.IN_TRANSIT
        await session.commit()
        token = create_access_token(order.user_id)
        order_id = order.id
        item_id = item.id
        shipment_id = shipment.id
    row = _row_for(await _get_my_orders(token), order_id)
    assert row["supplier_order_id"] == f"TP-3EC-1-{suffix}"
    assert len(row["shipments"]) == 1
    parcel = row["shipments"][0]
    assert parcel["id"] == shipment_id
    assert parcel["seq"] == 1
    assert parcel["status"] == "in_transit"
    assert parcel["status_label"] == "В пути"
    assert parcel["supplier_tracking"]["carrier"] == "DHL"
    assert parcel["supplier_tracking"]["tracking_number"] == f"CJ-3EC-{suffix}"
    assert (
        parcel["supplier_tracking"]["tracking_url"]
        == "https://www.dhl.com/track?id=CJ-3EC"
    )
    assert parcel["customer_tracking"]["carrier"] == "Почта России"
    assert parcel["customer_tracking"]["tracking_number"] == f"RP-3EC-{suffix}"
    assert parcel["customer_tracking"]["tracking_url"] is None
    cj = f"CJ-3EC-{suffix}"
    links = parcel["customer_tracking"]["links"]
    assert [row["carrier"] for row in links] == ["DHL", "Pochta"]
    assert (
        links[0]["url"]
        == "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html"
        f"?piececode={cj}"
    )
    assert links[1]["url"] == f"https://www.pochta.ru/tracking?barcode={cj}"
    assert parcel["supplier_tracking"]["links"] == []
    assert "TP-3EC" not in links[0]["url"]
    assert len(parcel["items"]) == 1
    item_row = parcel["items"][0]
    assert item_row["order_item_id"] == item_id
    assert item_row["quantity"] == 1
    assert item_row["product_title"] == "Shipment item"
    assert item_row["display_title"]
    assert "variant_option1_ru" in item_row
    assert "product_external_id" not in item_row
    assert "variant_external_id" not in item_row
    assert "unit_supplier_eur" not in item_row
    _assert_no_internal_shipment_fields(row["shipments"])


@pytest.mark.asyncio
async def test_my_orders_multiple_shipments_status_and_seq(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, quantity=2)
        item = await _first_item(session, order.id)
        first = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-A-{suffix}"
        )
        second = await _add_supplier_order(
            session, order.id, 2, SupplierOrderStatus.PLACED, f"TP-3EC-B-{suffix}"
        )
        await _add_line(session, first.id, item.id, 1)
        await _add_line(session, second.id, item.id, 1)
        service = ShipmentService(session)
        ship_a = await service.create_from_placed_supplier_order(order.id, first.id)
        ship_b = await service.create_from_placed_supplier_order(order.id, second.id)
        ship_a.status = ShipmentStatus.DELIVERED
        ship_b.status = ShipmentStatus.IN_TRANSIT
        await session.commit()
        token = create_access_token(order.user_id)
        order_id = order.id
        first_id, second_id = ship_a.id, ship_b.id
    row = _row_for(await _get_my_orders(token), order_id)
    parcels = row["shipments"]
    assert [parcel["id"] for parcel in parcels] == [first_id, second_id]
    assert [parcel["seq"] for parcel in parcels] == [1, 2]
    assert parcels[0]["status"] == "delivered"
    assert parcels[0]["status_label"] == "Доставлена"
    assert parcels[1]["status"] == "in_transit"
    assert parcels[1]["status_label"] == "В пути"
    assert row["status"] == "created"
    _assert_no_internal_shipment_fields(parcels)


@pytest.mark.asyncio
async def test_my_orders_legacy_tp_without_shipment_keeps_tracking(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        order.supplier_order_id = f"TP-3EC-LEGACY-{suffix}"
        initialize_supplier_tracking(order)
        await session.commit()
        token = create_access_token(order.user_id)
        order_id = order.id
    row = _row_for(await _get_my_orders(token), order_id)
    assert row["shipments"] == []
    assert row["supplier_order_id"] == f"TP-3EC-LEGACY-{suffix}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        tracking = await client.get(
            f"/orders/{order_id}/tracking",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert tracking.status_code == 200, tracking.text
    payload = tracking.json()
    assert "events" in payload
    assert "available" in payload
    assert "shipments" not in payload


@pytest.mark.asyncio
async def test_my_orders_idor_hides_other_user_shipments(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        owner = await _create_order(session, suffix)
        other = await _create_order(session, suffix + 1)
        item = await _first_item(session, owner.id)
        header = await _add_supplier_order(
            session, owner.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-IDOR-{suffix}"
        )
        await _add_line(session, header.id, item.id, 1)
        shipment = await ShipmentService(session).create_from_placed_supplier_order(
            owner.id, header.id
        )
        await session.commit()
        owner_token = create_access_token(owner.user_id)
        other_token = create_access_token(other.user_id)
        owner_order_id = owner.id
        other_order_id = other.id
        shipment_id = shipment.id
    owner_row = _row_for(await _get_my_orders(owner_token), owner_order_id)
    assert [parcel["id"] for parcel in owner_row["shipments"]] == [shipment_id]
    other_rows = await _get_my_orders(other_token)
    assert all(row["id"] != owner_order_id for row in other_rows)
    other_row = _row_for(other_rows, other_order_id)
    assert other_row["shipments"] == []
    assert str(shipment_id) not in str(other_rows)


@pytest.mark.asyncio
async def test_my_orders_batches_shipment_queries(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        first = await _create_order(session, suffix)
        second = await _create_order(session, suffix + 1, title="Second item")
        assert first.user_id != second.user_id
        second.user_id = first.user_id
        await session.commit()
        item_a = await _first_item(session, first.id)
        item_b = await _first_item(session, second.id)
        header_a = await _add_supplier_order(
            session, first.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-Q1-{suffix}"
        )
        header_b = await _add_supplier_order(
            session, second.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-Q2-{suffix}"
        )
        await _add_line(session, header_a.id, item_a.id, 1)
        await _add_line(session, header_b.id, item_b.id, 1)
        service = ShipmentService(session)
        await service.create_from_placed_supplier_order(first.id, header_a.id)
        await service.create_from_placed_supplier_order(second.id, header_b.id)
        await session.commit()
        token = create_access_token(first.user_id)

    captured: list[str] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    sync_engine = async_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor)
    try:
        rows = await _get_my_orders(token)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor)

    assert len(rows) >= 2
    shipment_selects = [
        sql
        for sql in captured
        if "from shipments" in sql.lower() and sql.lstrip().lower().startswith("select")
    ]
    line_selects = [
        sql
        for sql in captured
        if "from supplier_order_lines" in sql.lower()
        and sql.lstrip().lower().startswith("select")
    ]
    assert len(shipment_selects) == 1, shipment_selects
    assert (
        " in (" in shipment_selects[0].lower() or " in(" in shipment_selects[0].lower()
    )
    assert len(line_selects) == 1, line_selects


@pytest.mark.asyncio
async def test_my_orders_shipment_without_cj_has_no_links(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix)
        item = await _first_item(session, order.id)
        header = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-NOCJ-{suffix}"
        )
        await _add_line(session, header.id, item.id, 1)
        await ShipmentService(session).create_from_placed_supplier_order(
            order.id, header.id
        )
        await session.commit()
        token = create_access_token(order.user_id)
        order_id = order.id
    row = _row_for(await _get_my_orders(token), order_id)
    parcel = row["shipments"][0]
    assert parcel["supplier_tracking"]["tracking_number"] is None
    assert parcel["customer_tracking"]["links"] == []
    _assert_no_internal_shipment_fields(row["shipments"])


@pytest.mark.asyncio
async def test_my_orders_two_shipments_separate_cj_links_and_items(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, quantity=2, title="Shared item")
        item = await _first_item(session, order.id)
        first = await _add_supplier_order(
            session, order.id, 1, SupplierOrderStatus.PLACED, f"TP-3EC-A-{suffix}"
        )
        second = await _add_supplier_order(
            session, order.id, 2, SupplierOrderStatus.PLACED, f"TP-3EC-B-{suffix}"
        )
        await _add_line(session, first.id, item.id, 1)
        await _add_line(session, second.id, item.id, 1)
        service = ShipmentService(session)
        ship_a = await service.create_from_placed_supplier_order(order.id, first.id)
        ship_b = await service.create_from_placed_supplier_order(order.id, second.id)
        ship_a.supplier_tracking_number = f"CJ-A-{suffix}"
        ship_b.supplier_tracking_number = f"CJ-B-{suffix}"
        await session.commit()
        token = create_access_token(order.user_id)
        order_id = order.id
    row = _row_for(await _get_my_orders(token), order_id)
    parcels = row["shipments"]
    assert len(parcels) == 2
    cj_a = f"CJ-A-{suffix}"
    cj_b = f"CJ-B-{suffix}"
    links_a = parcels[0]["customer_tracking"]["links"]
    links_b = parcels[1]["customer_tracking"]["links"]
    assert len(links_a) + len(links_b) == 4
    assert [row["carrier"] for row in links_a] == ["DHL", "Pochta"]
    assert [row["carrier"] for row in links_b] == ["DHL", "Pochta"]
    assert cj_a in links_a[0]["url"] and cj_a in links_a[1]["url"]
    assert cj_b in links_b[0]["url"] and cj_b in links_b[1]["url"]
    assert cj_b not in links_a[0]["url"] and cj_a not in links_b[0]["url"]
    assert parcels[0]["items"][0]["quantity"] == 1
    assert parcels[1]["items"][0]["quantity"] == 1
    assert parcels[0]["supplier_tracking"]["tracking_number"] == cj_a
    assert parcels[1]["supplier_tracking"]["tracking_number"] == cj_b
    _assert_no_internal_shipment_fields(parcels)
