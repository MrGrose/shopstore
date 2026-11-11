from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# Способ входа в ответе /users/me.
class IdentitySchema(BaseModel):
    provider: str
    provider_user_id: str | None = None
    email: str | None = None
    telegram_username: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# Схема пользователя в ответе API.
class UserSchema(BaseModel):
    id: int
    telegram_id: int | None = None
    telegram_username: str | None = None
    email: str | None = None
    name: str | None = None
    avatar: str | None = None
    role: str = "buyer"
    referral_code: str | None = None
    referrer_id: int | None = None
    referral_commission_percent: Decimal | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# Текущий пользователь в ЛК: флаги доступа считаются на бэкенде.
class UserMeSchema(UserSchema):
    can_be_referred: bool = False
    has_referral_program: bool = False
    identities: list[IdentitySchema] = []


# Частичное обновление профиля в личном кабинете.
class UserMeUpdate(BaseModel):
    name: str | None = None


# Создание пользователя.
class UserCreate(BaseModel):
    email: str | None = None
    name: str | None = None
    role: str = "buyer"


# Частичное обновление пользователя.
class UserUpdate(BaseModel):
    email: str | None = None
    name: str | None = None
    role: str | None = None
    referral_commission_percent: Decimal | None = None
    is_active: bool | None = None
