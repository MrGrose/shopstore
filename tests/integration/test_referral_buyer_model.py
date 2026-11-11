import uuid
from decimal import Decimal

import pytest

from src.core.user_roles import UserRole
from src.models.order import Order, OrderStatus
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_resolve_referrer_skips_inactive_buyer(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7990{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        partner.is_active = False
        session.add(partner)
        await session.commit()

        referrer_id = await ReferralService(session).resolve_referrer(
            partner.referral_code
        )
        assert referrer_id is None


@pytest.mark.asyncio
async def test_resolve_referrer_skips_admin(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        admin = User(
            email=f"admin-ref-{suffix}@test.local",
            name=f"Admin {suffix}",
            role=UserRole.ADMIN.value,
            referral_code=f"ADM{suffix:06d}"[:16],
        )
        session.add(admin)
        await session.commit()

        referrer_id = await ReferralService(session).resolve_referrer(
            admin.referral_code
        )
        assert referrer_id is None


@pytest.mark.asyncio
async def test_resolve_referrer_rejects_legacy_ps_code(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7992{suffix:07d}")
        partner.referral_code = f"PS-{partner.id}"
        session.add(partner)
        await session.commit()

        referrer_id = await ReferralService(session).resolve_referrer(
            partner.referral_code
        )
        assert referrer_id is None


@pytest.mark.asyncio
async def test_accrue_skips_inactive_referrer(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7991{suffix:07d}")
        referrer = await ReferralService(session).ensure_referral_code(referrer)
        referrer.is_active = False
        session.add(referrer)
        await session.flush()

        buyer = User(
            email=f"buyer-{suffix}@test.local",
            name=f"Buyer {suffix}",
            role=UserRole.BUYER.value,
            referrer_id=referrer.id,
        )
        session.add(buyer)
        await session.flush()
        buyer = await ReferralService(session).ensure_referral_code(buyer)
        await session.flush()

        order = Order(
            user_id=buyer.id,
            total_amount=Decimal("5000.00"),
            items_subtotal_amount=Decimal("4500.00"),
            discount_items_amount=Decimal("0"),
            delivery_fee_amount=Decimal("500.00"),
            delivery_fee_eur_snapshot=Decimal("30"),
            eur_rate_snapshot=Decimal("100"),
            status=OrderStatus.COMPLETED.value,
            idempotency_key=f"inactive-ref-{uuid.uuid4()}",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        earning = await ReferralService(session).accrue_for_order(order)
        assert earning is None
