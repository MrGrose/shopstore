import httpx
import pytest
from sqlalchemy import select

from src.main import app
from src.models.user import User
from src.repositories.session import async_session_maker
from src.schemas.support import SupportTicketCreateSchema
from src.services.delivery_profile_service import DeliveryProfileService
from src.services.support.service import SupportService
from src.services.user_service import UserService
from tests.integration.helpers.order_admin import create_admin_access_token
from tests.integration.helpers.test_customer import create_test_customer


def _assert_redirect_ok(response: httpx.Response) -> str:
    assert response.status_code == 303, response.text
    location = response.headers.get("location", "")
    assert "error=" not in location, location
    return location


@pytest.mark.asyncio
async def test_admin_customer_forms_profile_delivery_referral_and_delete(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"forms-{suffix}@admin-forms.test"
    alias = f"alias{suffix}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 50_000)
        partner = await UserService(session).register_user_by_phone(
            f"+7950{suffix:07d}"
        )
        partner.name = f"Partner {suffix}"
        user = await create_test_customer(
            session,
            name=f"Form Test {suffix}",
            email=email,
            telegram_username=f"form_{suffix}",
            telegram_id=None,
        )
        session.add(partner)
        await session.commit()
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        update = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": f"Updated {suffix}",
                "email": email,
                "telegram_username": f"updated_{suffix}",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(update)

        delivery = await client.post(
            f"/internal/admin/customers/{user_id}/delivery",
            headers=headers,
            data={
                "last_name": "Ivanov",
                "first_name": "Ivan",
                "street": "Testovaya",
                "house": "10A",
                "apartment": "42",
                "city": "Moscow",
                "postal_code": "101000",
                "phone": "+79001234567",
            },
        )
        _assert_redirect_ok(delivery)

        commission = await client.post(
            f"/internal/admin/customers/{user_id}/referral-commission",
            headers=headers,
            data={"referral_commission_percent": "7.5"},
        )
        _assert_redirect_ok(commission)

        alias_save = await client.post(
            f"/internal/admin/customers/{user_id}/referral-alias",
            headers=headers,
            data={"referral_alias": alias},
        )
        _assert_redirect_ok(alias_save)

        referrer = await client.post(
            f"/internal/admin/customers/{user_id}/referrer",
            headers=headers,
            data={
                "referrer_id": str(partner.id),
                "referrer_change_reason": f"integration test {suffix}",
            },
        )
        _assert_redirect_ok(referrer)

        detail = await client.get(
            "/internal/admin/customers",
            params={"id": user_id},
            headers=headers,
        )
        assert detail.status_code == 200
        text = detail.text
        assert f"Updated {suffix}" in text
        assert 'value="Testovaya"' in text
        assert f'value="{alias}"' in text
        assert f"Partner {suffix}" in text
        assert f"customer-referral-commission-{user_id}" in text
        assert "7.5" in text

        commission_clear = await client.post(
            f"/internal/admin/customers/{user_id}/referral-commission",
            headers=headers,
            data={"clear_referral_commission": "1"},
        )
        _assert_redirect_ok(commission_clear)

        alias_clear = await client.post(
            f"/internal/admin/customers/{user_id}/referral-alias",
            headers=headers,
            data={"clear_alias": "1"},
        )
        _assert_redirect_ok(alias_clear)

        referrer_clear = await client.post(
            f"/internal/admin/customers/{user_id}/referrer",
            headers=headers,
            data={
                "referrer_id": "",
                "referrer_change_reason": f"clear {suffix}",
            },
        )
        _assert_redirect_ok(referrer_clear)

        delivery_reset = await client.post(
            f"/internal/admin/customers/{user_id}/delivery/reset",
            headers=headers,
        )
        _assert_redirect_ok(delivery_reset)

        after_reset = await client.get(
            "/internal/admin/customers",
            params={"id": user_id},
            headers=headers,
        )
        assert after_reset.status_code == 200
        assert "Профиль доставки не заполнен" in after_reset.text

        delete = await client.post(
            f"/internal/admin/customers/{user_id}/delete",
            headers=headers,
        )
        _assert_redirect_ok(delete)

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is None
        profile = await DeliveryProfileService(session).get_profile(user_id)
        assert profile is None


@pytest.mark.asyncio
async def test_admin_customers_bulk_delete_selected(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"bulk-{suffix}@admin-forms.test"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 70_000)
        user = await create_test_customer(
            session,
            name=f"Bulk {suffix}",
            email=email,
            telegram_username=None,
            telegram_id=None,
        )
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        table = await client.get("/internal/admin/customers/table", headers=headers)
        assert table.status_code == 200
        assert "data-customer-delete-checkbox" in table.text
        assert f'value="{user_id}"' in table.text

        delete = await client.post(
            "/internal/admin/customers/delete-selected",
            headers=headers,
            data={"user_ids": str(user_id)},
        )
        assert delete.status_code == 200, delete.text
        payload = delete.json()
        assert payload["deleted"] == 1

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is None


@pytest.mark.asyncio
async def test_admin_customer_delete_with_support_ticket(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"support-del-{suffix}@admin-forms.test"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 80_000)
        user = await create_test_customer(
            session,
            name=f"Support Delete {suffix}",
            email=email,
            telegram_username=None,
            telegram_id=None,
        )
        user_id = user.id
        await SupportService(session).create_ticket(
            user_id=user_id,
            payload=SupportTicketCreateSchema(
                topic="general",
                body="test ticket",
                order_id=None,
            ),
        )
        await session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        delete = await client.post(
            f"/internal/admin/customers/{user_id}/delete",
            headers=headers,
        )
        _assert_redirect_ok(delete)

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        assert user is None
