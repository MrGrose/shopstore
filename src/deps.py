from collections.abc import AsyncGenerator

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import verify_access_token
from src.repositories.session import async_session_maker


# Получает асинхронную сессию БД.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


# Читает access_token из запроса.
def read_access_token_from_request(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> str | None:
    token: str | None = None
    if credentials:
        token = credentials.credentials
    if not token:
        auth_header = request.headers.get("Authorization", "")
        scheme, _, header_token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and header_token.strip():
            token = header_token.strip()
    if not token:
        token = request.cookies.get("access_token")
    return token


# Разрешает user_id по access_token.
def resolve_user_id_from_token(token: str | None) -> int | None:
    if not token:
        return None
    return verify_access_token(token)
