import pytest

from src.services.auth.telegram_link import TelegramLinkService


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def getdel(self, key: str) -> str | None:
        value = self.values.pop(key, None)
        self.expirations.pop(key, None)
        return value


# Проверяет срок хранения и одноразовое использование токена.
@pytest.mark.asyncio
async def test_telegram_link_token_is_single_use_and_does_not_expose_user_id():
    redis = _Redis()
    service = TelegramLinkService(redis, ttl_seconds=600)

    token = await service.create_token(42)

    assert token
    assert "42" not in token
    assert list(redis.expirations.values()) == [600]
    assert await service.consume_token(token) == 42
    assert await service.consume_token(token) is None
