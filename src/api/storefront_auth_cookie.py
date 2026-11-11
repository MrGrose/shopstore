from fastapi import Response

from src.core.config import settings


# Ставит JWT витрины в httpOnly cookie.
def set_storefront_auth_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=settings.ACCESS_TOKEN_TTL_SECONDS,
    )
