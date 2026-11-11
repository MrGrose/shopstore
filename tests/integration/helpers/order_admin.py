import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token
from src.core.user_roles import UserRole
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderItem,
    OrderStatus,
)
from src.models.pricing import PromoCode
from src.models.product import Product
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct
from src.repositories.promo_repo import PromoRepository
from src.schemas.order import DeliveryAddressCreate
from src.services.user_service import UserService

# Один shared admin для integration-тестов (не плодить admin_test_* в dev БД).
_TEST_SUITE_ADMIN_TELEGRAM_ID = 8_000_000_001


# Возвращает JWT существующего pytest-admin или создаёт его один раз.
async def create_admin_access_token(
    session: AsyncSession,
    suffix: int,
) -> tuple[int, str]:
    del suffix
    user = await UserService(session).upsert_telegram_user(
        telegram_id=_TEST_SUITE_ADMIN_TELEGRAM_ID,
        telegram_username="pytest_admin_suite",
        name="Pytest Admin Suite",
    )
    if user.role != UserRole.ADMIN.value:
        user.role = UserRole.ADMIN.value
        await session.commit()
        await session.refresh(user)
    return user.id, create_access_token(user.id)


# Создаёт telegram-пользователя для checkout-тестов.
async def create_telegram_user(session: AsyncSession, suffix: int) -> User:
    return await UserService(session).upsert_telegram_user(
        telegram_id=9_100_000_000 + suffix,
        telegram_username=f"buyer_test_{suffix}",
        name=f"Buyer Test {suffix}",
    )


# Возвращает id активного товара из каталога.
async def pick_active_product_id(session: AsyncSession) -> int:
    product_id = await session.scalar(
        select(Product.id).where(Product.is_active.is_(True)).limit(1)
    )
    if product_id is None:
        raise RuntimeError("нужен хотя бы один активный товар в каталоге")
    return int(product_id)


# Выставляет доступный остаток товара или его вариантов для stock-тестов.
async def set_product_available_stock(
    session: AsyncSession,
    product_id: int,
    stock: int,
) -> None:
    product = await CrudProduct(session=session, model=Product).get_by_id_with_related(
        product_id
    )
    if product is None:
        raise RuntimeError(f"товар #{product_id} не найден")
    order_crud = CrudOrder(session=session, model=Order)
    if product.variants:
        variant_ids = [int(variant.id) for variant in product.variants]
        reserved_by_variant = await order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        for variant in product.variants:
            variant.inventory_quantity = stock + reserved_by_variant.get(
                int(variant.id), 0
            )
    else:
        reserved_by_product = await order_crud.get_reserved_quantities([product_id])
        product.stock = stock + reserved_by_product.get(product_id, 0)
    await session.commit()


# Подбирает product_id и variant_id для тестового заказа.
async def resolve_product_line_spec(
    session: AsyncSession,
    product_id: int,
    price: Decimal,
    quantity: int,
) -> tuple[int, int | None, Decimal, int]:
    product = await CrudProduct(session=session, model=Product).get_by_id_with_related(
        product_id
    )
    if product is None:
        raise RuntimeError(f"товар #{product_id} не найден")
    variant_id = int(product.variants[0].id) if product.variants else None
    return product_id, variant_id, price, quantity


# Возвращает две разные позиции каталога для availability-тестов.
async def pick_two_product_line_specs(
    session: AsyncSession,
) -> list[tuple[int, int | None, Decimal, int]]:
    product_ids = list(
        (
            await session.scalars(
                select(Product.id).where(Product.is_active.is_(True)).limit(2)
            )
        ).all()
    )
    if len(product_ids) < 2:
        raise RuntimeError("нужно минимум 2 активных товара в каталоге")
    lines: list[tuple[int, int | None, Decimal, int]] = []
    for index, product_id in enumerate(product_ids):
        lines.append(
            await resolve_product_line_spec(
                session,
                int(product_id),
                Decimal("100") * (index + 1),
                1,
            )
        )
    return lines


# Создаёт заказ с позициями и событием availability_confirmation_requested.
async def create_pending_availability_order(
    session: AsyncSession,
    user_id: int,
    product_specs: list[tuple[int, int | None, Decimal, int]],
    *,
    promo_code: str | None = None,
    discount: Decimal = Decimal("0"),
) -> tuple[Order, list[OrderItem]]:
    subtotal = sum(price * qty for _, _, price, qty in product_specs)
    delivery = Decimal("500")
    total = subtotal - discount + delivery
    order_crud = CrudOrder(session=session, model=Order)
    delivery_payload = DeliveryAddressCreate(
        last_name="Test",
        first_name="User",
        street="Test St",
        house="1",
        city="Moscow",
        postal_code="101000",
        phone="+79990000000",
    ).model_dump()
    items_payload = [
        {
            "product_id": product_id,
            "variant_id": variant_id,
            "quantity": qty,
            "unit_price": price,
            "product_title_captured": f"Product {product_id}",
        }
        for product_id, variant_id, price, qty in product_specs
    ]
    order = await order_crud.create_order_with_items(
        user_id=user_id,
        total_amount=total,
        items_subtotal_amount=subtotal,
        discount_items_amount=discount,
        delivery_fee_eur_snapshot=Decimal("0"),
        delivery_fee_amount=delivery,
        eur_rate_snapshot=Decimal("100"),
        promo_code_applied=promo_code,
        items_payload=items_payload,
        idempotency_key=f"test-order-{uuid.uuid4()}",
        delivery_payload=delivery_payload,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
        status=OrderStatus.PROCESSING,
    )
    pending_items = [
        {"product_id": product_id, "variant_id": variant_id}
        for product_id, variant_id, _, _ in product_specs
    ]
    await order_crud.create_order_event(
        order_id=order.id,
        event_type="availability_confirmation_requested",
        event_message="Low stock",
        payload_json={"items": pending_items},
    )
    await order_crud.commit_order(order)
    items = await order_crud.get_order_items(order.id)
    return order, items


# Создаёт percent-промокод для тестов пересчёта.
async def create_percent_promo(
    session: AsyncSession,
    suffix: int,
    percent: Decimal = Decimal("10"),
) -> PromoCode:
    repo = PromoRepository(session)
    code = f"EDIT{suffix % 100000:05d}"
    promo = await repo.create(
        {
            "code": code,
            "discount_type": "percent",
            "usage_mode": "multi_use",
            "value": percent,
            "min_order_amount": Decimal("0"),
            "max_discount_amount": None,
            "usage_limit_total": None,
            "is_active": True,
            "active_from": None,
            "active_to": datetime.utcnow() + timedelta(days=30),
        }
    )
    return promo


# Фиксирует usage промокода для заказа.
async def attach_promo_usage(
    session: AsyncSession,
    promo: PromoCode,
    order_id: int,
    user_id: int,
) -> None:
    repo = PromoRepository(session)
    await repo.create_usage_flush(
        promo_code_id=promo.id,
        order_id=order_id,
        user_id=user_id,
    )
    await session.commit()
