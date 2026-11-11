from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.core.config import settings
from src.middleware.docs_access import DocsAccessMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    # Базовые security-заголовки. Без X-Frame-Options — ломает Telegram Mini App.
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.SECURITY_HSTS_MAX_AGE > 0:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={settings.SECURITY_HSTS_MAX_AGE}; includeSubDomains"
            )
        return response


def setup_security(app: FastAPI) -> None:
    # Подключает заголовки и опционально проверку Host (см. ALLOWED_HOSTS).
    app.add_middleware(SecurityHeadersMiddleware)
    hosts = settings.trusted_hosts
    if hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if settings.api_docs_enabled:
        app.add_middleware(DocsAccessMiddleware)
