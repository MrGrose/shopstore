from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.referral_cookie import read_referral_cookie
from src.core.user_roles import UserRole
from src.deps import get_db, read_access_token_from_request, resolve_user_id_from_token
from src.repositories.session import async_session_maker
from src.services.auth_service import AuthService
from src.services.login_finalize_service import finalize_login
from src.services.user_service import UserService
from src.utils.urls import safe_storefront_next_url
from src.web.admin_panel_auth import verify_admin_panel_credentials
from src.web.templating import templates

router = APIRouter(tags=["web"])


async def _admin_user_id_from_request(request: Request, db: AsyncSession) -> int | None:
    token = read_access_token_from_request(request)
    user_id = resolve_user_id_from_token(token)
    if not user_id:
        return None
    user = await UserService(db).get_user(user_id)
    if user is None or user.role != UserRole.ADMIN.value:
        return None
    return user_id


@router.get(
    "/internal/admin/login",
    response_class=HTMLResponse,
    include_in_schema=False,
    response_model=None,
)
async def admin_login_page(
    request: Request,
    next: str = Query("/internal/admin/orders"),
    db: AsyncSession = Depends(get_db),
):
    if await _admin_user_id_from_request(request, db):
        return RedirectResponse(
            url=safe_storefront_next_url(next, default="/internal/admin/orders"),
            status_code=status.HTTP_302_FOUND,
        )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/login.html",
        context={
            "next_url": safe_storefront_next_url(
                next, default="/internal/admin/orders"
            ),
            "panel_login_enabled": settings.admin_panel_login_enabled,
            "error": None,
        },
    )


@router.post(
    "/internal/admin/login", response_class=HTMLResponse, include_in_schema=False
)
async def admin_login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/internal/admin/orders"),
) -> Response:
    safe_next = safe_storefront_next_url(next, default="/internal/admin/orders")
    if not settings.admin_panel_login_enabled:
        return templates.TemplateResponse(
            request=request,
            name="site/admin/login.html",
            context={
                "next_url": safe_next,
                "panel_login_enabled": False,
                "error": (
                    "Вход по паролю не настроен "
                    "(ADMIN_PANEL_LOGIN / ADMIN_PANEL_PASSWORD)."
                ),
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not verify_admin_panel_credentials(username, password):
        return templates.TemplateResponse(
            request=request,
            name="site/admin/login.html",
            context={
                "next_url": safe_next,
                "panel_login_enabled": True,
                "error": "Неверный логин или пароль.",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    async with async_session_maker() as session:
        auth_service = AuthService(session)
        try:
            user = await auth_service.authenticate_admin_panel()
        except ValueError as exc:
            return templates.TemplateResponse(
                request=request,
                name="site/admin/login.html",
                context={
                    "next_url": safe_next,
                    "panel_login_enabled": True,
                    "error": str(exc),
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        redirect = RedirectResponse(url=safe_next, status_code=status.HTTP_302_FOUND)
        await finalize_login(
            session,
            user,
            request,
            redirect,
            referral_code=read_referral_cookie(request),
        )
    return redirect


@router.post("/internal/admin/logout", include_in_schema=False)
async def admin_logout() -> Response:
    response = RedirectResponse(
        url="/internal/admin/login", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(
        key="access_token",
        path="/",
        samesite="lax",
        secure=False,
    )
    return response
