import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from src.core.config import settings
from src.services.verification.phone.errors import (
    PhoneCallConflictError,
    PhoneCallUnavailableError,
)

PhoneAuthChannel = Literal["flash_call", "voice_code", "verification_number"]
PhoneCallFlowStatus = Literal[
    "pending", "verified", "failed", "expired", "cancelled", "used"
]


class PhoneCallFlow(BaseModel):
    flow_id: str
    phone_e164: str
    current_channel: PhoneAuthChannel
    status: PhoneCallFlowStatus = "pending"
    channel_attempts: dict[str, int] = Field(default_factory=dict)
    provider_call_id: str | None = None
    active_call_version: int = 0
    code_hmac: str | None = None
    verify_attempts: int = 0
    created_at: datetime
    expires_at: datetime
    retry_available_at: datetime | None = None
    provider_error: bool = False


class PhoneCallFlowStore:
    # Хранит весь каскад одного phone login в Redis.
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # Строит Redis-ключ flow.
    def flow_key(self, flow_id: str) -> str:
        return f"auth:phone:call-flow:{flow_id}"

    # Хеширует телефон или IP для Redis-ключей.
    def subject_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    # Возвращает ключ активного flow телефона.
    def active_key(self, phone_e164: str) -> str:
        return f"auth:phone:active:{self.subject_hash(phone_e164)}"

    # Ставит короткую блокировку на запуск одного provider call.
    async def claim_launch(self, flow_id: str) -> bool:
        return bool(
            await self.redis.set(
                f"auth:phone:launch:{flow_id}",
                "1",
                ex=settings.PHONE_CALL_COOLDOWN_SECONDS,
                nx=True,
            )
        )

    # Снимает блокировку запуска после сохранения результата.
    async def release_launch(self, flow_id: str) -> None:
        await self.redis.delete(f"auth:phone:launch:{flow_id}")

    # Сохраняет flow с общим TTL.
    async def save(self, flow: PhoneCallFlow) -> None:
        ttl = max(1, int((flow.expires_at - datetime.now(tz=UTC)).total_seconds()))
        await self.redis.setex(self.flow_key(flow.flow_id), ttl, flow.model_dump_json())

    # Загружает flow и проверяет срок жизни.
    async def load(self, flow_id: str) -> PhoneCallFlow | None:
        raw = await self.redis.get(self.flow_key(flow_id))
        if not raw:
            return None
        flow = PhoneCallFlow.model_validate_json(raw)
        if flow.expires_at <= datetime.now(tz=UTC) and flow.status == "pending":
            flow.status = "expired"
        return flow

    # Привязывает телефон к одному активному flow.
    async def claim_active(self, phone_e164: str, flow_id: str) -> bool:
        return bool(
            await self.redis.set(
                self.active_key(phone_e164),
                flow_id,
                ex=settings.PHONE_CALL_FLOW_TTL_SECONDS,
                nx=True,
            )
        )

    # Возвращает активный flow телефона, если он ещё существует.
    async def active_flow(self, phone_e164: str) -> PhoneCallFlow | None:
        key = self.active_key(phone_e164)
        flow_id = await self.redis.get(key)
        if not flow_id:
            return None
        flow = await self.load(str(flow_id))
        if flow is None or flow.status in {"failed", "expired", "cancelled", "used"}:
            await self.redis.delete(key)
            return None
        return flow

    # Снимает признак активного flow после завершения.
    async def release_active(self, flow: PhoneCallFlow) -> None:
        key = self.active_key(flow.phone_e164)
        if await self.redis.get(key) == flow.flow_id:
            await self.redis.delete(key)

    # Атомарно меняет verified на used и возвращает исходный flow.
    async def consume_verified(self, flow_id: str) -> PhoneCallFlow | None:
        script = """
        local raw = redis.call('GET', KEYS[1])
        if not raw then return nil end
        local record = cjson.decode(raw)
        if record.status ~= 'verified' then return nil end
        record.status = 'used'
        local ttl = redis.call('TTL', KEYS[1])
        if ttl <= 0 then return nil end
        redis.call('SETEX', KEYS[1], ttl, cjson.encode(record))
        return raw
        """
        raw = await self.redis.eval(script, 1, self.flow_key(flow_id))
        if not raw:
            return None
        return PhoneCallFlow.model_validate_json(raw)

    # Проверяет общие phone/IP limits до обращения к provider.
    async def assert_rate_allowed(self, phone_e164: str, client_ip: str | None) -> None:
        subjects = [
            (
                "phone",
                self.subject_hash(phone_e164),
                settings.PHONE_CALL_RATE_LIMIT_PHONE,
            )
        ]
        if client_ip:
            subjects.append(
                ("ip", self.subject_hash(client_ip), settings.PHONE_CALL_RATE_LIMIT_IP)
            )
        for kind, subject, limit in subjects:
            count = int(await self.redis.get(f"auth:phone:rate:{kind}:{subject}") or 0)
            if count >= limit:
                raise PhoneCallConflictError("Слишком много запросов. Попробуйте позже")
        global_count = int(await self.redis.get("auth:phone:rate:global") or 0)
        if global_count >= settings.PHONE_LOGIN_GLOBAL_SEND_MAX:
            raise PhoneCallUnavailableError(
                "Сервис временно недоступен. Попробуйте позже"
            )

    # Резервирует один запрос в лимите Zvonok 20 rps.
    async def reserve_provider_request(self) -> bool:
        key = "auth:phone:rate:provider-second"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 1)
        return count <= 20

    # Учитывает новый платный запрос звонка.
    async def record_request(self, phone_e164: str, client_ip: str | None) -> None:
        subjects = [("phone", self.subject_hash(phone_e164))]
        if client_ip:
            subjects.append(("ip", self.subject_hash(client_ip)))
        for kind, subject in subjects:
            key = f"auth:phone:rate:{kind}:{subject}"
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(
                    key, settings.PHONE_LOGIN_RATE_LIMIT_WINDOW_SECONDS
                )
        global_key = "auth:phone:rate:global"
        global_count = await self.redis.incr(global_key)
        if global_count == 1:
            await self.redis.expire(
                global_key,
                settings.PHONE_LOGIN_GLOBAL_SEND_WINDOW_SECONDS,
            )
