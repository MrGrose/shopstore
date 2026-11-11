from dataclasses import dataclass
from urllib.parse import quote

from fastapi import Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.core.user_roles import UserRole
from src.deps import get_db, read_access_token_from_request, resolve_user_id_from_token
from src.models.user import User
from src.services.user_service import UserService


class StorefrontRedirect(Exception):
    def __init__(self, response: RedirectResponse) -> None:
        self.response = response


@dataclass(frozen=True)
class StorefrontContext:
    user_id: int | None
    is_admin: bool


def login_redirect_for_request(request: Request) -> RedirectResponse:
    raw_next = request.url.path
    if request.url.query:
        raw_next = f"{raw_next}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(raw_next, safe='/?=&')}",
        status_code=status.HTTP_302_FOUND,
    )


def admin_login_redirect_for_request(request: Request) -> RedirectResponse:
    raw_next = request.url.path
    if request.url.query:
        raw_next = f"{raw_next}?{request.url.query}"
    return RedirectResponse(
        url=f"/internal/admin/login?next={quote(raw_next, safe='/?=&')}",
        status_code=status.HTTP_302_FOUND,
    )


# Проверяет, является ли пользователь администратором.
async def user_is_admin(db: AsyncSession, user_id: int) -> bool:
    user = await UserService(db).get_user(user_id)
    return bool(user and user.role == UserRole.ADMIN.value)


# Опциональный пользователь витрины.
async def optional_storefront_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StorefrontContext:
    token = read_access_token_from_request(request)
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        return StorefrontContext(user_id=None, is_admin=False)
    is_admin = await user_is_admin(db, user_id)
    return StorefrontContext(user_id=user_id, is_admin=is_admin)


# Требует авторизованного пользователя витрины.
async def require_storefront_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StorefrontContext:
    token = read_access_token_from_request(request)
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        raise StorefrontRedirect(login_redirect_for_request(request))
    is_admin = await user_is_admin(db, user_id)
    return StorefrontContext(user_id=user_id, is_admin=is_admin)


# HTML-админка: редирект на /login, если нет cookie; иначе роль admin.
async def require_admin_user_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = read_access_token_from_request(request)
    if not token:
        raise StorefrontRedirect(admin_login_redirect_for_request(request))
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        raise StorefrontRedirect(admin_login_redirect_for_request(request))
    user = await UserService(db).get_user(user_id)
    if user is None or user.role != UserRole.ADMIN.value:
        raise StorefrontRedirect(
            RedirectResponse(url="/catalog", status_code=status.HTTP_302_FOUND),
        )
    return user
