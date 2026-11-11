from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from src.main import app
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderItem,
    OrderStatus,
)
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.schemas.order import (
    AdminAvailabilityConfirmationUpdate,
    AdminAvailabilityItemDecision,
    AdminAvailabilityStockCheckUpdate,
    AdminOrderItemsUpdate,
    AdminOrderItemUpdate,
    AdminOrderStatusUpdate,
)
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_pending_availability_order,
    create_telegram_user,
    pick_active_product_id,
    pick_two_product_line_specs,
    resolve_product_line_spec,
)


async def _set_product_available_stock(session, product_id: int, stock: int) -> None:
    product = await CrudProduct(session=session, model=Product).get_by_id_with_related(
        product_id
    )
    if product is None:
        raise RuntimeError(f"товар #{product_id} не найден")
    if product.variants:
        for variant in product.variants:
            variant.inventory_quantity = stock
    else:
        product.stock = stock
    await session.commit()


async def _create_processing_order(
    session,
    user_id: int,
    suffix: int,
    *,
    availability_status: str = AvailabilityConfirmationStatus.NOT_REQUIRED,
    product_id: int | None = None,
) -> tuple[Order, list[OrderItem]]:
    if product_id is None:
        product_id = await pick_active_product_id(session)
    line_spec = await resolve_product_line_spec(session, product_id, Decimal("100"), 1)
    order_crud = CrudOrder(session=session, model=Order)
    initial_status = (
        OrderStatus.PROCESSING
        if availability_status
        in {
            AvailabilityConfirmationStatus.PENDING,
            AvailabilityConfirmationStatus.UNAVAILABLE,
        }
        else OrderStatus.CREATED
    )
    order = await order_crud.create_order_with_items(
        user_id=user_id,
        total_amount=Decimal("600"),
        items_subtotal_amount=Decimal("100"),
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=Decimal("500"),
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=None,
        items_payload=[
            {
                "product_id": line_spec[0],
                "variant_id": line_spec[1],
                "quantity": line_spec[3],
                "unit_price": line_spec[2],
            }
        ],
        idempotency_key=f"sync-{suffix}-{availability_status}",
        availability_confirmation_status=availability_status,
        status=initial_status,
    )
    items = await order_crud.get_order_items(order.id)
    return order, items


async def _count_events(session, order_id: int, event_type: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == event_type,
            )
        )
        or 0
    )


async def _admin_get_order_detail(order_id: int, admin_token: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        return await client.get(
            f"/internal/admin/orders?id={order_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )


@pytest.mark.asyncio
async def test_cancel_pending_order_sets_not_required(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, _items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        order_id = order.id
        service = OrderService(session)
        await service.update_order_status(
            order_id,
            AdminOrderStatusUpdate(status=OrderStatus.CANCELLED),
            actor=buyer,
        )

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED
        assert (
            order.availability_confirmation_status
            == AvailabilityConfirmationStatus.NOT_REQUIRED
        )
        count = await session.scalar(
            select(func.count())
            .select_from(OrderItem)
            .where(OrderItem.order_id == order_id)
        )
        assert int(count or 0) == 1
        event = await session.scalar(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == "order_cancelled",
            )
            .order_by(OrderEvent.id.desc())
        )
        assert event is not None
        payload = event.payload_json or {}
        assert (
            payload.get("availability_before") == AvailabilityConfirmationStatus.PENDING
        )
        assert (
            payload.get("availability_after")
            == AvailabilityConfirmationStatus.NOT_REQUIRED
        )


@pytest.mark.parametrize(
    "availability_status",
    [
        AvailabilityConfirmationStatus.PENDING,
        AvailabilityConfirmationStatus.UNAVAILABLE,
        AvailabilityConfirmationStatus.CONFIRMED,
        AvailabilityConfirmationStatus.NOT_REQUIRED,
    ],
)
@pytest.mark.asyncio
async def test_created_no_direct_delivery_transition(
    merge_unique_suffix: int,
    availability_status: str,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(
            session, suffix + hash(availability_status) % 1000
        )
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=availability_status,
        )
        order.payment_paid_at = utc_now_naive()
        await session.commit()
        service = OrderService(session)
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.DELIVERY),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_edit_rejects_cancelled_order(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(session, buyer.id, suffix)
        order.status = OrderStatus.CANCELLED
        await session.commit()
        service = OrderService(session)
        with pytest.raises(ValueError, match="завершённого"):
            await service.edit_order_composition(
                order.id,
                AdminOrderItemsUpdate(
                    items=[
                        AdminOrderItemUpdate(
                            id=items[0].id,
                            quantity=2,
                            unit_price=Decimal("100"),
                        )
                    ],
                ),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_edit_rejects_active_qr(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(session, buyer.id, suffix)
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=10000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        attempt.qr_expires_at = utc_now_naive() + timedelta(minutes=10)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()
        service = OrderService(session)
        with pytest.raises(ValueError, match="QR"):
            await service.edit_order_composition(
                order.id,
                AdminOrderItemsUpdate(
                    items=[
                        AdminOrderItemUpdate(
                            id=items[0].id,
                            quantity=2,
                            unit_price=Decimal("100"),
                        )
                    ],
                ),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_edit_allows_expired_qr(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(session, buyer.id, suffix)
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=10000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        attempt.qr_expires_at = utc_now_naive() - timedelta(minutes=1)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()
        service = OrderService(session)
        result, _warning = await service.edit_order_composition(
            order.id,
            AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=items[0].quantity,
                        unit_price=Decimal("150"),
                    )
                ],
            ),
            actor=buyer,
        )
        assert result.items[0].unit_price == Decimal("150")


@pytest.mark.asyncio
async def test_edit_price_only_keeps_confirmed(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.CONFIRMED,
        )
        service = OrderService(session)
        result, _warning = await service.edit_order_composition(
            order.id,
            AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=items[0].quantity,
                        unit_price=Decimal("150"),
                    )
                ],
            ),
            actor=buyer,
        )
        assert (
            result.availability_confirmation_status
            == AvailabilityConfirmationStatus.CONFIRMED
        )


@pytest.mark.asyncio
async def test_edit_rejects_insufficient_stock(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        await _set_product_available_stock(session, product_id, 1)
        order, items = await _create_processing_order(
            session, buyer.id, suffix, product_id=product_id
        )
        service = OrderService(session)
        try:
            with pytest.raises(ValueError, match="Недостаточно"):
                await service.edit_order_composition(
                    order.id,
                    AdminOrderItemsUpdate(
                        items=[
                            AdminOrderItemUpdate(
                                id=items[0].id,
                                quantity=5,
                                unit_price=Decimal("100"),
                            )
                        ],
                    ),
                    actor=buyer,
                )
        finally:
            await _set_product_available_stock(session, product_id, 100)


@pytest.mark.asyncio
async def test_cancelled_pending_not_highlighted_in_detail(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    admin_token = ""
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, _items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        order.status = OrderStatus.CANCELLED
        await session.commit()
        order_id = order.id
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
    assert 'id="order-availability-form-' not in response.text
    assert "order-summary-mock-lines" in response.text
    assert "orders-action-rail-queue" in response.text
    assert "order-action-now" not in response.text


@pytest.mark.asyncio
async def test_active_qr_shows_readonly_composition(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    admin_token = ""
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=10000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        attempt.qr_expires_at = utc_now_naive() + timedelta(minutes=15)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 2)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            f"/internal/admin/orders?id={order_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    assert "orders-composition--readonly" in response.text
    assert "QR действует до:" in response.text
    assert "orders-items-list__qty-value" in response.text
    assert "data-qty-minus" not in response.text
    assert "orders-composition-save" not in response.text


@pytest.mark.asyncio
async def test_paid_order_shows_readonly_composition(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    admin_token = ""
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order.payment_paid_at = utc_now_naive()
        await session.commit()
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 3)

    response = await _admin_get_order_detail(order_id, admin_token)
    assert response.status_code == 200
    assert "orders-composition--readonly" in response.text
    assert "оплаченный" in response.text
    assert "orders-items-list__qty-value" in response.text
    assert "orders-composition-save" not in response.text


@pytest.mark.asyncio
async def test_expired_qr_composition_editor_enabled(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    admin_token = ""
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        order_crud = CrudOrder(session=session, model=Order)
        await order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=1,
            provider="sbp",
            merchant_order_id=f"shopstore-{order.id}/1",
            x_req_id_order=f"shopstore-order-{order.id}-1",
            x_req_id_qr=f"shopstore-qrc-{order.id}-1",
            payment_amount_minor=10000,
            payment_currency="RUB",
            init_state="ready",
        )
        attempt = await order_crud.get_latest_payment_attempt(order.id)
        assert attempt is not None
        attempt.qr_expires_at = utc_now_naive() - timedelta(minutes=1)
        attempt.provider_status = "QRCDATA_CREATED"
        await session.commit()
        order_id = order.id
        _, admin_token = await create_admin_access_token(session, suffix + 4)

    response = await _admin_get_order_detail(order_id, admin_token)
    assert response.status_code == 200
    assert "orders-composition--readonly" not in response.text
    assert 'name="notify_customer" value="1" disabled' not in response.text


@pytest.mark.asyncio
async def test_post_items_rejects_readonly_cancelled_order(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    order_id = 0
    item_id = 0
    admin_token = ""
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(session, buyer.id, suffix)
        order.status = OrderStatus.CANCELLED
        await session.commit()
        order_id = order.id
        item_id = items[0].id
        _, admin_token = await create_admin_access_token(session, suffix + 5)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/internal/admin/orders/{order_id}/items",
            data={
                f"item_{item_id}_qty": "2",
                f"item_{item_id}_price": "100",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 303
    assert "error=" in response.headers.get("location", "")

    async with async_session_maker() as session:
        item = await session.get(OrderItem, item_id)
        assert item is not None
        assert item.quantity == 1


@pytest.mark.asyncio
async def test_remove_all_low_stock_sets_not_required(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        try:
            specs = await pick_two_product_line_specs(session)
        except RuntimeError:
            pytest.skip("нужно минимум 2 активных товара")
        low_spec, normal_spec = specs[0], specs[1]
        await _set_product_available_stock(session, low_spec[0], 1)
        await _set_product_available_stock(session, normal_spec[0], 100)
        order, items = await create_pending_availability_order(
            session, buyer.id, [low_spec, normal_spec]
        )
        low_item = next(i for i in items if i.product_id == low_spec[0])
        service = OrderService(session)
        result, _warning = await service.edit_order_composition(
            order.id,
            AdminOrderItemsUpdate(remove_item_ids=[low_item.id]),
            actor=buyer,
        )
        assert (
            result.availability_confirmation_status
            == AvailabilityConfirmationStatus.NOT_REQUIRED
        )
        assert result.payment_due_at is not None


@pytest.mark.asyncio
async def test_unavailable_to_not_required_after_composition_change(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        await _set_product_available_stock(session, product_id, 5000)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            product_id=product_id,
            availability_status=AvailabilityConfirmationStatus.UNAVAILABLE,
        )
        service = OrderService(session)
        result, _warning = await service.edit_order_composition(
            order.id,
            AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=2,
                        unit_price=Decimal("100"),
                    )
                ],
            ),
            actor=buyer,
        )
        assert (
            result.availability_confirmation_status
            == AvailabilityConfirmationStatus.NOT_REQUIRED
        )
        assert result.payment_due_at is not None


@pytest.mark.asyncio
async def test_duplicate_lines_exceeding_stock_rejected(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        await _set_product_available_stock(session, product_id, 1)
        order_crud = CrudOrder(session=session, model=Order)
        order = await order_crud.create_order_with_items(
            user_id=buyer.id,
            total_amount=Decimal("700"),
            items_subtotal_amount=Decimal("200"),
            discount_items_amount=Decimal("0"),
            delivery_fee_eur_snapshot=Decimal("0"),
            delivery_fee_amount=Decimal("500"),
            eur_rate_snapshot=Decimal("100"),
            promo_code_applied=None,
            items_payload=[
                {
                    "product_id": line_spec[0],
                    "variant_id": line_spec[1],
                    "quantity": 1,
                    "unit_price": line_spec[2],
                },
                {
                    "product_id": line_spec[0],
                    "variant_id": line_spec[1],
                    "quantity": 1,
                    "unit_price": line_spec[2],
                },
            ],
            idempotency_key=f"dup-lines-{suffix}",
            status=OrderStatus.PROCESSING,
            availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
        )
        items = await order_crud.get_order_items(order.id)
        service = OrderService(session)
        try:
            with pytest.raises(ValueError, match="Недостаточно"):
                await service.edit_order_composition(
                    order.id,
                    AdminOrderItemsUpdate(
                        items=[
                            AdminOrderItemUpdate(
                                id=items[0].id,
                                quantity=2,
                                unit_price=Decimal("100"),
                            ),
                            AdminOrderItemUpdate(
                                id=items[1].id,
                                quantity=1,
                                unit_price=Decimal("100"),
                            ),
                        ],
                    ),
                    actor=buyer,
                )
        finally:
            await _set_product_available_stock(session, product_id, 100)


@pytest.mark.asyncio
async def test_noop_save_does_not_change_availability(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.CONFIRMED,
        )
        before_status = order.availability_confirmation_status
        before_events = await _count_events(
            session, order.id, "availability_confirmation_requested"
        )
        service = OrderService(session)
        result, _warning = await service.edit_order_composition(
            order.id,
            AdminOrderItemsUpdate(
                items=[
                    AdminOrderItemUpdate(
                        id=items[0].id,
                        quantity=items[0].quantity,
                        unit_price=items[0].unit_price,
                    )
                ],
            ),
            actor=buyer,
        )
        after_events = await _count_events(
            session, order.id, "availability_confirmation_requested"
        )
        assert result.availability_confirmation_status == before_status
        assert after_events == before_events


@pytest.mark.asyncio
async def test_price_only_after_pending_no_duplicate_availability_event(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        await _set_product_available_stock(session, product_id, 1)
        order, items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        before = await _count_events(
            session, order.id, "availability_confirmation_requested"
        )
        service = OrderService(session)
        try:
            await service.edit_order_composition(
                order.id,
                AdminOrderItemsUpdate(
                    items=[
                        AdminOrderItemUpdate(
                            id=items[0].id,
                            quantity=items[0].quantity,
                            unit_price=Decimal("120"),
                        )
                    ],
                ),
                actor=buyer,
            )
            after = await _count_events(
                session, order.id, "availability_confirmation_requested"
            )
            assert after == before
        finally:
            await _set_product_available_stock(session, product_id, 100)


@pytest.mark.asyncio
async def test_manual_created_to_processing_forbidden(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        order, _items = await _create_processing_order(session, buyer.id, suffix)
        service = OrderService(session)
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.PROCESSING),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_manual_processing_to_created_forbidden(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 1)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, _items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        service = OrderService(session)
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.CREATED),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_delivery_forbidden_when_unpaid(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 2)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        service = OrderService(session)
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.DELIVERY),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_failed_recovery_status_follows_availability(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 3)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.NOT_REQUIRED,
        )
        order.status = OrderStatus.FAILED
        await session.commit()
        service = OrderService(session)
        result = await service.update_order_status(
            order.id,
            AdminOrderStatusUpdate(status=OrderStatus.CREATED),
            actor=buyer,
        )
        assert result.status == OrderStatus.CREATED
        order.status = OrderStatus.FAILED
        await session.commit()
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.PROCESSING),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_confirm_syncs_status_and_records_admin_author(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 4)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, _items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        order_id = order.id
        service = OrderService(session)
        await service.confirm_availability(
            order_id,
            AdminAvailabilityConfirmationUpdate(
                action="confirm", notify_customer=False
            ),
            actor=buyer,
        )

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == OrderStatus.CREATED
        event = await session.scalar(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == "status_changed",
            )
            .order_by(OrderEvent.id.desc())
        )
        assert event is not None
        payload = event.payload_json or {}
        assert payload.get("reason") == "availability_resolved"
        assert payload.get("before") == OrderStatus.PROCESSING
        assert payload.get("after") == OrderStatus.CREATED
        assert event.created_by is not None
        assert f"buyer_test_{suffix + 4}" in event.created_by


@pytest.mark.asyncio
async def test_failed_recovery_pending_to_processing(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 10)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, _items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        order.status = OrderStatus.FAILED
        await session.commit()
        service = OrderService(session)
        result = await service.update_order_status(
            order.id,
            AdminOrderStatusUpdate(status=OrderStatus.PROCESSING),
            actor=buyer,
        )
        assert result.status == OrderStatus.PROCESSING
        order.status = OrderStatus.FAILED
        await session.commit()
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.CREATED),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_failed_recovery_unavailable_to_processing(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 11)
        order, _items = await _create_processing_order(
            session,
            buyer.id,
            suffix,
            availability_status=AvailabilityConfirmationStatus.UNAVAILABLE,
        )
        order.status = OrderStatus.FAILED
        await session.commit()
        service = OrderService(session)
        result = await service.update_order_status(
            order.id,
            AdminOrderStatusUpdate(status=OrderStatus.PROCESSING),
            actor=buyer,
        )
        assert result.status == OrderStatus.PROCESSING
        order.status = OrderStatus.FAILED
        await session.commit()
        with pytest.raises(ValueError, match="переход"):
            await service.update_order_status(
                order.id,
                AdminOrderStatusUpdate(status=OrderStatus.CREATED),
                actor=buyer,
            )


@pytest.mark.asyncio
async def test_empty_stock_check_cancels_with_unavailable(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix + 12)
        product_id = await pick_active_product_id(session)
        line_spec = await resolve_product_line_spec(
            session, product_id, Decimal("100"), 1
        )
        order, items = await create_pending_availability_order(
            session, buyer.id, [line_spec]
        )
        order_id = order.id
        service = OrderService(session)
        result, _warning = await service.save_availability_stock_check(
            order_id,
            AdminAvailabilityStockCheckUpdate(
                items=[
                    AdminAvailabilityItemDecision(
                        order_item_id=items[0].id,
                        confirmed=False,
                    )
                ],
            ),
            actor=buyer,
        )

    assert result.status == OrderStatus.CANCELLED
    assert (
        result.availability_confirmation_status
        == AvailabilityConfirmationStatus.UNAVAILABLE
    )
    assert not (result.items or [])

    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED
        assert (
            order.availability_confirmation_status
            == AvailabilityConfirmationStatus.UNAVAILABLE
        )
