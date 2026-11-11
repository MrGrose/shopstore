from unittest.mock import patch

import pytest

from src.services.support import SupportRateLimiter


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttl_keys: set[str] = set()

    async def ping(self) -> bool:
        return True

    async def exists(self, key: str) -> int:
        return 1 if key in self.ttl_keys else 0

    async def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return str(value) if value is not None else None

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.ttl_keys.add(key)

    async def incr(self, key: str) -> int:
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key: str, _ttl: int) -> None:
        return None


@pytest.mark.asyncio
async def test_support_rate_limit_blocks_after_create_limit() -> None:
    redis = _FakeRedis()
    limiter = SupportRateLimiter(redis)
    with patch("src.services.support.rate_limit.settings") as cfg:
        cfg.SUPPORT_RATE_LIMIT_CREATE_PER_WINDOW = 2
        cfg.SUPPORT_RATE_LIMIT_MESSAGE_PER_WINDOW = 30
        cfg.SUPPORT_RATE_LIMIT_COOLDOWN_SECONDS = 30
        cfg.SUPPORT_RATE_LIMIT_WINDOW_SECONDS = 3600

        redis.values["support_rate:user:10:create_ticket"] = 2
        with pytest.raises(ValueError, match="Слишком много"):
            await limiter.assert_action_allowed(10, "create_ticket")


@pytest.mark.asyncio
async def test_support_rate_limit_cooldown_blocks_rapid_resend() -> None:
    redis = _FakeRedis()
    limiter = SupportRateLimiter(redis)
    with patch("src.services.support.rate_limit.settings") as cfg:
        cfg.SUPPORT_RATE_LIMIT_CREATE_PER_WINDOW = 10
        cfg.SUPPORT_RATE_LIMIT_MESSAGE_PER_WINDOW = 30
        cfg.SUPPORT_RATE_LIMIT_COOLDOWN_SECONDS = 30
        cfg.SUPPORT_RATE_LIMIT_WINDOW_SECONDS = 3600

        await limiter.record_action(11, "add_message")
        with pytest.raises(ValueError, match="Подождите"):
            await limiter.assert_action_allowed(11, "add_message")
