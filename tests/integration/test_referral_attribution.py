import pytest

from src.core.user_roles import UserRole
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_attribute_referrer_already_attributed(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7997{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        buyer = await user_svc.register_user_by_phone(f"+7998{suffix:07d}")
        buyer.referrer_id = partner.id
        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)

        result = await ReferralService(session).attribute_referrer(
            buyer, partner.referral_code
        )
        assert result.status == "already_attributed"
        assert result.user.referrer_id == partner.id


@pytest.mark.asyncio
async def test_attribute_referrer_invalid_code(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        buyer = await user_svc.register_user_by_phone(f"+7999{suffix:07d}")

        result = await ReferralService(session).attribute_referrer(
            buyer, "not-a-real-code"
        )
        assert result.status == "invalid_code"
        assert result.user.referrer_id is None


@pytest.mark.asyncio
async def test_attribute_referrer_not_eligible_for_admin(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        admin = User(
            email=f"admin-attr-{suffix}@test.local",
            name=f"Admin {suffix}",
            role=UserRole.ADMIN.value,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)

        result = await ReferralService(session).attribute_referrer(admin, "abc")
        assert result.status == "not_eligible"


@pytest.mark.asyncio
async def test_attribute_referrer_attributed(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7981{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        buyer = await user_svc.register_user_by_phone(f"+7982{suffix:07d}")

        result = await ReferralService(session).attribute_referrer(
            buyer, partner.referral_code
        )
        assert result.status == "attributed"
        assert result.user.referrer_id == partner.id
