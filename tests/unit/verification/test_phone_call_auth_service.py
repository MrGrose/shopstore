from datetime import UTC, datetime

import pytest

from src.core.config import settings
from src.integrations.zvonok.provider import ProviderStartResult
from src.services.verification.phone.call_service import PhoneCallAuthService


class _Provider:
    def __init__(self) -> None:
        self.starts: list[tuple[str, str | None]] = []
        self.status_value = "pending"

    async def start(self, channel: str, phone_e164: str, code: str | None = None):
        self.starts.append((channel, code))
        returned_code = "4321" if channel == "flash_call" else None
        return ProviderStartResult(
            external_id=f"call-{len(self.starts)}",
            code=returned_code,
        )

    async def get_status(self, external_id: str):
        return self.status_value


class _Store:
    def __init__(self) -> None:
        self.flows = {}
        self.active = {}

    async def active_flow(self, phone_e164: str):
        flow_id = self.active.get(phone_e164)
        return self.flows.get(flow_id)

    async def claim_active(self, phone_e164: str, flow_id: str) -> bool:
        if phone_e164 in self.active:
            return False
        self.active[phone_e164] = flow_id
        return True

    async def release_active(self, flow) -> None:
        self.active.pop(flow.phone_e164, None)

    async def claim_launch(self, flow_id: str) -> bool:
        return True

    async def release_launch(self, flow_id: str) -> None:
        return None

    async def save(self, flow) -> None:
        self.flows[flow.flow_id] = flow.model_copy(deep=True)

    async def load(self, flow_id: str):
        flow = self.flows.get(flow_id)
        return flow.model_copy(deep=True) if flow else None

    async def assert_rate_allowed(self, phone_e164: str, client_ip: str | None):
        return None

    async def record_request(self, phone_e164: str, client_ip: str | None):
        return None

    async def reserve_provider_request(self) -> bool:
        return True

    async def consume_verified(self, flow_id: str):
        flow = self.flows.get(flow_id)
        if not flow or flow.status != "verified":
            return None
        original = flow.model_copy(deep=True)
        flow.status = "used"
        return original


@pytest.fixture
def call_service(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "PHONE_CALL_COOLDOWN_SECONDS", 0)
    provider = _Provider()
    store = _Store()
    service = PhoneCallAuthService(provider=provider, store=store)
    service.channels = ["flash_call", "voice_code", "verification_number"]
    return service, provider, store


@pytest.mark.asyncio
async def test_cascade_requires_two_requests_before_manual_switch(call_service):
    service, provider, _ = call_service
    flow = await service.start("+7 999 123-45-67")
    assert provider.starts == [("flash_call", None)]
    assert flow.code_hmac
    assert "4321" not in flow.model_dump_json()

    with pytest.raises(ValueError, match="доступные попытки"):
        await service.switch(flow.flow_id)

    flow.retry_available_at = datetime.now(tz=UTC)
    await service.store.save(flow)
    flow = await service.retry(flow.flow_id)
    assert flow.channel_attempts["flash_call"] == 2
    flow = await service.switch(flow.flow_id)
    assert flow.current_channel == "voice_code"
    assert provider.starts[-1][0] == "voice_code"
    assert provider.starts[-1][1] is not None


@pytest.mark.asyncio
async def test_wrong_code_does_not_create_new_provider_request(call_service):
    service, provider, _ = call_service
    flow = await service.start("+79991234567")
    with pytest.raises(ValueError, match="Неверный код"):
        await service.verify_code(flow.flow_id, "0000")
    assert len(provider.starts) == 1


@pytest.mark.asyncio
async def test_old_verification_number_result_cannot_verify_new_call(call_service):
    service, provider, store = call_service
    flow = await service.start("+79991234567")
    flow.current_channel = "verification_number"
    flow.provider_call_id = "old-call"
    flow.active_call_version = 3
    await store.save(flow)
    provider.status_value = "verified"

    original_get_status = provider.get_status

    async def replace_call(external_id: str):
        current = await store.load(flow.flow_id)
        current.provider_call_id = "new-call"
        current.active_call_version = 4
        await store.save(current)
        return await original_get_status(external_id)

    provider.get_status = replace_call
    current = await service.status(flow.flow_id)
    assert current.status == "pending"
    assert current.provider_call_id == "new-call"


@pytest.mark.asyncio
async def test_verified_flow_is_consumed_once(call_service):
    service, _, store = call_service
    flow = await service.start("+79991234567")
    flow.status = "verified"
    await store.save(flow)
    consumed = await service.consume_verified(flow.flow_id)
    assert consumed.phone_e164 == "+79991234567"
    with pytest.raises(ValueError, match="ещё не подтверждён"):
        await service.consume_verified(flow.flow_id)


@pytest.mark.asyncio
async def test_verification_number_has_two_minute_wait(call_service, monkeypatch):
    service, _, store = call_service
    monkeypatch.setattr(settings, "PHONE_VERIFICATION_NUMBER_COOLDOWN_SECONDS", 120)
    flow = await service.start("+79991234567")
    flow.current_channel = "verification_number"
    flow.provider_call_id = None
    flow.code_hmac = None
    flow.retry_available_at = None
    await store.save(flow)

    await service._launch(flow, None)

    assert flow.retry_available_at is not None
    remaining = (flow.retry_available_at - datetime.now(tz=UTC)).total_seconds()
    assert 119 <= remaining <= 120


@pytest.mark.asyncio
async def test_public_state_contains_cascade_decisions_without_private_data(
    call_service,
):
    service, _, store = call_service
    flow = await service.start("+79991234567")
    flow.channel_attempts["flash_call"] = 2
    await store.save(flow)

    state = service.public_state(flow)

    assert state.channel == "flash_call"
    assert state.can_retry is False
    assert state.next_channel == "voice_code"
    assert state.call_started is True
    assert state.verification_phone_number is None
    assert not hasattr(state, "phone_e164")
    assert not hasattr(state, "code_hmac")


@pytest.mark.asyncio
async def test_full_cascade_reaches_verification_number_manually(call_service):
    service, provider, store = call_service
    flow = await service.start("+79991234567")

    flow.retry_available_at = datetime.now(tz=UTC)
    await store.save(flow)
    flow = await service.retry(flow.flow_id)
    flow = await service.switch(flow.flow_id)

    flow.retry_available_at = datetime.now(tz=UTC)
    await store.save(flow)
    flow = await service.retry(flow.flow_id)
    flow = await service.switch(flow.flow_id)

    assert flow.current_channel == "verification_number"
    assert [channel for channel, _ in provider.starts] == [
        "flash_call",
        "flash_call",
        "voice_code",
        "voice_code",
        "verification_number",
    ]


@pytest.mark.asyncio
async def test_disabled_flash_call_is_excluded(monkeypatch):
    monkeypatch.setattr(settings, "PHONE_AUTH_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "PHONE_AUTH_CHANNEL_ORDER",
        "flash_call,voice_code,verification_number",
    )
    monkeypatch.setattr(settings, "PHONE_FLASH_CALL_ENABLED", False)
    monkeypatch.setattr(settings, "PHONE_VOICE_CODE_ENABLED", True)
    monkeypatch.setattr(settings, "PHONE_VERIFICATION_NUMBER_ENABLED", True)
    provider = _Provider()
    service = PhoneCallAuthService(provider=provider, store=_Store())

    flow = await service.start("+79991234567")

    assert flow.current_channel == "voice_code"
    assert provider.starts[0][0] == "voice_code"
