import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime

from redis.asyncio import Redis

from src.core.config import settings
from src.core.redis import async_redis
from src.integrations.smtp_client import send_plain_email

logger = logging.getLogger(__name__)


# Нормализует email для ключей Redis.
def _normalize_email(email: str) -> str:
    return email.strip().lower()


# Строит ключ Redis для OTP привязки email.
def _otp_key(email: str, user_id: int) -> str:
    normalized = _normalize_email(email)
    return f"otp:link:{user_id}:{normalized}"


# Хэширует OTP-код с секретом приложения.
def _hash_code(email: str, code: str) -> str:
    payload = f"{_normalize_email(email)}:{code}:{settings.AUTH_SECRET}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Текст письма OTP для привязки email к аккаунту.
def _email_otp_message(code: str, ttl_minutes: int) -> tuple[str, str]:
    return (
        "Код привязки email SHOPSTORE",
        (
            f"Ваш код для привязки email: {code}\n\n"
            f"Код действует {ttl_minutes} минут.\n"
            "Если вы не запрашивали привязку — проигнорируйте письмо."
        ),
    )


class EmailOtpService:
    # Генерирует OTP, сохраняет в Redis и отправляет на email.
    async def send_code(
        self,
        email: str,
        user_id: int,
        client_ip: str | None = None,
    ) -> None:
        redis = async_redis()
        try:
            await redis.ping()
        except Exception as exc:
            logger.error("Redis недоступен для OTP: %s", exc)
            raise RuntimeError("Сервис временно недоступен") from exc

        normalized = _normalize_email(email)
        await self._check_rate_limit(redis, normalized, client_ip)

        code = f"{secrets.randbelow(1_000_000):06d}"
        record = {
            "code_hash": _hash_code(normalized, code),
            "attempts": 0,
            "created_at": datetime.now(tz=UTC).isoformat(),
            "purpose": "link",
        }
        key = _otp_key(normalized, user_id)
        await redis.setex(
            key,
            settings.EMAIL_OTP_TTL_SECONDS,
            json.dumps(record),
        )

        subject, body = _email_otp_message(
            code,
            settings.EMAIL_OTP_TTL_SECONDS // 60,
        )
        await send_plain_email(normalized, subject, body)

    # Проверяет OTP и удаляет ключ при успехе.
    async def verify_code(
        self,
        email: str,
        code: str,
        user_id: int,
    ) -> None:
        redis = async_redis()
        normalized = _normalize_email(email)
        key = _otp_key(normalized, user_id)
        raw = await redis.get(key)
        if not raw:
            raise ValueError("Код недействителен. Нажмите «Отправить код повторно».")

        record = json.loads(raw)
        attempts = int(record.get("attempts") or 0)
        if attempts >= settings.EMAIL_OTP_MAX_ATTEMPTS:
            await redis.delete(key)
            raise ValueError("Слишком много попыток. Запросите новый код")

        expected = str(record.get("code_hash") or "")
        if not secrets.compare_digest(_hash_code(normalized, code.strip()), expected):
            record["attempts"] = attempts + 1
            ttl = await redis.ttl(key)
            if ttl > 0:
                await redis.setex(key, ttl, json.dumps(record))
            raise ValueError("Неверный код")

        await redis.delete(key)

    # Rate limit по email и IP.
    async def _check_rate_limit(
        self,
        redis: Redis,
        email: str,
        client_ip: str | None,
    ) -> None:
        window = settings.EMAIL_OTP_RATE_LIMIT_WINDOW_SECONDS
        email_key = f"otp_rate:email:{email}"
        email_count = await redis.incr(email_key)
        if email_count == 1:
            await redis.expire(email_key, window)
        if email_count > settings.EMAIL_OTP_RATE_LIMIT_EMAIL:
            raise ValueError("Слишком много запросов. Попробуйте позже")

        if client_ip:
            ip_key = f"otp_rate:ip:{client_ip}"
            ip_count = await redis.incr(ip_key)
            if ip_count == 1:
                await redis.expire(ip_key, window)
            if ip_count > settings.EMAIL_OTP_RATE_LIMIT_IP:
                raise ValueError("Слишком много запросов. Попробуйте позже")
