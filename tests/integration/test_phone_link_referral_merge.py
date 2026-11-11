import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.core.user_roles import UserRole
from src.models.auth_identity import AuthIdentity
from src.models.order import Order, OrderStatus
from src.models.pricing import ReferralEarning
from src.models.user import User
from src.repositories.auth_identity_repo import PROVIDER_PHONE, PROVIDER_TELEGRAM
from src.repositories.session import async_session_maker
from src.services.identity_service import IdentityService
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_link_phone_merges_referral_donor_assets(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    telegram_id = 8_100_000_000 + suffix
    phone_e164 = f"+7988{suffix:07d}"
    donor_code = f"RB{suffix:06d}"[:16]
    tag = f"ref-merge-test-{suffix}"

    user_a_id = 0
    user_b_id = 0
    invited_id = 0
    earning_id = 0

    async with async_session_maker() as session:
        user_svc = UserService(session)
        identity_svc = IdentityService(session)

        user_a = await user_svc.upsert_telegram_user(
            telegram_id=telegram_id,
            telegram_username=f"user_a_{suffix}",
            name=f"User A {tag}",
        )
        user_a_id = user_a.id
        assert user_a.role == UserRole.BUYER.value

        user_b = await user_svc.register_user_by_phone(phone_e164)
        user_b_id = user_b.id
        user_b.referral_code = donor_code
        session.add(user_b)
        await session.commit()
        await session.refresh(user_b)

        invited = User(
            email=f"invited-{suffix}@test.local",
            name=f"Invited {tag}",
            role=UserRole.BUYER.value,
            referrer_id=user_b_id,
        )
        session.add(invited)
        await session.flush()
        invited = await ReferralService(session).ensure_referral_code(invited)
        await session.commit()
        await session.refresh(invited)
        invited_id = invited.id

        order = Order(
            user_id=invited_id,
            total_amount=Decimal("5000.00"),
            items_subtotal_amount=Decimal("4500.00"),
            discount_items_amount=Decimal("0"),
            delivery_fee_amount=Decimal("500.00"),
            delivery_fee_eur_snapshot=Decimal("30"),
            eur_rate_snapshot=Decimal("100"),
            status=OrderStatus.COMPLETED.value,
            idempotency_key=f"ref-merge-test-{uuid.uuid4()}",
        )
        session.add(order)
        await session.flush()

        earning = ReferralEarning(
            referrer_id=user_b_id,
            referred_user_id=invited_id,
            order_id=order.id,
            order_amount_rub=Decimal("4500.00"),
            commission_percent=Decimal("5.00"),
            commission_amount_rub=Decimal("225.00"),
        )
        session.add(earning)
        await session.commit()
        await session.refresh(earning)
        earning_id = earning.id

        user_a = await user_svc.get_user(user_a_id)
        assert user_a is not None
        linked = await identity_svc.link_phone_to_user(user_a, phone_e164)
        assert linked.id == user_a_id
        assert linked.role == UserRole.BUYER.value
        assert linked.referral_code == donor_code

    async with async_session_maker() as session:
        assert await session.get(User, user_b_id) is None

        user_a_row = await session.get(User, user_a_id)
        assert user_a_row is not None
        assert user_a_row.role == UserRole.BUYER.value
        assert user_a_row.referral_code == donor_code

        phone_identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == PROVIDER_PHONE,
                AuthIdentity.provider_user_id == phone_e164,
            )
        )
        assert phone_identity is not None
        assert phone_identity.user_id == user_a_id

        tg_identity = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_a_id,
                AuthIdentity.provider == PROVIDER_TELEGRAM,
            )
        )
        assert tg_identity is not None

        invited_row = await session.get(User, invited_id)
        assert invited_row is not None
        assert invited_row.referrer_id == user_a_id

        earning_row = await session.get(ReferralEarning, earning_id)
        assert earning_row is not None
        assert earning_row.referrer_id == user_a_id
