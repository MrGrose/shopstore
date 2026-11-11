from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from src.main import app
from src.models.order import Order, Shipment, SupplierOrder, SupplierOrderStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_engine, async_session_maker
from src.services.orders.shipments import ShipmentService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
    set_product_available_stock,
)

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
_UNIT = Decimal("34.00")
_RATE = Decimal("100")
ORDER_DETAIL_TEMPLATE = ROOT / "src/templates/site/admin/partials/order_detail.html"
ORDERS_TABLE_TEMPLATE = ROOT / "src/templates/site/admin/partials/orders_table.html"


# Заказ без packing/place — только Order + опциональный TP/CJ.
async def _create_order(
    session: AsyncSession,
    suffix: int,
    supplier_order_id: str | None = None,
    supplier_tracking_id: str | None = None,
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
                "quantity": 1,
                "unit_price": line_spec[2],
                "product_title_captured": "Admin TP item",
                "supplier_price_eur_captured": Decimal("50.00"),
            }
        ],
        idempotency_key=f"admin-tp-{suffix}",
    )
    if supplier_order_id is not None:
        order.supplier_order_id = supplier_order_id
    if supplier_tracking_id is not None:
        order.supplier_tracking_id = supplier_tracking_id
    await session.commit()
    await session.refresh(order)
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
        placed_by="test:admin-tp" if status == SupplierOrderStatus.PLACED else None,
    )
    session.add(header)
    await session.commit()
    await session.refresh(header)
    return header


# Ставит CJ на Shipment placed SO.
async def _set_shipment_cj(
    session: AsyncSession, order_id: int, supplier_order_id: int, cj: str | None
) -> Shipment:
    row = await ShipmentService(session).create_from_placed_supplier_order(
        order_id, supplier_order_id
    )
    row.supplier_tracking_number = cj
    await session.commit()
    await session.refresh(row)
    return row


# HTML админки под admin JWT.
async def _admin_get(path: str, token: str) -> str:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(path, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 200, response.text[:500]
        return response.text


# Ячейка TP строки списка для заказа.
def _table_tp_cell(html: str, order_id: int) -> str:
    marker = f'aria-label="Выбрать заказ #{order_id}"'
    start = html.index(marker)
    tr_start = html.index('class="orders-table__tr', start)
    tr_end = html.index("</div>", html.index(">", tr_start))
    return html[tr_start:tr_end]


# Блок «Поставщик» карточки, без rail.
def _supplier_block(html: str) -> str:
    start = html.index('order-summary-field-label">Поставщик')
    end = html.index("orders-detail-main", start)
    return html[start:end]


def test_admin_templates_use_so_context_not_order_legacy_fields() -> None:
    table = ORDERS_TABLE_TEMPLATE.read_text(encoding="utf-8")
    assert "order_supplier_tps" in table
    assert "order.supplier_order_id or" not in table
    detail = ORDER_DETAIL_TEMPLATE.read_text(encoding="utf-8")
    supplier = _supplier_block(detail)
    assert "admin_supplier_parcels" in supplier
    assert "order.supplier_order_id" not in supplier
    assert "order.supplier_tracking_id" not in supplier


@pytest.mark.asyncio
async def test_admin_orders_table_one_placed_tp(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, "TP-LEGACY")
        order_id = int(order.id)
        await _add_supplier_order(
            session, order_id, 1, SupplierOrderStatus.PLACED, f"TP-ONE-{suffix}"
        )
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders/table?q={order_id}", token)
    cell = _table_tp_cell(html, order_id)
    assert f"TP-ONE-{suffix}" in cell
    assert "TP-LEGACY" not in cell
    assert "+ ещё" not in cell


@pytest.mark.asyncio
async def test_admin_orders_table_four_placed_compact(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    tps = [
        f"TP-{suffix}-A",
        f"TP-{suffix}-B",
        f"TP-{suffix}-C",
        f"TP-{suffix}-D",
    ]
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, tps[0], "CJ-LEGACY")
        order_id = int(order.id)
        for seq, tp in enumerate(tps, start=1):
            await _add_supplier_order(
                session, order_id, seq, SupplierOrderStatus.PLACED, tp
            )
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders/table?q={order_id}", token)
    cell = _table_tp_cell(html, order_id)
    assert tps[0] in cell
    assert "+ ещё 3" in cell
    assert tps[1] in cell
    assert tps[2] in cell
    assert tps[3] in cell
    assert cell.count(tps[1]) == 1
    visible = cell.split("title=")[0]
    assert tps[1] not in visible
    assert tps[2] not in visible
    assert tps[3] not in visible


@pytest.mark.asyncio
async def test_admin_orders_table_legacy_without_so(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, f"TP-LEGACY-{suffix}")
        order_id = int(order.id)
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders/table?q={order_id}", token)
    cell = _table_tp_cell(html, order_id)
    assert f"TP-LEGACY-{suffix}" in cell
    assert "+ ещё" not in cell


@pytest.mark.asyncio
async def test_admin_orders_table_skips_draft_and_cancelled(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, "TP-LEGACY")
        order_id = int(order.id)
        await _add_supplier_order(
            session, order_id, 1, SupplierOrderStatus.PLACED, f"TP-OK-{suffix}"
        )
        await _add_supplier_order(session, order_id, 2, SupplierOrderStatus.DRAFT, None)
        await _add_supplier_order(
            session, order_id, 3, SupplierOrderStatus.CANCELLED, f"TP-SKIP-{suffix}"
        )
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders/table?q={order_id}", token)
    cell = _table_tp_cell(html, order_id)
    assert f"TP-OK-{suffix}" in cell
    assert f"TP-SKIP-{suffix}" not in cell
    assert "TP-LEGACY" not in cell
    assert "+ ещё" not in cell


@pytest.mark.asyncio
async def test_admin_orders_table_batches_supplier_order_query(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        orders = []
        for offset in range(3):
            order = await _create_order(session, suffix + offset)
            orders.append(order)
            for seq in (1, 2):
                await _add_supplier_order(
                    session,
                    int(order.id),
                    seq,
                    SupplierOrderStatus.PLACED,
                    f"TP-N1-{suffix}-{offset}-{seq}",
                )
        _, token = await create_admin_access_token(session, suffix + 9)

    captured: list[str] = []

    def _before_cursor(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    sync_engine = async_engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor)
    try:
        await _admin_get("/internal/admin/orders/table", token)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor)

    so_selects = [
        sql
        for sql in captured
        if "from supplier_orders" in sql.lower()
        and sql.lstrip().lower().startswith("select")
    ]
    assert len(so_selects) == 1, so_selects
    assert " in (" in so_selects[0].lower() or " in(" in so_selects[0].lower()


@pytest.mark.asyncio
async def test_admin_order_detail_one_parcel(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, "TP-LEGACY", "CJ-LEGACY")
        order_id = int(order.id)
        header = await _add_supplier_order(
            session, order_id, 1, SupplierOrderStatus.PLACED, f"TP-ONE-{suffix}"
        )
        await _set_shipment_cj(session, order_id, int(header.id), f"CJ-ONE-{suffix}")
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders?id={order_id}", token)
    block = _supplier_block(html)
    assert "Посылка 1" in block
    assert f"TP-ONE-{suffix}" in block
    assert f"CJ-ONE-{suffix}" in block
    assert "TP-LEGACY" not in block
    assert "CJ-LEGACY" not in block
    assert "Посылка 2" not in block


@pytest.mark.asyncio
async def test_admin_order_detail_four_parcels_keep_cj(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    pairs = [
        (f"TP-{suffix}-A", f"CJ-{suffix}-A"),
        (f"TP-{suffix}-B", f"CJ-{suffix}-B"),
        (f"TP-{suffix}-C", f"CJ-{suffix}-C"),
        (f"TP-{suffix}-D", f"CJ-{suffix}-D"),
    ]
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, pairs[0][0], pairs[0][1])
        order_id = int(order.id)
        for seq, (tp, cj) in enumerate(pairs, start=1):
            header = await _add_supplier_order(
                session, order_id, seq, SupplierOrderStatus.PLACED, tp
            )
            await _set_shipment_cj(session, order_id, int(header.id), cj)
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders?id={order_id}", token)
    block = _supplier_block(html)
    positions = []
    for seq, (tp, cj) in enumerate(pairs, start=1):
        assert f"Посылка {seq}" in block
        assert tp in block
        assert cj in block
        positions.append((block.index(tp), block.index(cj)))
    for index, (tp_pos, cj_pos) in enumerate(positions):
        assert tp_pos < cj_pos
        if index + 1 < len(positions):
            next_tp_pos, _ = positions[index + 1]
            assert cj_pos < next_tp_pos


@pytest.mark.asyncio
async def test_admin_order_detail_missing_cj_message(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(session, suffix, f"TP-{suffix}", "CJ-LEGACY")
        order_id = int(order.id)
        header = await _add_supplier_order(
            session, order_id, 1, SupplierOrderStatus.PLACED, f"TP-{suffix}"
        )
        await _set_shipment_cj(session, order_id, int(header.id), None)
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders?id={order_id}", token)
    block = _supplier_block(html)
    assert f"TP-{suffix}" in block
    assert "Трек-номер ещё не получен" in block
    assert "CJ-LEGACY" not in block


@pytest.mark.asyncio
async def test_admin_order_detail_legacy_without_so_shipment(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        order = await _create_order(
            session, suffix, f"TP-LEGACY-{suffix}", f"CJ-LEGACY-{suffix}"
        )
        order_id = int(order.id)
        _, token = await create_admin_access_token(session, suffix + 9)
    html = await _admin_get(f"/internal/admin/orders?id={order_id}", token)
    block = _supplier_block(html)
    assert "Посылка 1" in block
    assert f"TP-LEGACY-{suffix}" in block
    assert f"CJ-LEGACY-{suffix}" in block
