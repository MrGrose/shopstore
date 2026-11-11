import logging

from src.core.config import settings
from src.core.redis import async_redis
from src.integrations.telegram_gateway import (
    GatewayAuthError,
    GatewayDeliveryError,
    TelegramGatewayClient,
)
from src.services.verification.phone.rate_limit import PhoneRateLimiter
from src.services.verification.phone.session_store import (
    PhoneSessionStore,
    VerificationPurpose,
)
from src.utils.phone import mask_phone, normalize_ru_mobile_phone

logger = logging.getLogger(__name__)


class PhoneVerificationService:
    # Отправка и проверка phone verification codes через Telegram Gateway.
    def __init__(self, gateway: TelegramGatewayClient | None = None) -> None:
        self.gateway = gateway or TelegramGatewayClient()

    # Отправляет verification code и сохраняет request_id в Redis.
    async def send_code(
        self,
        phone: str,
        client_ip: str | None = None,
        purpose: VerificationPurpose = "login",
        user_id: int | None = None,
    ) -> int:
        if not settings.telegram_gateway_configured:
            logger.warning(
                "Phone login: TELEGRAM_GATEWAY_ACCESS_TOKEN не задан — "
                "добавьте в .env и перезапустите API"
            )
            raise RuntimeError("Вход по телефону временно недоступен")

        phone_e164 = normalize_ru_mobile_phone(phone)
        redis = async_redis()
        rate_limiter = PhoneRateLimiter(redis)
        await rate_limiter.assert_send_allowed(phone_e164, client_ip)

        try:
            result = await self.gateway.send_verification_message(
                phone_number=phone_e164,
                code_length=settings.PHONE_LOGIN_CODE_LENGTH,
                ttl=settings.PHONE_LOGIN_CODE_TTL_SECONDS,
                payload=purpose,
            )
        except GatewayAuthError as exc:
            logger.error("Telegram Gateway auth: %s", exc)
            raise RuntimeError("Вход по телефону временно недоступен") from exc
        except GatewayDeliveryError as exc:
            logger.warning(
                "Telegram Gateway send отклонён для %s: %s",
                mask_phone(phone_e164),
                exc,
            )
            raise ValueError(
                "Код не удалось отправить. "
                "Убедитесь, что номер зарегистрирован в Telegram"
            ) from exc

        request_id = str(result.get("request_id") or "").strip()
        if not request_id:
            logger.error(
                "Telegram Gateway не вернул request_id для %s",
                mask_phone(phone_e164),
            )
            raise RuntimeError("Сервис временно недоступен")

        balance = result.get("remaining_balance")
        if balance is not None:
            logger.info(
                "Phone verify send ok phone=%s balance=%s",
                mask_phone(phone_e164),
                balance,
            )

        await PhoneSessionStore(redis).save(
            phone_e164,
            purpose,
            request_id,
            user_id=user_id,
        )
        await rate_limiter.record_send(phone_e164, client_ip)
        return settings.PHONE_LOGIN_CODE_TTL_SECONDS

    # Проверяет код через Telegram Gateway checkVerificationStatus.
    async def verify_code(
        self,
        phone: str,
        code: str,
        purpose: VerificationPurpose = "login",
        user_id: int | None = None,
    ) -> None:
        if not settings.telegram_gateway_configured:
            logger.warning(
                "Phone login: TELEGRAM_GATEWAY_ACCESS_TOKEN не задан — "
                "добавьте в .env и перезапустите API"
            )
            raise RuntimeError("Вход по телефону временно недоступен")

        phone_e164 = normalize_ru_mobile_phone(phone)
        normalized_code = code.strip()
        if not normalized_code:
            raise ValueError("Неверный код")

        redis = async_redis()
        session_store = PhoneSessionStore(redis)
        session = await session_store.load(phone_e164, purpose, user_id=user_id)
        if session is None:
            raise ValueError("Код недействителен. Нажмите «Отправить код повторно».")

        rate_limiter = PhoneRateLimiter(redis)
        rate_limiter.assert_verify_attempts_allowed(session.attempts)

        try:
            result = await self.gateway.check_verification_status(
                session.request_id,
                normalized_code,
            )
        except GatewayAuthError as exc:
            logger.error("Telegram Gateway auth при verify: %s", exc)
            raise RuntimeError("Сервис временно недоступен") from exc
        except GatewayDeliveryError as exc:
            logger.warning(
                "Telegram Gateway verify ошибка phone=%s: %s",
                mask_phone(phone_e164),
                exc,
            )
            raise ValueError("Неверный код") from exc

        verification_status = result.get("verification_status")
        status = ""
        if isinstance(verification_status, dict):
            status = str(verification_status.get("status") or "")

        if status == "code_valid":
            await session_store.delete(phone_e164, purpose, user_id=user_id)
            return

        if status in {"code_max_attempts_exceeded", "expired"}:
            await session_store.delete(phone_e164, purpose, user_id=user_id)
            if status == "expired":
                raise ValueError("Код истёк. Запросите новый код")
            raise ValueError("Слишком много попыток. Запросите новый код")

        session.attempts += 1
        if session.attempts >= settings.PHONE_LOGIN_VERIFY_MAX_ATTEMPTS:
            await session_store.delete(phone_e164, purpose, user_id=user_id)
            raise ValueError("Слишком много попыток. Запросите новый код")

        await session_store.increment_attempts(
            phone_e164,
            purpose,
            session,
            user_id=user_id,
        )
        raise ValueError("Неверный код")
