import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    # Логирует method, path, status_code, duration_ms, response_size.
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            (
                "http_request method=%s path=%s status_code=%s "
                "duration_ms=%s response_size=%s"
            ),
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            _response_size(response),
        )
        return response


def _response_size(response: Response) -> int:
    content_length = response.headers.get("content-length")
    if content_length is None:
        return 0
    try:
        return int(content_length)
    except ValueError:
        return 0


def setup_request_metrics(app: FastAPI) -> None:
    app.add_middleware(RequestMetricsMiddleware)
