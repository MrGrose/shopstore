import pytest

from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_attribute_referrer_attribution_locked(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7970{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        buyer = await user_svc.register_user_by_phone(f"+7971{suffix:07d}")
        buyer.referral_attribution_locked = True
        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)

        result = await ReferralService(session).attribute_referrer(
            buyer, partner.referral_code
        )
        assert result.status == "attribution_locked"
        assert result.user.referrer_id is None


@pytest.mark.asyncio
async def test_admin_clear_sets_attribution_locked(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        admin = await user_svc.register_user_by_phone(f"+7972{suffix:07d}")
        partner = await user_svc.register_user_by_phone(f"+7973{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        buyer = await user_svc.register_user_by_phone(f"+7974{suffix:07d}")
        buyer.referrer_id = partner.id
        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)

        updated = await ReferralService(session).admin_set_referrer(
            buyer,
            None,
            admin_user_id=admin.id,
            reason="тест сброса",
        )
        assert updated.referrer_id is None
        assert updated.referral_attribution_locked is True

        audit = await ReferralService(session).referral_repo.list_referral_audit(
            buyer.id
        )
        assert len(audit) == 1
        assert audit[0].new_attribution_locked is True
        assert audit[0].reason == "тест сброса"


@pytest.mark.asyncio
async def test_admin_set_referrer_unlocks_from_clear(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        admin = await user_svc.register_user_by_phone(f"+7975{suffix:07d}")
        partner = await user_svc.register_user_by_phone(f"+7976{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        buyer = await user_svc.register_user_by_phone(f"+7977{suffix:07d}")
        buyer.referral_attribution_locked = True
        session.add(buyer)
        await session.commit()
        await session.refresh(buyer)

        updated = await ReferralService(session).admin_set_referrer(
            buyer,
            partner.id,
            admin_user_id=admin.id,
            reason="назначение после clear",
        )
        assert updated.referrer_id == partner.id
        assert updated.referral_attribution_locked is False


@pytest.mark.asyncio
async def test_admin_set_referrer_rejects_cycle(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        admin = await user_svc.register_user_by_phone(f"+7960{suffix:07d}")
        a = await user_svc.register_user_by_phone(f"+7961{suffix:07d}")
        b = await user_svc.register_user_by_phone(f"+7962{suffix:07d}")
        a.referrer_id = b.id
        session.add(a)
        await session.commit()
        await session.refresh(a)
        await session.refresh(b)

        with pytest.raises(ValueError, match="цикл"):
            await ReferralService(session).admin_set_referrer(
                b,
                a.id,
                admin_user_id=admin.id,
                reason="попытка цикла",
            )
