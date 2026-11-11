import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from src.core.config import settings
from src.core.redis import async_redis
from src.integrations.zvonok.provider import (
    PhoneCallProviderError,
    ProviderCallStatus,
    ProviderStartResult,
    ZvonokPhoneProvider,
)
from src.services.verification.phone.call_flow_store import (
    PhoneAuthChannel,
    PhoneCallFlow,
    PhoneCallFlowStatus,
    PhoneCallFlowStore,
)
from src.services.verification.phone.errors import (
    PhoneCallConflictError,
    PhoneCallInputError,
    PhoneCallUnavailableError,
)
from src.utils.phone import normalize_ru_mobile_phone


class PhoneCallProvider(Protocol):
    async def start(
        self,
        channel: PhoneAuthChannel,
        phone_e164: str,
        code: str | None = None,
    ) -> ProviderStartResult: ...

    async def get_status(self, external_id: str) -> ProviderCallStatus: ...


@dataclass(frozen=True, slots=True)
class PhoneCallFlowState:
    flow_id: str
    channel: PhoneAuthChannel
    status: PhoneCallFlowStatus
    expires_in: int
    retry_after: int
    can_retry: bool
    call_started: bool
    next_channel: PhoneAuthChannel | None
    verification_phone_number: str | None


class PhoneCallAuthService:
    # Управляет ручным каскадом звонков и состоянием одного flow.
    def __init__(
        self,
        provider: PhoneCallProvider | None = None,
        store: PhoneCallFlowStore | None = None,
    ) -> None:
        self.provider = provider or ZvonokPhoneProvider()
        self.store = store or PhoneCallFlowStore(async_redis())
        self.channels = settings.phone_auth_channels

    # Возвращает безопасное состояние каскада для внешнего клиента.
    def public_state(self, flow: PhoneCallFlow) -> PhoneCallFlowState:
        now = datetime.now(tz=UTC)
        current_index = self.channels.index(flow.current_channel)
        attempts = flow.channel_attempts.get(flow.current_channel, 0)
        can_switch = (
            attempts >= settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL
            or flow.provider_error
        )
        next_channel = (
            cast(PhoneAuthChannel, self.channels[current_index + 1])
            if can_switch and current_index + 1 < len(self.channels)
            else None
        )
        retry_after = 0
        if flow.retry_available_at:
            retry_after = max(
                0,
                int((flow.retry_available_at - now).total_seconds()),
            )
        can_retry = (
            flow.status == "pending"
            and attempts < settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL
            and not flow.provider_error
        )
        return PhoneCallFlowState(
            flow_id=flow.flow_id,
            channel=flow.current_channel,
            status=flow.status,
            expires_in=max(0, int((flow.expires_at - now).total_seconds())),
            retry_after=retry_after,
            can_retry=can_retry,
            call_started=bool(flow.provider_call_id),
            next_channel=next_channel,
            verification_phone_number=(
                settings.ZVONOK_VERIFICATION_PHONE_NUMBER
                if flow.current_channel == "verification_number"
                else None
            ),
        )

    # Создаёт flow и запускает первый включённый канал.
    async def start(self, phone: str, client_ip: str | None = None) -> PhoneCallFlow:
        self._assert_enabled()
        try:
            phone_e164 = normalize_ru_mobile_phone(phone)
        except ValueError as exc:
            raise PhoneCallInputError(str(exc)) from exc
        existing = await self.store.active_flow(phone_e164)
        if existing is not None:
            return existing
        now = datetime.now(tz=UTC)
        flow = PhoneCallFlow(
            flow_id=str(uuid.uuid4()),
            phone_e164=phone_e164,
            current_channel=self.channels[0],
            created_at=now,
            expires_at=now + timedelta(seconds=settings.PHONE_CALL_FLOW_TTL_SECONDS),
        )
        if not await self.store.claim_active(phone_e164, flow.flow_id):
            existing = await self.store.active_flow(phone_e164)
            if existing is not None:
                return existing
            raise PhoneCallConflictError("Подтверждение уже запущено")
        try:
            await self._launch(flow, client_ip)
        except RuntimeError:
            if flow.provider_error:
                await self._fail_if_last_channel(flow)
                return flow
            await self.store.release_active(flow)
            raise
        return flow

    # Повторно запускает только текущий канал после cooldown.
    async def retry(self, flow_id: str, client_ip: str | None = None) -> PhoneCallFlow:
        flow = await self._require_flow(flow_id)
        self._assert_pending(flow)
        attempts = flow.channel_attempts.get(flow.current_channel, 0)
        if attempts >= settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL:
            raise PhoneCallConflictError("Попытки этого способа закончились")
        if flow.retry_available_at and flow.retry_available_at > datetime.now(tz=UTC):
            raise PhoneCallConflictError("Подождите перед повторным звонком")
        try:
            await self._launch(flow, client_ip)
        except RuntimeError:
            if not flow.provider_error:
                raise
            await self._fail_if_last_channel(flow)
        return flow

    # Переключает flow только на следующий включённый канал.
    async def switch(self, flow_id: str, client_ip: str | None = None) -> PhoneCallFlow:
        flow = await self._require_flow(flow_id)
        self._assert_pending(flow)
        attempts = flow.channel_attempts.get(flow.current_channel, 0)
        if (
            attempts < settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL
            and not flow.provider_error
        ):
            raise PhoneCallConflictError(
                "Сначала используйте доступные попытки текущего способа"
            )
        current_index = self.channels.index(flow.current_channel)
        if current_index + 1 >= len(self.channels):
            raise PhoneCallConflictError("Других способов подтверждения нет")
        flow.current_channel = cast(
            PhoneAuthChannel,
            self.channels[current_index + 1],
        )
        flow.provider_call_id = None
        flow.code_hmac = None
        flow.verify_attempts = 0
        flow.retry_available_at = None
        flow.provider_error = False
        try:
            await self._launch(flow, client_ip)
        except RuntimeError:
            if not flow.provider_error:
                raise
            await self._fail_if_last_channel(flow)
        return flow

    # Проверяет пользовательский код текущего звонка.
    async def verify_code(self, flow_id: str, code: str) -> PhoneCallFlow:
        flow = await self._require_flow(flow_id)
        self._assert_pending(flow)
        if flow.current_channel == "verification_number" or not flow.code_hmac:
            raise PhoneCallConflictError("Для этого способа код не используется")
        if flow.verify_attempts >= settings.PHONE_CALL_VERIFY_MAX_ATTEMPTS:
            raise PhoneCallConflictError("Слишком много неверных кодов")
        flow.verify_attempts += 1
        supplied = self._code_hmac(flow, code.strip())
        if not hmac.compare_digest(supplied, flow.code_hmac):
            await self.store.save(flow)
            raise PhoneCallConflictError("Неверный код")
        flow.status = "verified"
        flow.code_hmac = None
        await self.store.save(flow)
        return flow

    # Возвращает flow и обновляет polling-статус проверочного номера.
    async def status(self, flow_id: str) -> PhoneCallFlow:
        flow = await self._require_flow(flow_id)
        if (
            flow.status == "pending"
            and flow.current_channel == "verification_number"
            and flow.provider_call_id
        ):
            call_id = flow.provider_call_id
            call_version = flow.active_call_version
            try:
                provider_status = await self.provider.get_status(call_id)
            except PhoneCallProviderError as exc:
                raise PhoneCallUnavailableError(
                    "Не удалось проверить состояние звонка"
                ) from exc
            current = await self._require_flow(flow_id)
            if (
                current.provider_call_id != call_id
                or current.active_call_version != call_version
            ):
                return current
            if provider_status == "verified":
                current.status = "verified"
            elif provider_status in {"failed", "expired"}:
                current.provider_call_id = None
                attempts = current.channel_attempts.get(current.current_channel, 0)
                if attempts >= settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL:
                    current.status = "failed"
            await self.store.save(current)
            return current
        return flow

    # Атомарно помечает подтверждённый flow использованным для login finalize.
    async def consume_verified(self, flow_id: str) -> PhoneCallFlow:
        flow = await self.store.consume_verified(flow_id)
        if flow is None:
            raise PhoneCallConflictError("Телефон ещё не подтверждён")
        await self.store.release_active(flow)
        return flow

    # Запускает provider и сохраняет только HMAC кода.
    async def _launch(self, flow: PhoneCallFlow, client_ip: str | None) -> None:
        if not await self.store.claim_launch(flow.flow_id):
            raise PhoneCallConflictError("Другой звонок уже запускается")
        try:
            await self._launch_claimed(flow, client_ip)
        except Exception:
            await self.store.release_launch(flow.flow_id)
            raise

    # Запускает provider внутри блокировки одного активного запроса.
    async def _launch_claimed(self, flow: PhoneCallFlow, client_ip: str | None) -> None:
        await self.store.assert_rate_allowed(flow.phone_e164, client_ip)
        if not await self.store.reserve_provider_request():
            raise PhoneCallConflictError("Слишком много запросов. Попробуйте позже")
        channel = flow.current_channel
        attempts = flow.channel_attempts.get(channel, 0)
        if attempts >= settings.PHONE_CALL_MAX_REQUESTS_PER_CHANNEL:
            raise PhoneCallConflictError("Попытки этого способа закончились")
        code = f"{secrets.randbelow(10000):04d}" if channel == "voice_code" else None
        flow.channel_attempts[channel] = attempts + 1
        flow.active_call_version += 1
        flow.provider_error = False
        try:
            result = await self.provider.start(channel, flow.phone_e164, code)
        except PhoneCallProviderError:
            flow.provider_error = True
            flow.provider_call_id = None
            flow.code_hmac = None
            await self.store.save(flow)
            raise PhoneCallUnavailableError("Звонок временно недоступен")
        provider_code = result.code if channel == "flash_call" else code
        if channel != "verification_number" and not provider_code:
            flow.provider_error = True
            await self.store.save(flow)
            raise PhoneCallUnavailableError("Провайдер не вернул код подтверждения")
        flow.provider_call_id = result.external_id
        flow.code_hmac = self._code_hmac(flow, provider_code) if provider_code else None
        flow.verify_attempts = 0
        cooldown_seconds = (
            settings.PHONE_VERIFICATION_NUMBER_COOLDOWN_SECONDS
            if channel == "verification_number"
            else settings.PHONE_CALL_COOLDOWN_SECONDS
        )
        flow.retry_available_at = datetime.now(tz=UTC) + timedelta(
            seconds=cooldown_seconds
        )
        await self.store.record_request(flow.phone_e164, client_ip)
        await self.store.save(flow)
        code = None
        provider_code = None

    # Строит HMAC кода с привязкой к flow и версии звонка.
    def _code_hmac(self, flow: PhoneCallFlow, code: str) -> str:
        payload = f"{flow.flow_id}:{flow.active_call_version}:{code}".encode()
        return hmac.new(settings.AUTH_SECRET.encode(), payload, "sha256").hexdigest()

    # Загружает существующий flow или возвращает нейтральную ошибку.
    async def _require_flow(self, flow_id: str) -> PhoneCallFlow:
        flow = await self.store.load(flow_id)
        if flow is None:
            raise PhoneCallConflictError("Подтверждение не найдено или устарело")
        return flow

    # Проверяет, что flow ещё принимает действия.
    def _assert_pending(self, flow: PhoneCallFlow) -> None:
        if flow.status != "pending":
            raise PhoneCallConflictError("Подтверждение уже завершено")

    # Проверяет feature flag и список каналов.
    def _assert_enabled(self) -> None:
        if not settings.PHONE_AUTH_ENABLED or not self.channels:
            raise PhoneCallUnavailableError("Вход по телефону временно недоступен")

    # Завершает flow, если provider сломался на последнем канале.
    async def _fail_if_last_channel(self, flow: PhoneCallFlow) -> None:
        if self.channels.index(flow.current_channel) + 1 < len(self.channels):
            return
        flow.status = "failed"
        await self.store.save(flow)
