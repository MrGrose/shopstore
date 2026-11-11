from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.order_limits import max_supplier_goods_eur
from src.models.order import Order
from src.models.product import Product
from src.repositories.product_repo import CrudProduct
from src.repositories.session import async_session_maker
from src.schemas.money import ceil_rub
from src.schemas.order import DeliveryAddressCreate
from src.services.cart_service import CartService
from src.services.orders.order_service import OrderService
from src.services.pricing.calculator import calculate_delivery_rub
from src.services.pricing.service import PricingService
from src.services.product_service import ProductService
from tests.integration.helpers.order_admin import (
    create_telegram_user,
    set_product_available_stock,
)

pytestmark = pytest.mark.integration

_DELIVERY = DeliveryAddressCreate(
    last_name="Estimate",
    first_name="Test",
    street="Test St",
    house="1",
    city="Moscow",
    postal_code="101000",
    phone="+79990000034",
).model_dump()


# Возвращает активный товар в наличии для мутации закупочной цены.
async def _pick_in_stock_product(session: AsyncSession) -> Product:
    product = await session.scalar(
        select(Product)
        .where(Product.is_active.is_(True), Product.catalog_in_stock.is_(True))
        .order_by(Product.id)
        .limit(1)
    )
    if product is None:
        pytest.skip("нужен активный товар в наличии")
    return product


# Активный in-stock товар, который get_product_for_storefront() отдаёт до мутации цены.
async def _pick_storefront_eligible_in_stock_product(session: AsyncSession) -> Product:
    product_service = ProductService(session)
    candidate_ids = (
        await session.scalars(
            select(Product.id)
            .where(Product.is_active.is_(True), Product.catalog_in_stock.is_(True))
            .order_by(Product.id)
            .limit(50)
        )
    ).all()
    if not candidate_ids:
        pytest.skip("нужен активный товар в наличии")

    for product_id in candidate_ids:
        visible = await product_service.get_product_for_storefront(int(product_id))
        if visible is not None:
            return visible

    pytest.skip("нет in-stock товара, который get_product_for_storefront() уже отдаёт")


# Проверяет, проходит ли товар SQL-фильтр витрины с капом TP.
async def _listed_on_storefront(session: AsyncSession, product_id: int) -> bool:
    repo = CrudProduct(session=session, model=Product)
    filters = repo._catalog_base_filters(exclude_over_supplier_unit_cap=True)
    found = await session.scalar(
        select(Product.id).where(Product.id == product_id, *filters)
    )
    return found is not None


# Выставляет закупочную цену товара и коммитит.
async def _set_supplier_price(
    session: AsyncSession, product_id: int, value: Decimal
) -> None:
    product = await session.get(Product, product_id)
    assert product is not None
    product.supplier_price_eur = value
    await session.commit()


# Выставляет клиентскую базу доставки в настройках.
async def _set_delivery_fee(session: AsyncSession, value: Decimal) -> Decimal:
    row = await PricingService(session).get_settings()
    previous = Decimal(str(row.delivery_fee_eur))
    row.delivery_fee_eur = value
    await session.commit()
    return previous


# Витрина прячет 270.02, оставляет 270.01; админ и SQL без капа видят дорогой unit.
@pytest.mark.asyncio
async def test_storefront_hides_unit_over_supplier_cap(
    monkeypatch: pytest.MonkeyPatch,
    merge_unique_suffix: int,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))
    assert max_supplier_goods_eur() == Decimal("270.01")

    async with async_session_maker() as session:
        product = await _pick_storefront_eligible_in_stock_product(session)
        product_id = int(product.id)
        original = Decimal(str(product.supplier_price_eur or 0))
        user = await create_telegram_user(session, merge_unique_suffix + 820)
        try:
            await _set_supplier_price(session, product_id, Decimal("270.01"))
            assert await _listed_on_storefront(session, product_id) is True
            allowed = await ProductService(session).get_product_for_storefront(
                product_id
            )
            assert allowed is not None

            await _set_supplier_price(session, product_id, Decimal("270.02"))
            assert await _listed_on_storefront(session, product_id) is False
            hidden = await ProductService(session).get_product_for_storefront(
                product_id
            )
            assert hidden is None
            admin = await ProductService(session).get_product(product_id)
            assert admin is not None
            with pytest.raises(ValueError, match="не найден"):
                await CartService(session).add_or_update_item(
                    user_id=user.id,
                    product_id=product_id,
                    quantity=1,
                )
        finally:
            await _set_supplier_price(session, product_id, original)


# 400 EUR: snapshot 68; смена delivery_fee после create заказ не двигает.
@pytest.mark.asyncio
async def test_checkout_400_eur_preview_create_and_frozen_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    merge_unique_suffix: int,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))

    async with async_session_maker() as session:
        product = await _pick_in_stock_product(session)
        product_id = int(product.id)
        original_price = Decimal(str(product.supplier_price_eur or 0))
        original_fee: Decimal | None = None
        user = await create_telegram_user(session, merge_unique_suffix + 821)
        try:
            original_fee = await _set_delivery_fee(session, Decimal("34.00"))
            await _set_supplier_price(session, product_id, Decimal("200.00"))
            await set_product_available_stock(session, product_id, stock=10)
            await CartService(session).add_or_update_item(
                user_id=user.id,
                product_id=product_id,
                quantity=2,
            )
            await session.commit()

            service = OrderService(session)
            preview = await service.preview_checkout(user_id=user.id)
            pricing = await PricingService(session).get_settings()
            rate = Decimal(str(pricing.eur_rate))
            delivery_rub = calculate_delivery_rub(Decimal("68.00"), rate)
            supplier_shipping_rub = calculate_delivery_rub(Decimal("59.98"), rate)
            assert preview.supplier_cost_eur == Decimal("400.00")
            assert preview.delivery_fee_amount == ceil_rub(delivery_rub)
            assert preview.delivery_fee_amount != ceil_rub(supplier_shipping_rub)

            created = await service.create_order(
                user_id=user.id,
                idempotency_key=f"tp-est-400-{merge_unique_suffix}",
                delivery_payload=_DELIVERY,
                notification_channels=["telegram"],
            )
            order = await session.get(Order, created.id)
            assert order is not None
            assert order.delivery_fee_eur_snapshot == Decimal("68.00")
            assert order.supplier_cost_eur_snapshot == Decimal("400.00")
            assert order.delivery_fee_amount == delivery_rub
            assert order.total_amount == (
                order.items_subtotal_amount
                - order.discount_items_amount
                + order.delivery_fee_amount
            )
            assert order.delivery_fee_amount != supplier_shipping_rub

            await _set_delivery_fee(session, Decimal("99.00"))
            await session.refresh(order)
            assert order.delivery_fee_eur_snapshot == Decimal("68.00")
            assert order.delivery_fee_amount == delivery_rub
        finally:
            await _set_supplier_price(session, product_id, original_price)
            if original_fee is not None:
                await _set_delivery_fee(session, original_fee)


# 100 EUR товаров — N=1, snapshot как раньше равен базе доставки.
@pytest.mark.asyncio
async def test_checkout_100_eur_keeps_single_delivery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    merge_unique_suffix: int,
) -> None:
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_MAX_EUR", Decimal("300"))
    monkeypatch.setattr(settings, "SUPPLIER_ORDER_SHIPPING_EUR", Decimal("29.99"))

    async with async_session_maker() as session:
        product = await _pick_in_stock_product(session)
        product_id = int(product.id)
        original_price = Decimal(str(product.supplier_price_eur or 0))
        original_fee: Decimal | None = None
        user = await create_telegram_user(session, merge_unique_suffix + 822)
        try:
            original_fee = await _set_delivery_fee(session, Decimal("34.00"))
            await _set_supplier_price(session, product_id, Decimal("100.00"))
            await set_product_available_stock(session, product_id, stock=10)
            await CartService(session).add_or_update_item(
                user_id=user.id,
                product_id=product_id,
                quantity=1,
            )
            await session.commit()
            created = await OrderService(session).create_order(
                user_id=user.id,
                idempotency_key=f"tp-est-100-{merge_unique_suffix}",
                delivery_payload=_DELIVERY,
                notification_channels=["telegram"],
            )
            order = await session.get(Order, created.id)
            assert order is not None
            assert order.delivery_fee_eur_snapshot == Decimal("34.00")
            assert order.supplier_cost_eur_snapshot == Decimal("100.00")
        finally:
            await _set_supplier_price(session, product_id, original_price)
            if original_fee is not None:
                await _set_delivery_fee(session, original_fee)
