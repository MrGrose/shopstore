from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.http_utils import register_phone_call_exception_responses
from src.api.routers.admin_order import router as admin_order_router
from src.api.routers.admin_pricing import router as admin_pricing_router
from src.api.routers.auth import router as auth_router
from src.api.routers.cart import router as cart_router
from src.api.routers.order import router as order_router
from src.api.routers.payment_sbp import router as payment_sbp_router
from src.api.routers.product import router as product_router
from src.api.routers.referral import router as referral_router
from src.api.routers.support import router as support_router
from src.api.routers.user import router as user_router
from src.core.config import (
    settings,
    validate_phone_auth_startup_settings,
    validate_sbp_startup_settings,
)
from src.deps import get_db
from src.middleware.cache_control import setup_cache_control
from src.middleware.metrics import setup_request_metrics
from src.middleware.security import setup_security
from src.storage import get_storage
from src.utils.images import (
    MEDIA_URL_PREFIX,
    product_media_key,
    public_product_media_url,
)
from src.web.admin_nav import AdminNavMiddleware
from src.web.deps import StorefrontRedirect
from src.web.router import router as web_router
from src.web.storefront_spa import (
    ready_storefront_check,
    spa_assets_dir,
    spa_public_dirs,
)
from src.web.templating import refresh_legal_template_globals

_docs_url = "/docs" if settings.api_docs_enabled else None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_sbp_startup_settings()
    validate_phone_auth_startup_settings()
    refresh_legal_template_globals()
    yield


app = FastAPI(
    title="Shopstore",
    docs_url=_docs_url,
    redoc_url="/redoc" if _docs_url else None,
    openapi_url="/openapi.json" if _docs_url else None,
    lifespan=lifespan,
)
# Настраивает security-заголовки и проверку Host.
setup_security(app)
setup_cache_control(app)
register_phone_call_exception_responses(app)
app.add_middleware(AdminNavMiddleware)
# Внешний слой: полное время запроса, включая остальные middleware.
setup_request_metrics(app)


# Обработчик перенаправления для витрины.
@app.exception_handler(StorefrontRedirect)
async def storefront_redirect_handler(
    _request: Request, exc: StorefrontRedirect
) -> RedirectResponse:
    return exc.response


@app.get("/health", tags=["ops"])
async def health_live() -> dict[str, str]:
    # Liveness: процесс отвечает по HTTP (для Docker/orchestrator без проверки БД).
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def health_ready(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    # Readiness: HTTP + БД + витрина (prod), для Docker healthcheck.
    await db.execute(text("SELECT 1"))
    readiness_error = ready_storefront_check(settings.is_dev)
    if readiness_error is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=readiness_error,
        )
    return {"status": "ok"}


app.include_router(product_router)
app.include_router(cart_router)
app.include_router(order_router)
app.include_router(payment_sbp_router)
app.include_router(user_router)
app.include_router(support_router)
app.include_router(referral_router)
app.include_router(auth_router)
app.include_router(admin_order_router)
app.include_router(admin_pricing_router)
app.include_router(web_router)

_spa_assets = spa_assets_dir()
if _spa_assets is not None:
    app.mount(
        "/assets",
        StaticFiles(directory=str(_spa_assets)),
        name="storefront-assets",
    )
for _prefix, _directory in spa_public_dirs():
    app.mount(
        _prefix,
        StaticFiles(directory=str(_directory)),
        name=f"storefront-{_directory.name}",
    )

_PRODUCT_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


# Отдаёт публичное фото товара через Storage.read, без path к диску в handler.
def _product_media_response(file_name: str) -> Response:
    suffix = Path(file_name).suffix.lower()
    media_type = _PRODUCT_MEDIA_TYPES.get(suffix)
    if media_type is None or Path(file_name).name != file_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    relative = f"{MEDIA_URL_PREFIX}/{file_name}"
    public = public_product_media_url(relative)
    if public and public != relative:
        return RedirectResponse(
            url=public,
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    try:
        data = get_storage().read(product_media_key(file_name))
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# Публичный URL-contract /media/products/{file}, как писал LocalStorage.public_url.
@app.get("/media/products/{file_name}", include_in_schema=False)
def serve_product_media(file_name: str) -> Response:
    return _product_media_response(file_name)


app.mount("/static", StaticFiles(directory="src/static"), name="static")
