import uuid
from decimal import Decimal

import pytest

from src.core.user_roles import UserRole
from src.models.order import Order, OrderStatus
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.pricing_service import PricingService
from src.services.referral_service import (
    ReferralService,
    effective_commission_percent,
    referral_commission_percent_source,
)
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_effective_commission_null_uses_global(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        buyer = await user_svc.register_user_by_phone(f"+7993{suffix:07d}")
        buyer = await ReferralService(session).ensure_referral_code(buyer)
        await PricingService(session).update_admin_settings(
            referral_commission_percent=Decimal("7.50")
        )
        percent = await effective_commission_percent(buyer, session)
        assert percent == Decimal("7.50")
        assert referral_commission_percent_source(buyer) == "global"


@pytest.mark.asyncio
async def test_effective_commission_individual_override(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        buyer = await user_svc.register_user_by_phone(f"+7994{suffix:07d}")
        buyer = await ReferralService(session).ensure_referral_code(buyer)
        buyer.referral_commission_percent = Decimal("12.00")
        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)

        percent = await effective_commission_percent(buyer, session)
        assert percent == Decimal("12.00")
        assert referral_commission_percent_source(buyer) == "individual"


@pytest.mark.asyncio
async def test_accrue_skips_zero_override(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7995{suffix:07d}")
        referrer = await ReferralService(session).ensure_referral_code(referrer)
        referrer.referral_commission_percent = Decimal("0.00")
        session.add(referrer)
        await session.flush()

        buyer = User(
            email=f"buyer-zero-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ReferralService(session).ensure_referral_code(buyer)

        order = Order(
            user_id=buyer.id,
            total_amount=Decimal("5000.00"),
            items_subtotal_amount=Decimal("4500.00"),
            discount_items_amount=Decimal("0"),
            delivery_fee_amount=Decimal("500.00"),
            delivery_fee_eur_snapshot=Decimal("30"),
            eur_rate_snapshot=Decimal("100"),
            status=OrderStatus.COMPLETED.value,
            idempotency_key=f"zero-commission-{uuid.uuid4()}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ReferralService(session).accrue_for_order(order)
        assert earning is None


@pytest.mark.asyncio
async def test_accrue_uses_individual_override_snapshot(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7996{suffix:07d}")
        referrer = await ReferralService(session).ensure_referral_code(referrer)
        referrer.referral_commission_percent = Decimal("10.00")
        session.add(referrer)
        await session.flush()

        buyer = User(
            email=f"buyer-ovr-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ReferralService(session).ensure_referral_code(buyer)

        order = Order(
            user_id=buyer.id,
            total_amount=Decimal("2000.00"),
            items_subtotal_amount=Decimal("1500.00"),
            discount_items_amount=Decimal("0"),
            delivery_fee_amount=Decimal("500.00"),
            delivery_fee_eur_snapshot=Decimal("30"),
            eur_rate_snapshot=Decimal("100"),
            status=OrderStatus.COMPLETED.value,
            idempotency_key=f"override-commission-{uuid.uuid4()}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ReferralService(session).accrue_for_order(order)
        assert earning is not None
        assert earning.commission_percent == Decimal("10.00")
        assert earning.commission_amount_rub == Decimal("150.00")
