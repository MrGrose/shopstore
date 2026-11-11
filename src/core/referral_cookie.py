from fastapi import Request
from starlette.responses import Response

from src.schemas.referral import ReferralAttributionStatus

REFERRAL_COOKIE_NAME = "referral_code"
REFERRAL_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 дней


# Читает реферальный код из cookie запроса.
def read_referral_cookie(request: Request) -> str | None:
    raw = request.cookies.get(REFERRAL_COOKIE_NAME)
    if not raw:
        return None
    normalized = raw.strip()
    return normalized or None


# Cookie оставляем только при invalid_code.
def should_clear_referral_cookie(status: ReferralAttributionStatus) -> bool:
    return status != "invalid_code"


# Удаляет referral cookie с теми же атрибутами, что при установке на фронте.
def clear_referral_cookie_response(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        REFERRAL_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=secure,
    )
