from enum import StrEnum

from src.core.config import settings


class UserRole(StrEnum):
    BUYER = "buyer"
    ADMIN = "admin"


def _normalized_role(role: str | None) -> str:
    return str(role or "").strip().lower()


# Доступ к реферальной программе в ЛК — у всех покупателей.
def user_has_referral_program(role: str | None) -> bool:
    return _normalized_role(role) == UserRole.BUYER.value


# Покупатель может быть привязан к рефереру; админ — нет.
def user_can_be_referred(role: str | None) -> bool:
    return _normalized_role(role) == UserRole.BUYER.value


# Реферером может быть только активный покупатель.
def user_can_be_referrer(role: str | None, *, is_active: bool) -> bool:
    return _normalized_role(role) == UserRole.BUYER.value and is_active


# Возвращает роль по allowlist ADMIN_TG_IDS в настройках.
def resolve_role_for_telegram_id(telegram_id: int | None) -> str:
    if telegram_id is None:
        return UserRole.BUYER.value
    tid = int(telegram_id)
    return (
        UserRole.ADMIN.value
        if tid in settings.admin_telegram_ids
        else UserRole.BUYER.value
    )
