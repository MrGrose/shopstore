import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from urllib.parse import parse_qsl

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.user_access import assert_user_can_authenticate
from src.core.user_roles import UserRole
from src.models.user import User
from src.schemas.auth import TelegramWidgetPayloadSchema, TelegramWidgetUserSchema
from src.services.user_service import UserService

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_service = UserService(session=session)

    # Проверяет подлинность initData и возвращает user payload.
    def _validate_telegram_init_data(self, init_data: str) -> dict[str, object]:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        incoming_hash = parsed.pop("hash", None)
        if not incoming_hash:
            raise ValueError("Некорректные данные Telegram")

        check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        bot_token = settings.TG_BOT_SHOP.strip()
        if not bot_token:
            raise ValueError("TG_BOT_SHOP не задан")
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            key=secret_key,
            msg=check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, incoming_hash):
            raise ValueError("Подпись Telegram не прошла проверку")

        auth_date = int(parsed.get("auth_date", "0"))
        now_ts = int(datetime.now(tz=UTC).timestamp())
        if auth_date <= 0 or now_ts - auth_date > settings.TG_LOGIN_MAX_AGE_SECONDS:
            raise ValueError("Telegram-сессия устарела")

        user_data_raw = parsed.get("user")
        if not user_data_raw:
            raise ValueError("Данные пользователя отсутствуют")

        try:
            user_data = json.loads(user_data_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Некорректные данные пользователя") from exc

        if "id" not in user_data:
            raise ValueError("Telegram user id отсутствует")
        return user_data

    # Проверяет подпись Telegram Login Widget (публичная обёртка).
    def validate_telegram_widget_payload(
        self, payload: dict[str, object]
    ) -> TelegramWidgetUserSchema:
        return self._validate_telegram_widget_payload(payload)

    # Проверяет подпись Telegram Login Widget и нормализует user-данные.
    def _validate_telegram_widget_payload(
        self, payload: dict[str, object]
    ) -> TelegramWidgetUserSchema:
        data = TelegramWidgetPayloadSchema.model_validate(payload)
        now_ts = int(datetime.now(tz=UTC).timestamp())
        if now_ts - data.auth_date > settings.TG_LOGIN_MAX_AGE_SECONDS:
            raise ValueError("Telegram-сессия устарела")
        data_check_items = []
        for key in sorted(
            ("auth_date", "first_name", "id", "last_name", "photo_url", "username")
        ):
            value = getattr(data, key, None)
            if value is None:
                continue
            text = str(value).strip() if isinstance(value, str) else str(value)
            if text == "":
                continue
            data_check_items.append(f"{key}={text}")
        data_check_string = "\n".join(data_check_items)
        secret_key = hashlib.sha256(settings.TG_BOT_SHOP.encode("utf-8")).digest()
        expected_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, data.hash):
            raise ValueError("Подпись Telegram не прошла проверку")

        first_name = (data.first_name or "").strip()
        last_name = (data.last_name or "").strip()
        full_name = f"{first_name} {last_name}".strip() or None
        username = (data.username or "").strip() or None
        return TelegramWidgetUserSchema(
            id=data.id,
            telegram_username=username,
            name=full_name,
            photo_url=data.photo_url,
        )

    # Аутентифицирует пользователя через Telegram Mini App или Login Widget.
    async def authenticate_telegram_unified(
        self,
        source: str,
        payload: dict[str, object],
    ) -> User:
        if source == "miniapp":
            telegram_data = self._validate_telegram_init_data(
                str(payload.get("init_data") or "")
            )
            telegram_id_raw = telegram_data["id"]
            if not isinstance(telegram_id_raw, int):
                raise ValueError("Некорректный Telegram user id")
            first_name = str(telegram_data.get("first_name") or "").strip()
            last_name = str(telegram_data.get("last_name") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or None
            username = str(telegram_data.get("username") or "").strip() or None
            photo_url = str(telegram_data.get("photo_url") or "").strip() or None
            user = await self.user_service.upsert_telegram_user(
                telegram_id=telegram_id_raw,
                telegram_username=username,
                name=full_name,
                photo_url=photo_url or None,
            )
            user = await self.user_service.refresh_user_role_from_telegram_allowlist(
                user
            )
            assert_user_can_authenticate(user)
            return user

        if source == "widget":
            widget_payload = {
                key: payload.get(key)
                for key in (
                    "id",
                    "first_name",
                    "last_name",
                    "username",
                    "photo_url",
                    "auth_date",
                    "hash",
                )
                if payload.get(key) is not None
            }
            widget_user = self._validate_telegram_widget_payload(widget_payload)
            user = await self.user_service.upsert_telegram_user(
                telegram_id=widget_user.id,
                telegram_username=widget_user.telegram_username,
                name=widget_user.name,
                photo_url=widget_user.photo_url,
            )
            user = await self.user_service.refresh_user_role_from_telegram_allowlist(
                user
            )
            assert_user_can_authenticate(user)
            return user

        raise ValueError("Неизвестный source авторизации")

    # Выполняет вход через Telegram Mini App initData или Telegram Login Widget.
    async def login_via_telegram_unified(
        self,
        source: str,
        payload: dict[str, object],
        referral_code: str | None = None,
    ) -> tuple[str, User]:
        from src.core.security import create_access_token

        user = await self.authenticate_telegram_unified(source, payload)
        if referral_code:
            from src.services.referral_service import ReferralService

            result = await ReferralService(self.session).attribute_referrer(
                user, referral_code
            )
            user = result.user
        return create_access_token(user.id), user

    # Аутентифицирует admin-user для входа в панель (ADMIN_TG_IDS / TG_ADMIN_ID).
    async def authenticate_admin_panel(self) -> User:
        telegram_id = settings.dev_storefront_login_telegram_id
        if telegram_id is None:
            raise ValueError("Задайте ADMIN_TG_IDS или TG_ADMIN_ID в .env")
        user = await self.user_service.upsert_telegram_user(
            telegram_id=telegram_id,
            telegram_username=None,
            name="Admin Panel",
        )
        user = await self.user_service.refresh_user_role_from_telegram_allowlist(user)
        if user.role != UserRole.ADMIN.value:
            raise ValueError("Пользователь не имеет роль admin")
        return user
