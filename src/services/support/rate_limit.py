import logging

from redis.asyncio import Redis

from src.core.config import settings

logger = logging.getLogger(__name__)


class SupportRateLimiter:
    # Per-user throttle для создания обращений и сообщений в поддержку.
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    # Проверяет доступность Redis; при сбое лимит не применяется.
    async def _redis_ready(self) -> bool:
        try:
            await self.redis.ping()
            return True
        except Exception as exc:
            logger.warning("Redis недоступен — rate limit support пропущен: %s", exc)
            return False

    # Проверяет лимит перед create_ticket или add_message.
    async def assert_action_allowed(self, user_id: int, action: str) -> None:
        if not await self._redis_ready():
            return

        cooldown_key = f"support_rate:cooldown:{user_id}:{action}"
        if await self.redis.exists(cooldown_key):
            raise ValueError("Подождите перед повторной отправкой")

        user_key = f"support_rate:user:{user_id}:{action}"
        user_count = int(await self.redis.get(user_key) or 0)
        limit = (
            settings.SUPPORT_RATE_LIMIT_CREATE_PER_WINDOW
            if action == "create_ticket"
            else settings.SUPPORT_RATE_LIMIT_MESSAGE_PER_WINDOW
        )
        if user_count >= limit:
            raise ValueError("Слишком много обращений. Попробуйте позже")

    # Учитывает успешное действие клиента.
    async def record_action(self, user_id: int, action: str) -> None:
        if not await self._redis_ready():
            return

        cooldown_key = f"support_rate:cooldown:{user_id}:{action}"
        await self.redis.setex(
            cooldown_key,
            settings.SUPPORT_RATE_LIMIT_COOLDOWN_SECONDS,
            "1",
        )

        window = settings.SUPPORT_RATE_LIMIT_WINDOW_SECONDS
        user_key = f"support_rate:user:{user_id}:{action}"
        user_count = await self.redis.incr(user_key)
        if user_count == 1:
            await self.redis.expire(user_key, window)
