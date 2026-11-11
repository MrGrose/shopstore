from types import SimpleNamespace

import httpx
import pytest

from src.api.routers import auth as auth_router_module
from src.main import app
from src.models.user import User
from src.services.verification.phone.call_service import PhoneCallFlowState
from src.services.verification.phone.errors import PhoneCallConflictError

pytestmark = pytest.mark.integration


class _PhoneCallAuthService:
    channel = "flash_call"
    attempts = 0

    # Возвращает публичное состояние fake flow.
    def public_state(self, flow: PhoneCallFlowState) -> PhoneCallFlowState:
        return flow

    # Создаёт первый fake flow без обращения к provider.
    async def start(self, phone: str, client_ip: str | None = None):
        assert phone
        self.__class__.channel = "flash_call"
        self.__class__.attempts = 1
        return self._state(can_retry=True)

    # Возвращает текущее fake-состояние.
    async def status(self, flow_id: str):
        assert flow_id == "flow-1"
        return self._state(can_retry=self.attempts < 2)

    # Выполняет вторую попытку текущего fake-канала.
    async def retry(self, flow_id: str, client_ip: str | None = None):
        assert flow_id == "flow-1"
        self.__class__.attempts += 1
        return self._state(can_retry=False, next_channel=self._next_channel())

    # Переключает fake flow только после двух попыток.
    async def switch(self, flow_id: str, client_ip: str | None = None):
        assert flow_id == "flow-1"
        if self.attempts < 2:
            raise PhoneCallConflictError(
                "Сначала используйте доступные попытки текущего способа"
            )
        self.__class__.channel = self._next_channel()
        self.__class__.attempts = 1
        return self._state(can_retry=True)

    # Подтверждает fake-код.
    async def verify_code(self, flow_id: str, code: str) -> None:
        assert flow_id == "flow-1"
        assert code == "1234"

    # Возвращает следующий канал fake-каскада.
    def _next_channel(self) -> str:
        return {
            "flash_call": "voice_code",
            "voice_code": "verification_number",
        }[self.channel]

    # Собирает безопасное состояние fake flow.
    def _state(
        self,
        can_retry: bool,
        next_channel: str | None = None,
    ) -> PhoneCallFlowState:
        return PhoneCallFlowState(
            flow_id="flow-1",
            channel=self.channel,
            status="pending",
            expires_in=300,
            retry_after=0,
            can_retry=can_retry,
            call_started=True,
            next_channel=next_channel,
            verification_phone_number=(
                "+78005553968" if self.channel == "verification_number" else None
            ),
        )


class _PhoneCallLoginService:
    used = False

    # Принимает flow service так же, как production service.
    def __init__(self, flow_service: object | None = None) -> None:
        self.flow_service = flow_service

    # Завершает fake flow только один раз.
    async def complete(self, *args: object, **kwargs: object) -> SimpleNamespace:
        if self.__class__.used:
            raise PhoneCallConflictError("Телефон ещё не подтверждён")
        self.__class__.used = True
        user = User(id=101, email=None, name=None, avatar=None, role="buyer")
        return SimpleNamespace(
            access_token="test-token",
            user=user,
            is_new_user=True,
        )


@pytest.fixture(autouse=True)
def _mock_phone_call_services(monkeypatch):
    _PhoneCallAuthService.channel = "flash_call"
    _PhoneCallAuthService.attempts = 0
    _PhoneCallLoginService.used = False
    monkeypatch.setattr(
        auth_router_module,
        "PhoneCallAuthService",
        _PhoneCallAuthService,
    )
    monkeypatch.setattr(
        auth_router_module,
        "PhoneCallLoginService",
        _PhoneCallLoginService,
    )


# Проверяет ручной HTTP-каскад до verification number.
@pytest.mark.asyncio
async def test_manual_cascade_reaches_verification_number() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        started = await client.post("/auth/phone/start", json={"phone": "+79991234567"})
        early_switch = await client.post("/auth/phone/flow-1/switch")
        flash_retry = await client.post("/auth/phone/flow-1/retry")
        voice = await client.post("/auth/phone/flow-1/switch")
        voice_retry = await client.post("/auth/phone/flow-1/retry")
        verification = await client.post("/auth/phone/flow-1/switch")

    assert started.json()["channel"] == "flash_call"
    assert early_switch.status_code == 409
    assert flash_retry.json()["next_channel"] == "voice_code"
    assert voice.json()["channel"] == "voice_code"
    assert voice_retry.json()["next_channel"] == "verification_number"
    assert verification.json()["channel"] == "verification_number"
    assert verification.json()["verification_phone_number"] == "+78005553968"


# Проверяет одноразовое завершение подтверждённого flow.
@pytest.mark.asyncio
async def test_verified_flow_can_complete_only_once() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        first = await client.post("/auth/phone/flow-1/complete")
        second = await client.post("/auth/phone/flow-1/complete")

    assert first.status_code == 200
    assert first.json()["is_new_user"] is True
    assert second.status_code == 409
