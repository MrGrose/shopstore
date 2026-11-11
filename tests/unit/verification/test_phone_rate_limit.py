import pytest

from src.services.verification.phone.rate_limit import PhoneRateLimiter


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.values else 0

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    async def incr(self, key: str) -> int:
        current = int(self.values.get(key, "0")) + 1
        self.values[key] = str(current)
        return current

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl

    async def ping(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_assert_send_allowed_blocks_cooldown():
    redis = _FakeRedis()
    limiter = PhoneRateLimiter(redis)
    redis.values["phone_verify_rate:cooldown:+79991234567"] = "1"
    with pytest.raises(ValueError, match="Подождите"):
        await limiter.assert_send_allowed("+79991234567", "1.2.3.4")


def test_assert_verify_attempts_allowed():
    limiter = PhoneRateLimiter(_FakeRedis())
    with pytest.raises(ValueError, match="Слишком много попыток"):
        limiter.assert_verify_attempts_allowed(5)
