import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.integrations.sbp.client import SBPClient, _parse_expires_at
from src.integrations.sbp.errors import SBPApiError, SBPAuthError


def test_parse_expires_at_iso() -> None:
    parsed = _parse_expires_at("2026-06-27T12:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_expires_at_epoch() -> None:
    parsed = _parse_expires_at("1893456000")
    assert parsed == datetime.fromtimestamp(1893456000, tz=timezone.utc)


@pytest.mark.asyncio
async def test_create_order_payload_and_x_req_id() -> None:
    client = SBPClient(
        login="u",
        password="p",
        tsp_id=1,
        api_base_url="https://api.test/v1",
        auth_base_url="https://auth.test/v1",
    )
    client._get_access_token = AsyncMock(  # type: ignore[method-assign]
        return_value="jwt-token",
    )
    captured: dict[str, object] = {}

    async def fake_api_request(
        method, path, json_body=None, x_req_id=None, retry_auth=True
    ):
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["x_req_id"] = x_req_id
        return {
            "success": True,
            "order": {"id": "prov-1", "status": "CREATED"},
        }

    client._api_request = fake_api_request  # type: ignore[method-assign]
    result = await client.create_order(
        merchant_order_id="shopstore-1",
        payment_amount_minor=12345,
        description="test",
        callback_url="https://cb.test/callback",
        x_req_id="shopstore-order-1",
    )
    assert result["id"] == "prov-1"
    assert captured["json_body"] == {
        "merchantOrderId": "shopstore-1",
        "paymentAmount": 12345,
        "orderCurrency": "RUB",
        "paymentCurrency": "RUB",
        "tspId": 1,
        "description": "test",
        "callbackUrl": "https://cb.test/callback",
    }
    assert captured["x_req_id"] == "shopstore-order-1"


@pytest.mark.asyncio
async def test_api_request_retries_after_401() -> None:
    client = SBPClient(login="u", password="p")
    token_calls = {"count": 0}
    api_calls = {"count": 0}

    async def fake_get_token():
        token_calls["count"] += 1
        return f"token-{token_calls['count']}"

    client._get_access_token = fake_get_token  # type: ignore[method-assign]
    client._invalidate_token_cache = AsyncMock()  # type: ignore[method-assign]

    class FakeResponse:
        def __init__(self, status: int):
            self.status = status

        async def read(self):
            return json.dumps(
                {"success": True, "order": {"status": "CREATED"}}
            ).encode()

    class FakeCtx:
        def __init__(self, status: int):
            self.response = FakeResponse(status)

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *args):
            return None

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def request(self, *args, **kwargs):
            api_calls["count"] += 1
            status = 401 if api_calls["count"] == 1 else 200
            return FakeCtx(status)

    with patch("src.integrations.sbp.client.aiohttp.ClientSession", FakeSession):
        data = await client._api_request(
            "GET",
            "/status/1",
            x_req_id="x1",
            retry_auth=True,
        )
    assert data["success"] is True
    assert token_calls["count"] == 2
    assert api_calls["count"] == 2


@pytest.mark.asyncio
async def test_login_missing_token_raises_auth_error() -> None:
    client = SBPClient(login="u", password="p", auth_base_url="https://auth.test/v1")

    class Resp:
        status = 200

        async def json(self, content_type=None):
            return {"success": True, "description": "login success"}

    class Ctx:
        async def __aenter__(self):
            return Resp()

        async def __aexit__(self, *args):
            return None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            return Ctx()

    with patch("src.integrations.sbp.client.aiohttp.ClientSession", Session):
        with pytest.raises(SBPAuthError):
            await client._login()


@pytest.mark.asyncio
async def test_get_status_requires_status_field() -> None:
    client = SBPClient()
    client._api_request = AsyncMock(  # type: ignore[method-assign]
        return_value={"success": True, "order": {}},
    )
    with pytest.raises(SBPApiError):
        await client.get_status("1")
