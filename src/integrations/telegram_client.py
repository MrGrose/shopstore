from dataclasses import dataclass
from http import HTTPStatus

import aiohttp

from src.core.config import settings


# результат отправки сообщения в Telegram
@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    message_id: int | None = None


class TelegramClient:
    def __init__(self, bot_token: str | None) -> None:
        self.bot_token = bot_token
        proxy = settings.TG_BOT_PROXY.strip()
        self._proxy = proxy or None

    # Отправка сообщения.
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, object] | None = None,
    ) -> TelegramSendResult:
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self._post_telegram(endpoint, payload)

    # Редактирование текста сообщения.
    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, object] | None = None,
    ) -> bool:
        endpoint = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result = await self._post_telegram(endpoint, payload)
        return result.ok

    # Отправка POST запроса в Telegram.
    async def _post_telegram(
        self,
        endpoint: str,
        payload: dict[str, object],
    ) -> TelegramSendResult:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=timeout,
        ) as client:
            async with client.post(
                endpoint,
                json=payload,
                proxy=self._proxy,
            ) as response:
                if response.status >= HTTPStatus.BAD_REQUEST:
                    return TelegramSendResult(ok=False)
                try:
                    body = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    return TelegramSendResult(ok=True)
                result = body.get("result")
                if not isinstance(result, dict):
                    return TelegramSendResult(ok=True)
                raw_message_id = result.get("message_id")
                message_id = (
                    int(raw_message_id) if isinstance(raw_message_id, int) else None
                )
                return TelegramSendResult(ok=True, message_id=message_id)
