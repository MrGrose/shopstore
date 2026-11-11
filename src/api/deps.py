from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.guest_cart import CartIdentity, new_guest_cart_id, read_guest_cart_id
from src.core.user_access import LOGIN_UNAVAILABLE_DETAIL, user_is_active
from src.core.user_roles import UserRole
from src.deps import get_db, read_access_token_from_request, resolve_user_id_from_token
from src.models.user import User
from src.services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False)


# Загружает пользователя по JWT; 401 если токен или user недействителен.
async def _require_user_from_token(
    db: AsyncSession,
    token: str | None,
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )
    user = await UserService(db).get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )
    if not user_is_active(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_UNAVAILABLE_DETAIL,
        )
    return user


# Возвращает текущего пользователя по Bearer или cookie.
async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = read_access_token_from_request(request, credentials)
    return await _require_user_from_token(db, token)


# Текущий пользователь с ролью admin (Bearer или cookie access_token).
async def require_admin_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = read_access_token_from_request(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
        )
    user = await UserService(db).get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав",
        )
    return user


# Текущий пользователь по Bearer или cookie; None если не авторизован.
async def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = read_access_token_from_request(request, credentials)
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        return None
    user = await UserService(db).get_user(user_id)
    if user is None or not user_is_active(user):
        return None
    return user


# Разрешает user_id по JWT/cookie access_token.
async def resolve_request_user_id(
    db: AsyncSession,
    request: Request | None = None,
) -> int:
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
        )
    token = read_access_token_from_request(request)
    user = await _require_user_from_token(db, token)
    return user.id


# Разрешает владельца корзины: JWT или гостевая cookie.
async def resolve_cart_identity(
    db: AsyncSession,
    request: Request,
) -> tuple[CartIdentity, str | None]:
    token = read_access_token_from_request(request)
    user_id = resolve_user_id_from_token(token) if token else None
    if user_id:
        user = await UserService(db).get_user(user_id)
        if user is not None and user_is_active(user):
            return CartIdentity(user_id=user_id), None
    if token:
        user = await UserService(db).get_user(user_id) if user_id else None
        detail = (
            LOGIN_UNAVAILABLE_DETAIL
            if user is not None and not user_is_active(user)
            else "Невалидный токен"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )
    existing_guest = read_guest_cart_id(request)
    if existing_guest:
        return CartIdentity(guest_cart_id=existing_guest), None
    new_guest = new_guest_cart_id()
    return CartIdentity(guest_cart_id=new_guest), new_guest
