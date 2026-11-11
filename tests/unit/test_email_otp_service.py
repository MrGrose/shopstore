import json
from unittest.mock import patch

import pytest

from src.core.config import settings
from src.services.email_otp_service import (
    EmailOtpService,
    _email_otp_message,
    _hash_code,
    _normalize_email,
    _otp_key,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def ping(self) -> bool:
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, 60)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


def test_email_otp_message_is_for_email_link_only() -> None:
    subject, body = _email_otp_message("123456", 10)

    assert subject == "Код привязки email SHOPSTORE"
    assert "код для привязки email" in body.lower()
    assert "вход" not in body.lower()
    assert "123456" in body
    assert "10 минут" in body


def test_otp_key_is_scoped_by_user_and_normalized_email() -> None:
    assert _otp_key(" User@Example.COM ", 42) == "otp:link:42:user@example.com"


@pytest.mark.asyncio
async def test_send_code_stores_link_record_and_sends_link_email() -> None:
    redis = _FakeRedis()
    sent: list[tuple[str, str, str]] = []

    async def _capture_send(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    with (
        patch("src.services.email_otp_service.async_redis", return_value=redis),
        patch("src.services.email_otp_service.secrets.randbelow", return_value=893_644),
        patch(
            "src.services.email_otp_service.send_plain_email", side_effect=_capture_send
        ),
    ):
        await EmailOtpService().send_code(" User@Example.COM ", 7301)

    key = _otp_key("user@example.com", 7301)
    assert key in redis.store
    record = json.loads(redis.store[key])
    assert record["purpose"] == "link"
    assert record["code_hash"] == _hash_code("user@example.com", "893644")

    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "user@example.com"
    assert subject == "Код привязки email SHOPSTORE"
    assert "893644" in body
    assert "привязк" in body.lower()


@pytest.mark.asyncio
async def test_verify_code_success_deletes_key() -> None:
    redis = _FakeRedis()
    email = "link@test.example"
    user_id = 99
    code = "445566"
    key = _otp_key(email, user_id)
    await redis.setex(
        key,
        settings.EMAIL_OTP_TTL_SECONDS,
        json.dumps(
            {
                "code_hash": _hash_code(email, code),
                "attempts": 0,
                "purpose": "link",
            },
        ),
    )

    with patch("src.services.email_otp_service.async_redis", return_value=redis):
        await EmailOtpService().verify_code(email, code, user_id)

    assert key not in redis.store


@pytest.mark.asyncio
async def test_verify_code_rejects_wrong_code_and_increments_attempts() -> None:
    redis = _FakeRedis()
    email = "link@test.example"
    user_id = 99
    key = _otp_key(email, user_id)
    await redis.setex(
        key,
        settings.EMAIL_OTP_TTL_SECONDS,
        json.dumps(
            {
                "code_hash": _hash_code(email, "111111"),
                "attempts": 0,
                "purpose": "link",
            },
        ),
    )

    with patch("src.services.email_otp_service.async_redis", return_value=redis):
        with pytest.raises(ValueError, match="Неверный код"):
            await EmailOtpService().verify_code(email, "222222", user_id)

    record = json.loads(redis.store[key])
    assert record["attempts"] == 1


@pytest.mark.asyncio
async def test_verify_code_missing_key_raises() -> None:
    redis = _FakeRedis()

    with patch("src.services.email_otp_service.async_redis", return_value=redis):
        with pytest.raises(ValueError, match="Код недействителен"):
            await EmailOtpService().verify_code(
                "missing@test.example",
                "123456",
                1,
            )


def test_normalize_email_lowercases_and_trims() -> None:
    assert _normalize_email("  Foo@Bar.COM ") == "foo@bar.com"
