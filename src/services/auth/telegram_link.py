import secrets

from redis.asyncio import Redis


class TelegramLinkService:
    # Создаёт и одноразово использует ссылки привязки Telegram.
    def __init__(self, redis: Redis, ttl_seconds: int = 600) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    # Создаёт одноразовый токен для текущего пользователя.
    async def create_token(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        await self.redis.set(
            self._key(token),
            str(user_id),
            ex=self.ttl_seconds,
            nx=True,
        )
        return token

    # Атомарно получает пользователя из токена и удаляет токен.
    async def consume_token(self, token: str) -> int | None:
        value = await self.redis.getdel(self._key(token))
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # Возвращает Redis-ключ для токена привязки Telegram.
    def _key(self, token: str) -> str:
        return f"auth:telegram:link:{token}"
