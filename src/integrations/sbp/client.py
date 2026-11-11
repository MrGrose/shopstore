import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from src.core.config import settings
from src.core.redis import async_redis
from src.integrations.sbp.errors import SBPApiError, SBPAuthError, SBPTimeoutError
from src.integrations.sbp.redis_lock import release_redis_lock, try_acquire_redis_lock

logger = logging.getLogger(__name__)

_TOKEN_CACHE_KEY = "sbp:access_token"
_TOKEN_EXPIRES_KEY = "sbp:access_token_expires"
_TOKEN_REFRESH_LOCK = "sbp:token_refresh_lock"
# TTL блокировки обновления токена.
_TOKEN_REFRESH_LOCK_TTL = 30
# Сдвиг времени для токена.
_TOKEN_SKEW_SECONDS = 300
# TTL кэша токена по умолчанию.
_TOKEN_DEFAULT_CACHE_TTL = 3600


# Парсит expiresAccess из ответа login.
def _parse_expires_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        if value > 10_000_000_000:
            value = value // 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class SBPClient:
    # Async HTTP-клиент SBP (СБП, JWT + x-req-id).
    def __init__(
        self,
        auth_base_url: str | None = None,
        api_base_url: str | None = None,
        login: str | None = None,
        password: str | None = None,
        tsp_id: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.auth_base_url = (auth_base_url or settings.SBP_AUTH_BASE_URL).rstrip("/")
        self.api_base_url = (api_base_url or settings.SBP_API_BASE_URL).rstrip("/")
        self.login = (login or settings.SBP_LOGIN).strip()
        self.password = (password or settings.SBP_PASSWORD).strip()
        self.tsp_id = int(tsp_id if tsp_id is not None else settings.SBP_TSP_ID)
        self.timeout = aiohttp.ClientTimeout(
            total=float(timeout_seconds or settings.SBP_TIMEOUT_SECONDS)
        )
        self._local_token: str | None = None
        self._local_expires_at: datetime | None = None
        self._local_lock = asyncio.Lock()

    # Создаёт заказ PayIn в провайдере.
    async def create_order(
        self,
        merchant_order_id: str,
        payment_amount_minor: int,
        description: str,
        callback_url: str,
        x_req_id: str,
    ) -> dict[str, Any]:
        payload = {
            "merchantOrderId": merchant_order_id,
            "paymentAmount": int(payment_amount_minor),
            "orderCurrency": "RUB",
            "paymentCurrency": "RUB",
            "tspId": self.tsp_id,
            "description": description,
            "callbackUrl": callback_url,
        }
        data = await self._api_request(
            "POST",
            "/order",
            json_body=payload,
            x_req_id=x_req_id,
        )
        order = data.get("order")
        if not isinstance(order, dict):
            raise SBPApiError("SBP: некорректный ответ create order")
        order_id = order.get("id")
        if order_id is None:
            raise SBPApiError("SBP: не получен id заказа")
        return order

    # Регистрирует QR-код СБП для заказа провайдера.
    async def create_qr(self, provider_order_id: str, x_req_id: str) -> dict[str, Any]:
        path = f"/order/qrcData/{provider_order_id}"
        data = await self._api_request(
            "POST",
            path,
            json_body={},
            x_req_id=x_req_id,
        )
        order = data.get("order")
        if not isinstance(order, dict):
            raise SBPApiError("SBP: некорректный ответ qrcData")
        return order

    # Запрашивает полный заказ у провайдера (статус и QR).
    async def get_order(
        self, provider_order_id: str, x_req_id: str | None = None
    ) -> dict[str, Any]:
        path = f"/order/{provider_order_id}"
        data = await self._api_request("GET", path, x_req_id=x_req_id)
        order = data.get("order")
        if not isinstance(order, dict):
            raise SBPApiError("SBP: некорректный ответ get order")
        return order

    # Запрашивает текущий статус заказа у провайдера.
    async def get_status(self, provider_order_id: str) -> str:
        path = f"/status/{provider_order_id}"
        data = await self._api_request(
            "GET", path, x_req_id=f"status-{provider_order_id}"
        )
        order = data.get("order")
        if not isinstance(order, dict):
            raise SBPApiError("SBP: некорректный ответ status")
        status = order.get("status")
        if not status:
            raise SBPApiError("SBP: пустой статус заказа")
        return str(status)

    async def _api_request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        x_req_id: str | None = None,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{self.api_base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if x_req_id:
            headers["x-req-id"] = x_req_id
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, trust_env=True
            ) as client:
                async with client.request(
                    method, url, headers=headers, json=json_body
                ) as res:
                    return await self._parse_api_response(
                        res,
                        retry_auth=retry_auth,
                        method=method,
                        path=path,
                        json_body=json_body,
                        x_req_id=x_req_id,
                    )
        except asyncio.TimeoutError as exc:
            raise SBPTimeoutError("SBP: превышено время ожидания ответа") from exc
        except aiohttp.ClientError as exc:
            raise SBPApiError("SBP: ошибка сети при обращении к API") from exc

    # Парсит ответ API.
    async def _parse_api_response(
        self,
        res: aiohttp.ClientResponse,
        retry_auth: bool,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
        x_req_id: str | None,
    ) -> dict[str, Any]:
        if res.status in (401, 403) and retry_auth:
            await self._invalidate_token_cache()
            return await self._api_request(
                method,
                path,
                json_body=json_body,
                x_req_id=x_req_id,
                retry_auth=False,
            )
        raw = await res.read()
        if res.status >= 400:
            raise SBPApiError(f"SBP: HTTP {res.status}")
        if not raw:
            raise SBPApiError("SBP: пустой ответ API")
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SBPApiError("SBP: некорректный JSON в ответе") from exc
        if not isinstance(data, dict):
            raise SBPApiError("SBP: некорректный формат ответа")
        if data.get("success") is False:
            description = str(data.get("description") or "ошибка провайдера")
            raise SBPApiError(f"SBP: {description}")
        return data

    # Получает токен доступа.
    async def _get_access_token(self) -> str:
        cached = await self._read_cached_token()
        if cached:
            return cached
        async with self._local_lock:
            cached = await self._read_cached_token()
            if cached:
                return cached
            local_cached = self._read_local_token()
            if local_cached:
                return local_cached
            lock_owner = await try_acquire_redis_lock(
                _TOKEN_REFRESH_LOCK,
                _TOKEN_REFRESH_LOCK_TTL,
            )
            if lock_owner is None:
                await asyncio.sleep(0.2)
                cached = await self._read_cached_token()
                if cached:
                    return cached
                local_cached = self._read_local_token()
                if local_cached:
                    return local_cached
            try:
                token, expires_at = await self._login()
                await self._store_token_cache(token, expires_at)
                self._local_token = token
                self._local_expires_at = expires_at
                return token
            finally:
                if lock_owner:
                    await release_redis_lock(_TOKEN_REFRESH_LOCK, lock_owner)

    # Выполняет логин в SBP.
    async def _login(self) -> tuple[str, datetime | None]:
        if not self.login or not self.password:
            raise SBPAuthError("SBP: не заданы SBP_LOGIN/SBP_PASSWORD")
        url = f"{self.auth_base_url}/public/login"
        payload = {"login": self.login, "password": self.password}
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, trust_env=True
            ) as client:
                async with client.post(url, json=payload) as res:
                    if res.status in (401, 403):
                        raise SBPAuthError("SBP: неверный логин или пароль")
                    if res.status >= 400:
                        raise SBPAuthError(f"SBP login: HTTP {res.status}")
                    data = await res.json(content_type=None)
        except asyncio.TimeoutError as exc:
            raise SBPTimeoutError("SBP: превышено время ожидания login") from exc
        except aiohttp.ClientError as exc:
            raise SBPApiError("SBP: ошибка сети при login") from exc
        if not isinstance(data, dict):
            raise SBPAuthError("SBP: некорректный ответ login")
        if not data.get("success", True):
            raise SBPAuthError("SBP: login отклонён")
        token = str(data.get("accessToken") or "").strip()
        if not token:
            raise SBPAuthError("SBP: accessToken не получен")
        expires_at = _parse_expires_at(str(data.get("expiresAccess") or ""))
        return token, expires_at

    # Читает токен из Redis.
    async def _read_cached_token(self) -> str | None:
        try:
            redis = async_redis()
            token = await redis.get(_TOKEN_CACHE_KEY)
            if not token:
                return None
            expires_raw = await redis.get(_TOKEN_EXPIRES_KEY)
            expires_at = _parse_expires_at(str(expires_raw or ""))
            if expires_at and datetime.now(timezone.utc) >= expires_at - timedelta(
                seconds=_TOKEN_SKEW_SECONDS
            ):
                return None
            return str(token)
        except Exception:
            logger.debug("SBP: Redis token cache недоступен, используем local")
            return None

    # Читает токен из локальной памяти.
    def _read_local_token(self) -> str | None:
        if not self._local_token:
            return None
        if self._local_expires_at and datetime.now(
            timezone.utc
        ) >= self._local_expires_at - timedelta(seconds=_TOKEN_SKEW_SECONDS):
            return None
        return self._local_token

    # Сохраняет токен в Redis.
    async def _store_token_cache(self, token: str, expires_at: datetime | None) -> None:
        try:
            redis = async_redis()
            ttl_seconds = _TOKEN_DEFAULT_CACHE_TTL
            if expires_at:
                ttl_seconds = max(
                    60,
                    int(
                        (
                            expires_at
                            - timedelta(seconds=_TOKEN_SKEW_SECONDS)
                            - datetime.now(timezone.utc)
                        ).total_seconds()
                    ),
                )
            await redis.set(_TOKEN_CACHE_KEY, token, ex=ttl_seconds)
            if expires_at:
                await redis.set(
                    _TOKEN_EXPIRES_KEY,
                    expires_at.isoformat(),
                    ex=ttl_seconds,
                )
        except Exception:
            logger.debug("SBP: не удалось сохранить token в Redis")

    # Сбрасывает кэш токена.
    async def _invalidate_token_cache(self) -> None:
        self._local_token = None
        self._local_expires_at = None
        try:
            redis = async_redis()
            await redis.delete(_TOKEN_CACHE_KEY, _TOKEN_EXPIRES_KEY)
        except Exception:
            pass
