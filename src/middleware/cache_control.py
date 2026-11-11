from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

NO_STORE = "no-store"


@dataclass(frozen=True)
class CachePolicy:
    cache_control: str
    vary: str | None = None


# Возвращает HTTP cache policy для пути и метода запроса.
def resolve_cache_policy(method: str, path: str) -> CachePolicy:
    if method.upper() != "GET":
        return CachePolicy(NO_STORE)

    if path in ("/health", "/ready"):
        return CachePolicy(NO_STORE)

    if path.startswith(
        (
            "/cart",
            "/users",
            "/orders",
            "/auth",
            "/support",
            "/referral",
            "/payments",
            "/admin",
            "/internal",
        )
    ):
        return CachePolicy(NO_STORE)

    if path.startswith("/products/catalog/"):
        return CachePolicy(NO_STORE)

    exact: dict[str, CachePolicy] = {
        "/catalog/taxonomy": CachePolicy(
            "public, max-age=300, stale-while-revalidate=3600"
        ),
        "/catalog/navigation": CachePolicy(
            "public, max-age=60, stale-while-revalidate=300"
        ),
        "/catalog/labels": CachePolicy(
            "public, max-age=300, stale-while-revalidate=3600"
        ),
        "/products": CachePolicy("public, max-age=30, stale-while-revalidate=120"),
        "/products/count": CachePolicy(
            "public, max-age=60, stale-while-revalidate=300"
        ),
        "/products/facets": CachePolicy(
            "public, max-age=60, stale-while-revalidate=300"
        ),
        "/products/meta": CachePolicy("public, max-age=60, stale-while-revalidate=300"),
        "/products/subcategories": CachePolicy(
            "public, max-age=60, stale-while-revalidate=300"
        ),
    }
    if path in exact:
        return exact[path]

    if path.startswith("/products/"):
        return CachePolicy("public, max-age=60, stale-while-revalidate=300")

    if path.startswith("/product/") and path.count("/") == 2:
        return CachePolicy("public, max-age=60, stale-while-revalidate=300")

    if path.startswith("/media/products/"):
        return CachePolicy("public, max-age=31536000, immutable")

    return CachePolicy(NO_STORE)


class CacheControlMiddleware(BaseHTTPMiddleware):
    # Устанавливает Cache-Control и Vary для публичных read-only API.
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if response.headers.get("Cache-Control"):
            return response
        policy = resolve_cache_policy(request.method, request.url.path)
        response.headers["Cache-Control"] = policy.cache_control
        if policy.vary:
            response.headers["Vary"] = policy.vary
        return response


def setup_cache_control(app: FastAPI) -> None:
    app.add_middleware(CacheControlMiddleware)
