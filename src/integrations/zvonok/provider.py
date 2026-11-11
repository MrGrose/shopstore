import logging
from dataclasses import dataclass
from typing import Literal

import aiohttp
from pydantic import TypeAdapter, ValidationError

from src.core.config import settings
from src.integrations.zvonok.schemas import (
    ZvonokCallStatusItem,
    ZvonokErrorResponse,
    ZvonokStartResponse,
)
from src.utils.phone import mask_phone

logger = logging.getLogger(__name__)

PhoneAuthChannel = Literal["flash_call", "voice_code", "verification_number"]
ProviderCallStatus = Literal["pending", "verified", "failed", "expired"]


class PhoneCallProviderError(RuntimeError):
    pass


@dataclass
class ProviderStartResult:
    external_id: str
    phone: str | None = None
    code: str | None = None
    balance: float | str | None = None
    created_at: str | None = None


class ZvonokPhoneProvider:
    # Выполняет запросы Zvonok и переводит ответы во внутренние статусы.
    def __init__(self) -> None:
        self.base_url = settings.ZVONOK_BASE_URL.rstrip("/")
        self.public_key = settings.ZVONOK_PUBLIC_KEY.strip()
        self.channel_config: dict[PhoneAuthChannel, tuple[str, int]] = {
            "flash_call": ("flashcall", settings.ZVONOK_FLASH_CALL_CAMPAIGN_ID),
            "voice_code": ("tellcode", settings.ZVONOK_VOICE_CODE_CAMPAIGN_ID),
            "verification_number": (
                "confirm",
                settings.ZVONOK_VERIFICATION_NUMBER_CAMPAIGN_ID,
            ),
        }

    # Запускает звонок выбранного канала.
    async def start(
        self,
        channel: PhoneAuthChannel,
        phone_e164: str,
        code: str | None = None,
    ) -> ProviderStartResult:
        if not self.public_key:
            raise PhoneCallProviderError("Zvonok не настроен")
        endpoint, campaign_id = self.channel_config[channel]
        form = aiohttp.FormData(default_to_multipart=True)
        form.add_field("public_key", self.public_key)
        form.add_field("phone", phone_e164)
        form.add_field("campaign_id", str(campaign_id))
        if code is not None:
            form.add_field("pincode", code)
        data = await self._request_json(
            "POST",
            f"{self.base_url}/manager/cabapi_external/api/v1/phones/{endpoint}/",
            data=form,
        )
        try:
            parsed = ZvonokStartResponse.model_validate(data)
        except ValidationError as exc:
            logger.error(
                "Zvonok вернул некорректный ответ запуска для %s",
                mask_phone(phone_e164),
            )
            raise PhoneCallProviderError("Некорректный ответ провайдера") from exc
        result_data = parsed.data if not isinstance(parsed.data, str) else None
        external_id = str(result_data.call_id or "").strip() if result_data else ""
        if parsed.status.lower() != "ok" or not external_id:
            logger.warning(
                "Zvonok отклонил запуск для %s: status=%s has_call_id=%s",
                mask_phone(phone_e164),
                parsed.status,
                bool(external_id),
            )
            raise PhoneCallProviderError("Провайдер отклонил запрос звонка")
        returned_code = None
        if result_data and result_data.pincode is not None:
            returned_code = str(result_data.pincode).zfill(4)
        return ProviderStartResult(
            external_id=external_id,
            phone=result_data.phone if result_data else None,
            code=returned_code,
            balance=result_data.balance if result_data else None,
            created_at=result_data.created if result_data else None,
        )

    # Получает внутренний статус звонка без раскрытия URL с ключом.
    async def get_status(self, external_id: str) -> ProviderCallStatus:
        data = await self._request_json(
            "GET",
            f"{self.base_url}/manager/cabapi_external/api/v1/phones/call_by_id/",
            params={"public_key": self.public_key, "call_id": external_id},
        )
        try:
            if isinstance(data, dict):
                error = ZvonokErrorResponse.model_validate(data)
                raise PhoneCallProviderError(
                    "Провайдер отклонил проверку звонка"
                    if error.status.lower() != "ok"
                    else "Некорректный ответ провайдера"
                )
            calls = TypeAdapter(list[ZvonokCallStatusItem]).validate_python(data)
        except ValidationError as exc:
            raise PhoneCallProviderError("Некорректный ответ провайдера") from exc
        if not calls:
            raise PhoneCallProviderError("Провайдер не вернул звонок")
        return self._map_status(calls[0].call_status)

    # Переводит статус Zvonok во внутренний статус.
    def _map_status(self, status_value: str) -> ProviderCallStatus:
        status_name = status_value.strip().lower()
        if status_name == "pincode_ok":
            return "verified"
        if status_name == "in_process":
            return "pending"
        if status_name == "expires":
            return "expired"
        failed_statuses = {
            "attempts_exc",
            "deleted",
            "duration_error",
            "novalid_button",
            "no_provider",
            "interrupted",
            "pincode_nook",
            "synth_error",
            "duplicate",
        }
        if status_name in failed_statuses:
            return "failed"
        # Новые или временные статусы провайдера не должны преждевременно
        # удалять call_id: подтверждение ещё может прийти следующим polling-запросом.
        return "pending"

    # Выполняет HTTP-запрос без логирования URL, query и body.
    async def _request_json(self, method: str, url: str, **kwargs: object) -> object:
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as client:
                async with client.request(method, url, **kwargs) as response:
                    data = await response.json(content_type=None)
                    if response.status >= 400:
                        raise PhoneCallProviderError("Ошибка связи с провайдером")
                    return data
        except PhoneCallProviderError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("Сбой запроса Zvonok: %s", type(exc).__name__)
            raise PhoneCallProviderError("Ошибка связи с провайдером") from exc
