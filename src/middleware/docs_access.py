from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.config import settings
from src.deps import read_access_token_from_request, resolve_user_id_from_token
from src.repositories.session import async_session_maker
from src.services.identity_service import IdentityService
from src.services.user_service import UserService

_DOCS_EXACT_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


# Проверяет, является ли путь доступным для документации.
def is_docs_path(path: str) -> bool:
    return path in _DOCS_EXACT_PATHS or path.startswith("/docs/")


# Проверяет, имеет ли пользователь доступ к документации.
async def docs_access_allowed(request: Request) -> bool:
    if settings.is_dev:
        return True
    token = read_access_token_from_request(request)
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        return False
    async with async_session_maker() as session:
        user = await UserService(session).get_user(user_id)
        if user is None:
            return False
        telegram_id = await IdentityService(session).get_telegram_id_for_user(user)
    if telegram_id is None:
        return False
    if telegram_id in settings.admin_telegram_ids:
        return True
    admin_id = settings.TG_ADMIN_ID
    return admin_id > 0 and telegram_id == admin_id


# Middleware для проверки доступа к документации.
class DocsAccessMiddleware(BaseHTTPMiddleware):
    # Обрабатывает запрос.
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if is_docs_path(request.url.path) and not await docs_access_allowed(request):
            return Response(status_code=404)
        return await call_next(request)
