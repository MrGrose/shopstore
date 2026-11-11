from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from src.models.user import User
from src.services.auth import phone as phone_auth_module
from src.services.auth.phone import PhoneCallLoginService


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        return None


class _FlowService:
    async def consume_verified(self, flow_id: str) -> SimpleNamespace:
        assert flow_id == "flow-1"
        return SimpleNamespace(phone_e164="+79991234567")


@pytest.mark.asyncio
async def test_complete_uses_existing_phone_auth_and_finalize(monkeypatch):
    session = object()
    user = User(id=7, email=None, name=None, avatar=None)

    class _PhoneAuthService:
        def __init__(self, received_session: object) -> None:
            assert received_session is session

        async def authenticate_by_phone(self, phone_e164: str):
            assert phone_e164 == "+79991234567"
            return user, True

    async def _finalize_login(
        received_session: object,
        received_user: User,
        request: Request,
        response: Response,
        referral_code: str | None = None,
    ):
        assert received_session is session
        assert received_user is user
        assert referral_code == "ref-code"
        return "access-token", user

    monkeypatch.setattr(
        phone_auth_module,
        "async_session_maker",
        lambda: _SessionContext(session),
    )
    monkeypatch.setattr(phone_auth_module, "PhoneAuthService", _PhoneAuthService)
    monkeypatch.setattr(phone_auth_module, "finalize_login", _finalize_login)

    request = Request({"type": "http", "headers": []})
    result = await PhoneCallLoginService(_FlowService()).complete(
        "flow-1",
        request,
        Response(),
        referral_code="ref-code",
    )

    assert result.access_token == "access-token"
    assert result.user is user
    assert result.is_new_user is True
