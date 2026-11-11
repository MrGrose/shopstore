from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.user import UserSchema


# Запрос проверки существования email.
class EmailCheckRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


# Ответ проверки существования email.
class EmailCheckResponse(BaseModel):
    exists: bool


# Запрос регистрации пользователя.
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str | None = Field(default=None, max_length=255)


# Ответ регистрации пользователя.
class RegisterResponse(BaseModel):
    id: int
    email: str | None
    name: str | None


# Ответ авторизации через Telegram.
class TelegramLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserSchema


# Диагностика Mini App auth (без initData, только для логов).
class MiniAppAuthProbeRequest(BaseModel):
    phase: str = Field(min_length=1, max_length=32)
    platform: str = Field(default="", max_length=64)
    init_data_len: int = Field(default=0, ge=0)
    has_telegram: bool = False
    has_webapp: bool = False
    version: str = Field(default="", max_length=32)
    inside_webapp: bool = False
    error_message: str | None = Field(default=None, max_length=500)


# Унифицированный запрос Telegram-логина для Mini App и сайта.
class TelegramUnifiedLoginRequest(BaseModel):
    # Откуда пришел логин: miniapp или widget.
    source: Literal["miniapp", "widget"]

    # Поле для Mini App режима (window.Telegram.WebApp.initData).
    init_data: str | None = Field(default=None, min_length=10)

    # Поля для Telegram Login Widget (сайт).
    id: int | None = Field(default=None, gt=0)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    photo_url: str | None = Field(default=None, max_length=2048)
    auth_date: int | None = Field(default=None, gt=0)
    hash: str | None = Field(default=None, min_length=10)


# Схема payload для Telegram Login Widget.
class TelegramWidgetPayloadSchema(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    photo_url: str | None = Field(default=None, max_length=2048)
    auth_date: int = Field(gt=0)
    hash: str = Field(min_length=10)


# Схема пользователя Telegram Login Widget.
class TelegramWidgetUserSchema(BaseModel):
    id: int
    telegram_username: str | None
    name: str | None
    photo_url: str | None = None


class TelegramLinkResponse(BaseModel):
    # Возвращает ссылку для привязки Telegram к текущему аккаунту.
    url: str
    expires_in: int


# Запрос отправки OTP на email.
class EmailSendCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


# Запрос проверки OTP и входа по email.
class EmailVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=6, max_length=6)


# Запрос отправки phone verification code.
class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


# Ответ send-code с TTL.
class PhoneSendCodeResponse(BaseModel):
    expires_in: int = Field(ge=30, le=3600)


# Запрос verify phone code.
class PhoneVerifyRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=4, max_length=8)


# Ответ phone login с флагом нового пользователя.
class PhoneLoginResponse(TelegramLoginResponse):
    is_new_user: bool = False


PhoneAuthChannel = Literal["flash_call", "voice_code", "verification_number"]
PhoneCallStatus = Literal[
    "pending", "verified", "failed", "expired", "cancelled", "used"
]


# Запрос запуска нового phone call flow.
class PhoneCallStartRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


# Запрос проверки четырёхзначного кода звонка.
class PhoneCallVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")


# Публичное состояние phone call flow без телефона и provider details.
class PhoneCallFlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flow_id: str
    channel: PhoneAuthChannel
    status: PhoneCallStatus
    expires_in: int = Field(ge=0)
    retry_after: int = Field(ge=0)
    can_retry: bool
    call_started: bool
    next_channel: PhoneAuthChannel | None = None
    verification_phone_number: str | None = None


# Единый запрос логина (telegram).
class UnifiedLoginRequest(BaseModel):
    provider: Literal["telegram"] = "telegram"
    source: Literal["miniapp", "widget"] | None = None
    init_data: str | None = Field(default=None, min_length=10)
    id: int | None = Field(default=None, gt=0)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    photo_url: str | None = Field(default=None, max_length=2048)
    auth_date: int | None = Field(default=None, gt=0)
    hash: str | None = Field(default=None, min_length=10)
