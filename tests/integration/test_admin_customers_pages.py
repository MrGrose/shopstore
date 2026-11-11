import httpx
import pytest

from src.main import app
from src.repositories.referral_repo import ReferralRepository
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService
from tests.integration.helpers.order_admin import create_admin_access_token


@pytest.mark.asyncio
async def test_list_invited_users_returns_referrals(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7980{suffix:07d}")
        invitee_a = await user_svc.register_user_by_phone(f"+7981{suffix:07d}")
        invitee_b = await user_svc.register_user_by_phone(f"+7982{suffix:07d}")
        invitee_a.referrer_id = referrer.id
        invitee_b.referrer_id = referrer.id
        session.add_all([invitee_a, invitee_b])
        await session.commit()

        repo = ReferralRepository(session)
        invited = await repo.list_invited_users(referrer.id)
        assert len(invited) == 2
        invited_ids = {user.id for user in invited}
        assert invitee_a.id in invited_ids
        assert invitee_b.id in invited_ids


@pytest.mark.asyncio
async def test_get_admin_customer_referral_block_includes_invited_users(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7990{suffix:07d}")
        invitee = await user_svc.register_user_by_phone(f"+7991{suffix:07d}")
        invitee.referrer_id = referrer.id
        session.add(invitee)
        await session.commit()

        block = await ReferralService(session).get_admin_customer_referral_block(
            referrer.id
        )
        invited_users = block.get("invited_users")
        assert isinstance(invited_users, list)
        assert len(invited_users) == 1
        assert invited_users[0].id == invitee.id


@pytest.mark.asyncio
async def test_admin_customers_page_renders_list_shell(
    merge_unique_suffix: int,
) -> None:
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/customers",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    text = response.text
    assert "Клиенты" in text
    assert 'id="admin-customers-total-count"' in text
    assert 'id="admin-customers-filters"' in text
    assert 'id="admin-customers-table"' in text


@pytest.mark.asyncio
async def test_admin_customers_table_partial_renders(merge_unique_suffix: int) -> None:
    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, merge_unique_suffix)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/customers/table",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert "customers-table-wrap" in response.text
    assert "Оплачено" in response.text


@pytest.mark.asyncio
async def test_admin_customers_table_shows_referrer_column(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7940{suffix:07d}")
        referrer.name = f"List Referrer {suffix}"
        buyer = await user_svc.register_user_by_phone(f"+7941{suffix:07d}")
        buyer.referrer_id = referrer.id
        session.add_all([referrer, buyer])
        await session.commit()
        _, token = await create_admin_access_token(session, suffix + 77_000)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/internal/admin/customers/table",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    text = response.text
    assert "Реферал" in text
    assert f"List Referrer {suffix}" in text


@pytest.mark.asyncio
async def test_admin_customers_search_by_name_phone_and_id(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    phone = f"+7930{suffix:07d}"
    async with async_session_maker() as session:
        user_svc = UserService(session)
        user = await user_svc.register_user_by_phone(phone)
        user.name = f"Search Target {suffix}"
        user.email = f"search-{suffix}@admin-search.test"
        session.add(user)
        await session.commit()
        _, token = await create_admin_access_token(session, suffix + 66_000)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        by_name = await client.get(
            "/internal/admin/customers/table",
            params={"q": f"Search Target {suffix}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        by_phone = await client.get(
            "/internal/admin/customers/table",
            params={"q": phone[-7:]},
            headers={"Authorization": f"Bearer {token}"},
        )
        by_id = await client.get(
            "/internal/admin/customers/table",
            params={"q": str(user.id)},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert by_name.status_code == 200
    assert f"Search Target {suffix}" in by_name.text
    assert by_phone.status_code == 200
    assert f"#{user.id}" in by_phone.text
    assert by_id.status_code == 200
    assert f"#{user.id}" in by_id.text


@pytest.mark.asyncio
async def test_admin_customer_detail_referral_links(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7960{suffix:07d}")
        invitee = await user_svc.register_user_by_phone(f"+7961{suffix:07d}")
        invitee.referrer_id = referrer.id
        invitee.name = f"Invitee {suffix}"
        session.add(invitee)
        await session.commit()
        _, token = await create_admin_access_token(session, suffix + 99_000)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        detail = await client.get(
            "/internal/admin/customers",
            params={"id": referrer.id},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert detail.status_code == 200
    text = detail.text
    assert "Реферал" in text
    assert "Кого привёл этот клиент" in text
    assert f"Invitee {suffix}" in text
    assert f'id="customer-profile-form-{referrer.id}"' in text
    assert f"/internal/admin/customers/{referrer.id}/delivery" in text
    assert f"/customers/{referrer.id}/referrer" in text


@pytest.mark.asyncio
async def test_admin_customer_detail_shows_referrer(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    async with async_session_maker() as session:
        user_svc = UserService(session)
        referrer = await user_svc.register_user_by_phone(f"+7962{suffix:07d}")
        referrer.name = f"Referrer {suffix}"
        buyer = await user_svc.register_user_by_phone(f"+7963{suffix:07d}")
        buyer.referrer_id = referrer.id
        session.add_all([referrer, buyer])
        await session.commit()
        _, token = await create_admin_access_token(session, suffix + 88_000)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        detail = await client.get(
            "/internal/admin/customers",
            params={"id": buyer.id},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert detail.status_code == 200
    assert f"Referrer {suffix}" in detail.text
    assert "Кто привёл этого клиента" in detail.text
