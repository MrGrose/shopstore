import httpx
import pytest

from src.core.security import create_access_token
from src.main import app
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from tests.integration.helpers.order_admin import (
    create_admin_access_token,
    create_telegram_user,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_referral_me_returns_stats_for_buyer(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix
    token = ""

    async with async_session_maker() as session:
        buyer = await create_telegram_user(session, suffix)
        buyer = await ReferralService(session).ensure_referral_code(buyer)
        await session.commit()
        token = create_access_token(buyer.id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/referral/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["referral_code"]
    assert "PS-" not in body["referral_code"]
    assert body["referral_link"]
    assert body["commission_percent_source"] in ("global", "individual", "disabled")
    assert isinstance(body["recent_earnings"], list)
    assert body["invited_count"] >= 0
    assert body["orders_count"] >= 0


@pytest.mark.asyncio
async def test_referral_me_forbidden_for_admin(merge_unique_suffix: int) -> None:
    suffix = merge_unique_suffix

    async with async_session_maker() as session:
        _admin_id, token = await create_admin_access_token(session, suffix)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        response = await client.get(
            "/referral/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
