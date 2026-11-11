import logging
from typing import Any

import aiohttp

from src.core.config import settings
from src.integrations.telegram_gateway.errors import (
    GatewayAuthError,
    GatewayDeliveryError,
    GatewayError,
)

logger = logging.getLogger(__name__)


class TelegramGatewayClient:
    # HTTP-клиент Telegram Gateway API (verification codes).
    def __init__(
        self, access_token: str | None = None, base_url: str | None = None
    ) -> None:
        self.access_token = (
            access_token or settings.TELEGRAM_GATEWAY_ACCESS_TOKEN
        ).strip()
        self.base_url = (base_url or settings.TELEGRAM_GATEWAY_BASE_URL).rstrip("/")

    # Отправляет verification code через Telegram Gateway.
    async def send_verification_message(
        self,
        phone_number: str,
        code_length: int,
        ttl: int,
        payload: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "phone_number": phone_number,
            "code_length": code_length,
            "ttl": ttl,
        }
        if payload:
            body["payload"] = payload
        return await self._post("sendVerificationMessage", body)

    # Проверяет код и статус verification request.
    async def check_verification_status(
        self,
        request_id: str,
        code: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"request_id": request_id}
        if code is not None:
            body["code"] = code
        return await self._post("checkVerificationStatus", body)

    # Проверяет возможность доставки (только диагностика).
    async def check_send_ability(self, phone_number: str) -> dict[str, Any]:
        return await self._post("checkSendAbility", {"phone_number": phone_number})

    async def _post(self, method: str, json_body: dict[str, Any]) -> dict[str, Any]:
        if not self.access_token:
            raise GatewayAuthError("Telegram Gateway не настроен")

        url = f"{self.base_url}/{method}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as client:
            async with client.post(url, headers=headers, json=json_body) as response:
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    raise GatewayError("Некорректный ответ Telegram Gateway")

                if not data.get("ok"):
                    error = str(data.get("error") or "UNKNOWN_ERROR")
                    if error == "ACCESS_TOKEN_INVALID":
                        raise GatewayAuthError("Неверный токен Telegram Gateway")
                    raise GatewayDeliveryError(error)

                result = data.get("result")
                if not isinstance(result, dict):
                    raise GatewayError("Пустой result от Telegram Gateway")
                return result
