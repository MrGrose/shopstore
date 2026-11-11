import uuid
from decimal import Decimal

import pytest

from src.core.user_roles import UserRole
from src.models.order import Order, OrderStatus
from src.models.user import User
from src.repositories.referral_repo import ReferralRepository
from src.repositories.session import async_session_maker
from src.services.pricing_service import PricingService
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


def _completed_order(
    *,
    user_id: int,
    total_amount: Decimal,
    delivery_fee_amount: Decimal,
    key_suffix: str,
) -> Order:
    return Order(
        user_id=user_id,
        total_amount=total_amount,
        items_subtotal_amount=total_amount - delivery_fee_amount,
        discount_items_amount=Decimal("0"),
        delivery_fee_amount=delivery_fee_amount,
        delivery_fee_eur_snapshot=Decimal("30"),
        eur_rate_snapshot=Decimal("100"),
        status=OrderStatus.COMPLETED.value,
        idempotency_key=f"ref-accrual-{key_suffix}-{uuid.uuid4()}",
    )


@pytest.mark.asyncio
async def test_accrue_single_level_chain_a_b_c(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        ref_svc = ReferralService(session)

        user_a = await user_svc.register_user_by_phone(f"+7980{suffix:07d}")
        user_a = await ref_svc.ensure_referral_code(user_a)
        await session.flush()

        user_b = User(
            email=f"ref-b-{suffix}@test.local",
            name=f"Buyer B {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=user_a.id,
        )
        session.add(user_b)
        await session.flush()
        user_b = await ref_svc.ensure_referral_code(user_b)

        user_c = User(
            email=f"ref-c-{suffix}@test.local",
            name=f"Buyer C {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=user_b.id,
        )
        session.add(user_c)
        await session.flush()
        user_c = await ref_svc.ensure_referral_code(user_c)

        order = _completed_order(
            user_id=user_c.id,
            total_amount=Decimal("3000.00"),
            delivery_fee_amount=Decimal("500.00"),
            key_suffix=f"abc-{suffix}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ref_svc.accrue_for_order(order)
        assert earning is not None
        assert earning.referrer_id == user_b.id
        assert earning.referred_user_id == user_c.id
        assert earning.order_amount_rub == Decimal("2500.00")

        repo = ReferralRepository(session)
        assert await repo.count_earnings(user_a.id) == 0
        assert await repo.count_earnings(user_b.id) == 1


@pytest.mark.asyncio
async def test_accrue_idempotent_by_order_id(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        ref_svc = ReferralService(session)

        referrer = await user_svc.register_user_by_phone(f"+7981{suffix:07d}")
        referrer = await ref_svc.ensure_referral_code(referrer)
        await session.flush()

        buyer = User(
            email=f"buyer-idem-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ref_svc.ensure_referral_code(buyer)

        order = _completed_order(
            user_id=buyer.id,
            total_amount=Decimal("2000.00"),
            delivery_fee_amount=Decimal("500.00"),
            key_suffix=f"idem-{suffix}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        first = await ref_svc.accrue_for_order(order)
        second = await ref_svc.accrue_for_order(order)

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert await ReferralRepository(session).count_earnings(referrer.id) == 1


@pytest.mark.asyncio
async def test_accrue_skips_non_completed_order(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        ref_svc = ReferralService(session)

        referrer = await user_svc.register_user_by_phone(f"+7982{suffix:07d}")
        referrer = await ref_svc.ensure_referral_code(referrer)
        await session.flush()

        buyer = User(
            email=f"buyer-pending-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ref_svc.ensure_referral_code(buyer)

        order = _completed_order(
            user_id=buyer.id,
            total_amount=Decimal("2000.00"),
            delivery_fee_amount=Decimal("500.00"),
            key_suffix=f"pending-{suffix}",
        )
        order.status = OrderStatus.DELIVERY.value
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ref_svc.accrue_for_order(order)
        assert earning is None


@pytest.mark.asyncio
async def test_accrue_base_excludes_delivery_fee(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        ref_svc = ReferralService(session)

        referrer = await user_svc.register_user_by_phone(f"+7983{suffix:07d}")
        referrer = await ref_svc.ensure_referral_code(referrer)
        await PricingService(session).update_admin_settings(
            referral_commission_percent=Decimal("5.00")
        )
        await session.flush()

        buyer = User(
            email=f"buyer-base-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ref_svc.ensure_referral_code(buyer)

        order = _completed_order(
            user_id=buyer.id,
            total_amount=Decimal("2000.00"),
            delivery_fee_amount=Decimal("500.00"),
            key_suffix=f"base-{suffix}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ref_svc.accrue_for_order(order)
        assert earning is not None
        assert earning.order_amount_rub == Decimal("1500.00")
        assert earning.commission_amount_rub == Decimal("75.00")
