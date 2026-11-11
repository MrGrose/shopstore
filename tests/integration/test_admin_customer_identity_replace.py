import httpx
import pytest

from src.main import app
from src.repositories.session import async_session_maker
from src.services.identity_service import IdentityService
from src.services.user_service import UserService
from tests.integration.helpers.order_admin import create_admin_access_token
from tests.integration.helpers.test_customer import create_test_customer


def _assert_redirect_ok(response: httpx.Response) -> None:
    assert response.status_code == 303, response.text
    location = response.headers.get("location", "")
    assert "error=" not in location, location


@pytest.mark.asyncio
async def test_admin_can_replace_customer_login_phone_and_telegram_id(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"identity-{suffix}@admin-forms.test"
    phone_a = f"+7951{suffix:07d}"
    phone_b = f"+7952{suffix:07d}"
    tg_a = 9_000_000_000 + suffix
    tg_b = 9_100_000_000 + suffix

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 90_000)
        user = await create_test_customer(
            session,
            name=f"Identity {suffix}",
            email=email,
            telegram_username=f"tg_{suffix}",
            telegram_id=str(tg_a),
        )
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        add_phone = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": f"Identity {suffix}",
                "email": email,
                "login_phone": phone_a,
                "telegram_id": str(tg_a),
                "telegram_username": f"tg_{suffix}",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(add_phone)

        change_phone = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": f"Identity {suffix}",
                "email": email,
                "login_phone": phone_b,
                "telegram_id": str(tg_a),
                "telegram_username": f"tg_{suffix}",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(change_phone)

        change_tg = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": f"Identity {suffix}",
                "email": email,
                "login_phone": phone_b,
                "telegram_id": str(tg_b),
                "telegram_username": f"tg_new_{suffix}",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(change_tg)

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        identity_svc = IdentityService(session)
        assert await identity_svc.get_phone_e164_for_user(user) == phone_b
        assert await identity_svc.get_telegram_id_for_user(user) == tg_b
        assert (
            await identity_svc.get_telegram_username_for_user(user)
            == f"tg_new_{suffix}"
        )


@pytest.mark.asyncio
async def test_admin_cannot_assign_phone_already_used(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    phone = f"+7953{suffix:07d}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 91_000)
        owner = await UserService(session).register_user_by_phone(phone)
        target = await create_test_customer(
            session,
            name=f"Target {suffix}",
            email=f"target-{suffix}@admin-forms.test",
            telegram_username=None,
            telegram_id=None,
        )
        owner_id = owner.id
        target_id = target.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await client.post(
            f"/internal/admin/customers/{target_id}/update",
            headers=headers,
            data={
                "name": f"Target {suffix}",
                "email": f"target-{suffix}@admin-forms.test",
                "login_phone": phone,
                "telegram_id": "",
                "telegram_username": "",
                "role": "buyer",
            },
        )
        assert response.status_code == 303
        assert "error=" in response.headers.get("location", "")

    async with async_session_maker() as session:
        owner = await UserService(session).get_user(owner_id)
        target = await UserService(session).get_user(target_id)
        assert owner is not None and target is not None
        identity_svc = IdentityService(session)
        assert await identity_svc.get_phone_e164_for_user(owner) == phone
        assert await identity_svc.get_phone_e164_for_user(target) is None


@pytest.mark.asyncio
async def test_admin_can_clear_email_when_phone_remains(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"clear-email-{suffix}@admin-forms.test"
    phone = f"+7954{suffix:07d}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 92_000)
        user = await UserService(session).register_user_by_phone(phone)
        await IdentityService(session).link_email_to_user(user, email)
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": user.name or f"User {suffix}",
                "email": "",
                "login_phone": phone,
                "telegram_id": "",
                "telegram_username": "",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(response)

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        identity_svc = IdentityService(session)
        assert user.email is None
        assert await identity_svc.get_phone_e164_for_user(user) == phone
        identities = await identity_svc.list_identities_for_user(user.id)
        assert not any(item.provider == "email" for item in identities)


@pytest.mark.asyncio
async def test_admin_can_clear_email_even_without_other_login_methods(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"email-only-{suffix}@admin-forms.test"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 93_000)
        user = await create_test_customer(
            session,
            name=f"Email only {suffix}",
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
        response = await client.post(
            f"/internal/admin/customers/{user_id}/update",
            headers=headers,
            data={
                "name": f"Email only {suffix}",
                "email": "",
                "login_phone": "",
                "telegram_id": "",
                "telegram_username": "",
                "role": "buyer",
            },
        )
        _assert_redirect_ok(response)

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        assert user.email is None
        identities = await IdentityService(session).list_identities_for_user(user.id)
        assert identities == []


def _admin_update_payload(
    *,
    name: str,
    email: str = "",
    login_phone: str = "",
    telegram_id: str = "",
    telegram_username: str = "",
    role: str = "buyer",
) -> dict[str, str]:
    return {
        "name": name,
        "email": email,
        "login_phone": login_phone,
        "telegram_id": telegram_id,
        "telegram_username": telegram_username,
        "role": role,
    }


async def _admin_update_customer(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    user_id: int,
    payload: dict[str, str],
) -> httpx.Response:
    return await client.post(
        f"/internal/admin/customers/{user_id}/update",
        headers=headers,
        data=payload,
    )


@pytest.mark.asyncio
async def test_admin_can_unbind_telegram_while_phone_remains(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    phone = f"+7955{suffix:07d}"
    tg_id = 9_200_000_000 + suffix
    name = f"Unbind TG {suffix}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 94_000)
        user = await create_test_customer(
            session,
            name=name,
            email=None,
            telegram_username=f"tg_{suffix}",
            telegram_id=str(tg_id),
        )
        await IdentityService(session).admin_set_phone_for_user(user, phone)
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await _admin_update_customer(
            client,
            headers,
            user_id,
            _admin_update_payload(name=name, login_phone=phone),
        )
        _assert_redirect_ok(response)

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        identity_svc = IdentityService(session)
        assert await identity_svc.get_phone_e164_for_user(user) == phone
        assert await identity_svc.get_telegram_id_for_user(user) is None
        providers = {
            item.provider
            for item in await identity_svc.list_identities_for_user(user.id)
        }
        assert providers == {"phone"}


@pytest.mark.asyncio
async def test_admin_can_unbind_phone_while_telegram_remains(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    phone = f"+7956{suffix:07d}"
    tg_id = 9_300_000_000 + suffix
    name = f"Unbind phone {suffix}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 95_000)
        user = await create_test_customer(
            session,
            name=name,
            email=None,
            telegram_username=f"tg_{suffix}",
            telegram_id=str(tg_id),
        )
        await IdentityService(session).admin_set_phone_for_user(user, phone)
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        response = await _admin_update_customer(
            client,
            headers,
            user_id,
            _admin_update_payload(
                name=name,
                telegram_id=str(tg_id),
                telegram_username=f"tg_{suffix}",
            ),
        )
        _assert_redirect_ok(response)

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        identity_svc = IdentityService(session)
        assert await identity_svc.get_phone_e164_for_user(user) is None
        assert await identity_svc.get_telegram_id_for_user(user) == tg_id
        providers = {
            item.provider
            for item in await identity_svc.list_identities_for_user(user.id)
        }
        assert providers == {"telegram"}


@pytest.mark.asyncio
async def test_admin_cannot_unbind_last_login_method(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    phone = f"+7957{suffix:07d}"
    tg_id = 9_400_000_000 + suffix
    name = f"Last login {suffix}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 96_000)
        phone_user = await UserService(session).register_user_by_phone(phone)
        tg_user = await create_test_customer(
            session,
            name=name,
            email=None,
            telegram_username=f"tg_{suffix}",
            telegram_id=str(tg_id),
        )
        phone_user_id = phone_user.id
        tg_user_id = tg_user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        clear_phone = await _admin_update_customer(
            client,
            headers,
            phone_user_id,
            _admin_update_payload(name=f"Phone only {suffix}"),
        )
        assert clear_phone.status_code == 303
        assert "error=" in clear_phone.headers.get("location", "")

        clear_tg = await _admin_update_customer(
            client,
            headers,
            tg_user_id,
            _admin_update_payload(name=name),
        )
        assert clear_tg.status_code == 303
        assert "error=" in clear_tg.headers.get("location", "")

    async with async_session_maker() as session:
        identity_svc = IdentityService(session)
        phone_user = await UserService(session).get_user(phone_user_id)
        tg_user = await UserService(session).get_user(tg_user_id)
        assert phone_user is not None and tg_user is not None
        assert await identity_svc.get_phone_e164_for_user(phone_user) == phone
        assert await identity_svc.get_telegram_id_for_user(tg_user) == tg_id


@pytest.mark.asyncio
async def test_admin_can_unbind_all_three_in_sequence(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    email = f"unbind-all-{suffix}@admin-forms.test"
    phone = f"+7958{suffix:07d}"
    tg_id = 9_500_000_000 + suffix
    name = f"Unbind all {suffix}"

    async with async_session_maker() as session:
        _, token = await create_admin_access_token(session, suffix + 97_000)
        user = await create_test_customer(
            session,
            name=name,
            email=email,
            telegram_username=f"tg_{suffix}",
            telegram_id=str(tg_id),
        )
        await IdentityService(session).admin_set_phone_for_user(user, phone)
        user_id = user.id

    headers = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
        follow_redirects=False,
    ) as client:
        clear_tg = await _admin_update_customer(
            client,
            headers,
            user_id,
            _admin_update_payload(name=name, email=email, login_phone=phone),
        )
        _assert_redirect_ok(clear_tg)

        clear_email = await _admin_update_customer(
            client,
            headers,
            user_id,
            _admin_update_payload(name=name, login_phone=phone),
        )
        _assert_redirect_ok(clear_email)

        clear_phone = await _admin_update_customer(
            client,
            headers,
            user_id,
            _admin_update_payload(name=name),
        )
        assert clear_phone.status_code == 303
        assert "error=" in clear_phone.headers.get("location", "")

    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        assert user is not None
        identity_svc = IdentityService(session)
        assert user.email is None
        assert await identity_svc.get_phone_e164_for_user(user) == phone
        assert await identity_svc.get_telegram_id_for_user(user) is None
        providers = {
            item.provider
            for item in await identity_svc.list_identities_for_user(user.id)
        }
        assert providers == {"phone"}
