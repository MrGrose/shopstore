import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings

logger = logging.getLogger(__name__)


class PhoneRateLimiter:
    # Rate limit и cooldown для phone send/verify.
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # Проверяет доступность Redis; при сбое лимит не применяется.
    async def _redis_ready(self) -> bool:
        try:
            await self.redis.ping()
            return True
        except RedisError as exc:
            logger.warning(
                "Redis недоступен — phone rate limit пропущен: %s",
                exc,
            )
            return False

    # Проверяет лимиты перед отправкой кода.
    async def assert_send_allowed(self, phone_e164: str, client_ip: str | None) -> None:
        if not await self._redis_ready():
            return

        cooldown_key = f"phone_verify_rate:cooldown:{phone_e164}"
        if await self.redis.exists(cooldown_key):
            raise ValueError("Подождите перед повторной отправкой кода")

        phone_key = f"phone_verify_rate:phone:{phone_e164}"
        phone_count = int(await self.redis.get(phone_key) or 0)
        if phone_count >= settings.PHONE_LOGIN_RATE_LIMIT_PHONE:
            raise ValueError("Слишком много запросов. Попробуйте позже")

        if client_ip:
            ip_key = f"phone_verify_rate:ip:{client_ip}"
            ip_count = int(await self.redis.get(ip_key) or 0)
            if ip_count >= settings.PHONE_LOGIN_RATE_LIMIT_IP:
                raise ValueError("Слишком много запросов. Попробуйте позже")

        global_key = "phone_verify_rate:global:send"
        global_count = int(await self.redis.get(global_key) or 0)
        if global_count >= settings.PHONE_LOGIN_GLOBAL_SEND_MAX:
            raise ValueError("Сервис временно недоступен. Попробуйте позже")

    # Учитывает успешную отправку кода.
    async def record_send(self, phone_e164: str, client_ip: str | None) -> None:
        if not await self._redis_ready():
            return

        cooldown_key = f"phone_verify_rate:cooldown:{phone_e164}"
        await self.redis.setex(
            cooldown_key,
            settings.PHONE_LOGIN_SEND_COOLDOWN_SECONDS,
            "1",
        )

        window = settings.PHONE_LOGIN_RATE_LIMIT_WINDOW_SECONDS
        phone_key = f"phone_verify_rate:phone:{phone_e164}"
        phone_count = await self.redis.incr(phone_key)
        if phone_count == 1:
            await self.redis.expire(phone_key, window)

        if client_ip:
            ip_key = f"phone_verify_rate:ip:{client_ip}"
            ip_count = await self.redis.incr(ip_key)
            if ip_count == 1:
                await self.redis.expire(ip_key, window)

        global_key = "phone_verify_rate:global:send"
        global_count = await self.redis.incr(global_key)
        if global_count == 1:
            await self.redis.expire(
                global_key,
                settings.PHONE_LOGIN_GLOBAL_SEND_WINDOW_SECONDS,
            )

    # Проверяет лимит попыток verify на сессию.
    def assert_verify_attempts_allowed(self, attempts: int) -> None:
        if attempts >= settings.PHONE_LOGIN_VERIFY_MAX_ATTEMPTS:
            raise ValueError("Слишком много попыток. Запросите новый код")
