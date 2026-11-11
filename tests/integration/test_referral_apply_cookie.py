import httpx
import pytest

from src.core.security import create_access_token
from src.core.user_roles import UserRole
from src.main import app
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService

pytestmark = pytest.mark.integration

CLEAR_STATUSES = (
    "attributed",
    "already_attributed",
    "self_referral",
    "attribution_locked",
    "not_eligible",
)


def _set_cookie_headers(response: httpx.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


def _referral_cookie_headers(headers: list[str]) -> list[str]:
    return [header for header in headers if header.lower().startswith("referral_code=")]


def _assert_referral_cookie_cleared(headers: list[str], *, secure: bool) -> None:
    referral_headers = _referral_cookie_headers(headers)
    assert len(referral_headers) == 1
    header = referral_headers[0].lower()
    assert "path=/" in header
    assert "samesite=lax" in header
    assert "max-age=0" in header
    if secure:
        assert "secure" in header
    else:
        assert "secure" not in header


def _assert_referral_cookie_not_cleared(headers: list[str]) -> None:
    assert _referral_cookie_headers(headers) == []


async def _post_apply(
    client: httpx.AsyncClient,
    token: str,
    cookie_value: str | None,
) -> httpx.Response:
    if cookie_value:
        client.cookies.set("referral_code", cookie_value)
    else:
        client.cookies.delete("referral_code")
    return await client.post(
        "/users/me/referrer/apply",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.asyncio
async def test_apply_invalid_code_keeps_referral_cookie(
    merge_unique_suffix: int,
) -> None:
    suffix = merge_unique_suffix % 1_000_000
    token = ""
    invalid_code = "not-a-real-code"

    async with async_session_maker() as session:
        buyer = await UserService(session).register_user_by_phone(f"+7970{suffix:07d}")
        token = create_access_token(buyer.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await _post_apply(client, token, invalid_code)

    assert response.status_code == 200
    assert response.json()["status"] == "invalid_code"
    _assert_referral_cookie_not_cleared(_set_cookie_headers(response))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", CLEAR_STATUSES)
async def test_apply_clears_referral_cookie_for_final_statuses(
    merge_unique_suffix: int,
    status: str,
) -> None:
    suffix = (merge_unique_suffix + hash(status) % 1_000_000) % 1_000_000
    token = ""
    cookie_value = "cookie-code-for-apply"

    async with async_session_maker() as session:
        user_svc = UserService(session)
        ref_svc = ReferralService(session)

        if status == "attributed":
            partner = await user_svc.register_user_by_phone(f"+7971{suffix:07d}")
            partner = await ref_svc.ensure_referral_code(partner)
            buyer = await user_svc.register_user_by_phone(f"+7972{suffix:07d}")
            cookie_value = partner.referral_code or cookie_value
            token = create_access_token(buyer.id)
        elif status == "already_attributed":
            partner = await user_svc.register_user_by_phone(f"+7973{suffix:07d}")
            partner = await ref_svc.ensure_referral_code(partner)
            buyer = await user_svc.register_user_by_phone(f"+7974{suffix:07d}")
            buyer.referrer_id = partner.id
            session.add(buyer)
            await session.commit()
            token = create_access_token(buyer.id)
        elif status == "self_referral":
            buyer = await user_svc.register_user_by_phone(f"+7975{suffix:07d}")
            buyer = await ref_svc.ensure_referral_code(buyer)
            cookie_value = buyer.referral_code or cookie_value
            token = create_access_token(buyer.id)
        elif status == "attribution_locked":
            buyer = await user_svc.register_user_by_phone(f"+7976{suffix:07d}")
            buyer.referral_attribution_locked = True
            session.add(buyer)
            await session.commit()
            token = create_access_token(buyer.id)
        elif status == "not_eligible":
            admin = User(
                email=f"admin-apply-{suffix}@test.local",
                name=f"Admin {suffix}",
                role=UserRole.ADMIN.value,
            )
            session.add(admin)
            await session.commit()
            token = create_access_token(admin.id)
        else:
            raise AssertionError(f"unexpected status fixture: {status}")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await _post_apply(client, token, cookie_value)

    assert response.status_code == 200
    assert response.json()["status"] == status
    _assert_referral_cookie_cleared(_set_cookie_headers(response), secure=False)
