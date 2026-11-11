import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from src.models.order import AvailabilityConfirmationStatus, Order, OrderStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    pick_active_product_id,
    resolve_product_line_spec,
)

pytestmark = pytest.mark.integration

MIGRATION_FILENAME = "z6a7b8c9d0e1_sync_order_status_with_availability.py"


def _load_migration_module(filename: str) -> object:
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location(
        "status_sync_migration", migration_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _insert_order(
    session,
    user_id: int,
    suffix: int,
    *,
    status: str,
    availability: str,
) -> Order:
    product_id = await pick_active_product_id(session)
    product_id, variant_id, unit_price, quantity = await resolve_product_line_spec(
        session, product_id, Decimal("100"), 1
    )
    order_crud = CrudOrder(session=session, model=Order)
    order = await order_crud.create_order_with_items(
        user_id=user_id,
        total_amount=Decimal("600"),
        items_subtotal_amount=unit_price * quantity,
        discount_items_amount=Decimal("0"),
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=Decimal("500"),
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=None,
        items_payload=[
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        ],
        idempotency_key=f"mig-sync-{suffix}-{status}-{availability}",
        availability_confirmation_status=availability,
        status=status,
    )
    if str(order.status) != status:
        order.status = status
        await order_crud.commit_order(order)
    return order


@pytest.mark.asyncio
async def test_migration_syncs_only_processing_confirmed_or_not_required(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix
    expectations: list[tuple[str, str, str]] = [
        (
            OrderStatus.PROCESSING,
            AvailabilityConfirmationStatus.NOT_REQUIRED,
            OrderStatus.CREATED,
        ),
        (
            OrderStatus.PROCESSING,
            AvailabilityConfirmationStatus.CONFIRMED,
            OrderStatus.CREATED,
        ),
        (
            OrderStatus.PROCESSING,
            AvailabilityConfirmationStatus.PENDING,
            OrderStatus.PROCESSING,
        ),
        (
            OrderStatus.PROCESSING,
            AvailabilityConfirmationStatus.UNAVAILABLE,
            OrderStatus.PROCESSING,
        ),
        (
            OrderStatus.CANCELLED,
            AvailabilityConfirmationStatus.NOT_REQUIRED,
            OrderStatus.CANCELLED,
        ),
        (
            OrderStatus.DELIVERY,
            AvailabilityConfirmationStatus.CONFIRMED,
            OrderStatus.DELIVERY,
        ),
        (
            OrderStatus.COMPLETED,
            AvailabilityConfirmationStatus.NOT_REQUIRED,
            OrderStatus.COMPLETED,
        ),
        (
            OrderStatus.FAILED,
            AvailabilityConfirmationStatus.PENDING,
            OrderStatus.FAILED,
        ),
    ]
    order_ids: list[int] = []
    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        for index, (status, availability, _expected) in enumerate(expectations):
            order = await _insert_order(
                session,
                buyer.id,
                suffix * 100 + index,
                status=status,
                availability=availability,
            )
            order_ids.append(order.id)
        migration = _load_migration_module(MIGRATION_FILENAME)
        await session.execute(migration.build_status_sync_statement())
        await session.commit()

    async with async_session_maker() as session:
        for order_id, (_status, _availability, expected) in zip(
            order_ids, expectations, strict=True
        ):
            row = await session.get(Order, order_id)
            assert row is not None
            assert row.status == expected
