import httpx
import pytest

from src.core.user_roles import UserRole
from src.main import app
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.identity_service import IdentityService
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


@pytest.mark.asyncio
async def test_resolve_referrer_opaque_code(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7977{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        code = partner.referral_code
        assert code is not None
        assert not code.startswith("PS-")

        referrer_id = await ReferralService(session).resolve_referrer(code)
        assert referrer_id == partner.id


@pytest.mark.asyncio
async def test_resolve_referrer_alias(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    alias = f"ref{suffix % 100000:05d}"
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7978{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        await ReferralService(session).set_admin_referral_alias(partner, alias)

        referrer_id = await ReferralService(session).resolve_referrer(alias)
        assert referrer_id == partner.id


@pytest.mark.asyncio
async def test_set_admin_referral_alias_duplicate_rejects(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    alias = f"dup{suffix % 100000:05d}"
    async with async_session_maker() as session:
        user_svc = UserService(session)
        first = await user_svc.register_user_by_phone(f"+7979{suffix:07d}")
        second = await user_svc.register_user_by_phone(f"+7980{suffix:07d}")
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)
        first = await ReferralService(session).ensure_referral_code(first)
        second = await ReferralService(session).ensure_referral_code(second)
        await ReferralService(session).set_admin_referral_alias(first, alias)

        with pytest.raises(ValueError, match="занят"):
            await ReferralService(session).set_admin_referral_alias(second, alias)


@pytest.mark.asyncio
async def test_self_referral_blocked_with_alias(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    alias = f"self{suffix % 100000:05d}"
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7981{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        await ReferralService(session).set_admin_referral_alias(partner, alias)

        updated = await ReferralService(session).attribute_referrer(partner, alias)
        assert updated.status == "self_referral"
        assert updated.user.referrer_id is None


@pytest.mark.asyncio
async def test_telegram_upsert_with_alias(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    alias = f"tg{suffix % 100000:05d}"
    telegram_id = 8_200_000_000 + suffix
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7983{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        await ReferralService(session).set_admin_referral_alias(partner, alias)

        buyer = await user_svc.upsert_telegram_user(
            telegram_id=telegram_id,
            telegram_username=f"buyer_{suffix}",
            name=f"Buyer {suffix}",
            referral_code=alias,
        )
        assert buyer.referrer_id == partner.id


@pytest.mark.asyncio
async def test_set_admin_referral_alias_admin_forbidden(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        admin = User(
            email=f"admin-{suffix}@test.local",
            name=f"Admin {suffix}",
            role=UserRole.ADMIN.value,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        with pytest.raises(ValueError, match="Покупатель"):
            await ReferralService(session).set_admin_referral_alias(admin, "martin")


@pytest.mark.asyncio
async def test_set_admin_referral_alias_conflicts_with_referral_code(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    code = f"rb{suffix:06d}"[:16]
    alias = code.lower()
    async with async_session_maker() as session:
        user_svc = UserService(session)
        owner = await user_svc.register_user_by_phone(f"+7985{suffix:07d}")
        owner.referral_code = code
        session.add(owner)
        partner = await user_svc.register_user_by_phone(f"+7986{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)

        with pytest.raises(ValueError, match="системным кодом"):
            await ReferralService(session).set_admin_referral_alias(partner, alias)


@pytest.mark.asyncio
async def test_resolve_referrer_uppercase_alias(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    alias = f"upc{suffix % 100000:05d}"
    async with async_session_maker() as session:
        user_svc = UserService(session)
        partner = await user_svc.register_user_by_phone(f"+7987{suffix:07d}")
        partner = await ReferralService(session).ensure_referral_code(partner)
        await ReferralService(session).set_admin_referral_alias(partner, alias)

        referrer_id = await ReferralService(session).resolve_referrer(alias.upper())
        assert referrer_id == partner.id


@pytest.mark.asyncio
async def test_merge_keeps_survivor_referral_alias(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    telegram_id = 8_300_000_000 + suffix
    phone_e164 = f"+7989{suffix:07d}"
    survivor_alias = f"sv{suffix % 100000:05d}"
    donor_alias = f"dn{suffix % 100000:05d}"
    donor_code = f"RB{suffix:06d}"[:16]

    async with async_session_maker() as session:
        user_svc = UserService(session)
        identity_svc = IdentityService(session)

        survivor = await user_svc.upsert_telegram_user(
            telegram_id=telegram_id,
            telegram_username=f"sv_{suffix}",
            name=f"Survivor {suffix}",
        )
        survivor.referral_alias = survivor_alias
        session.add(survivor)
        await session.commit()
        await session.refresh(survivor)
        survivor_id = survivor.id

        donor = await user_svc.register_user_by_phone(phone_e164)
        donor.referral_code = donor_code
        donor.referral_alias = donor_alias
        session.add(donor)
        await session.commit()
        await session.refresh(donor)
        donor_id = donor.id

        survivor = await user_svc.get_user(survivor_id)
        assert survivor is not None
        linked = await identity_svc.link_phone_to_user(survivor, phone_e164)
        assert linked.id == survivor_id

    async with async_session_maker() as session:
        assert await session.get(User, donor_id) is None
        row = await session.get(User, survivor_id)
        assert row is not None
        assert row.referral_alias == survivor_alias


@pytest.mark.asyncio
async def test_ref_alias_redirect() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get("/ref/martin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/?ref=martin"
