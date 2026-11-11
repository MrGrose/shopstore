import uuid
from dataclasses import dataclass

from fastapi import Response
from starlette.requests import Request

GUEST_CART_COOKIE = "guest_cart_id"
GUEST_CART_MAX_AGE = 60 * 60 * 24 * 365


@dataclass(frozen=True)
class CartIdentity:
    user_id: int | None = None
    guest_cart_id: str | None = None

    @property
    def is_guest(self) -> bool:
        return self.guest_cart_id is not None and self.user_id is None


# Создает новый UUID для гостевой корзины.
def new_guest_cart_id() -> str:
    return str(uuid.uuid4())


# Читает guest_cart_id из cookie.
def read_guest_cart_id(request: Request) -> str | None:
    raw = request.cookies.get(GUEST_CART_COOKIE)
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


# Применяет guest_cart_id в cookie.
def apply_guest_cart_cookie(response: Response, guest_cart_id: str | None) -> None:
    if not guest_cart_id:
        return
    response.set_cookie(
        key=GUEST_CART_COOKIE,
        value=guest_cart_id,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=GUEST_CART_MAX_AGE,
    )
