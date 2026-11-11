from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi import status as http_status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models.user import User
from src.schemas.order import DeliveryAddressCreate
from src.services.delivery_profile_service import DeliveryProfileService
from src.services.user_service import UserService
from src.web.admin_context import admin_page_context
from src.web.admin_labels import ORDER_STATUS_LABELS
from src.web.admin_redirect import customers_list_url
from src.web.deps import require_admin_user_page
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-customers"],
    dependencies=[Depends(require_admin_user_page)],
)


# Редирект на страницу клиентов после POST.
def _customers_redirect(
    customer_id: int | None = None,
    page: int = 1,
    q: str | None = None,
    success: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return RedirectResponse(
        url=customers_list_url(
            customer_id=customer_id,
            page=page,
            q=q,
            success=success,
            error=error,
        ),
        status_code=http_status.HTTP_303_SEE_OTHER,
    )


# Страница клиентов для админки.
@router.get(
    "/internal/admin/customers",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customers_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
    selected_id: int | None = Query(default=None, alias="id"),
    error: str | None = Query(default=None),
    success: str | None = Query(default=None),
) -> HTMLResponse:
    user_service = UserService(db)
    detail = None
    referral: dict[str, object] = {}
    referral_partners: list[User] = []
    if selected_id:
        detail = await user_service.get_admin_customer_detail(selected_id)
        if detail:
            ref = detail.get("referral")
            if isinstance(ref, dict):
                referral = ref
            partners = detail.get("referral_partners")
            if isinstance(partners, list):
                referral_partners = partners
    return templates.TemplateResponse(
        request=request,
        name="site/admin/customers.html",
        context=admin_page_context(
            request,
            admin_user,
            page=page,
            q=q or "",
            selected_id=selected_id,
            status_labels=ORDER_STATUS_LABELS,
            detail=detail,
            referral=referral,
            referral_partners=referral_partners,
            error=error,
            success=success,
        ),
    )


# Сохраняет профиль клиента из админки.
@router.post(
    "/internal/admin/customers/{user_id}/update",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_update_submit(
    request: Request,
    user_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    name: str = Form(""),
    email: str = Form(""),
    login_phone: str = Form(""),
    telegram_username: str = Form(""),
    telegram_id: str = Form(""),
    role: str = Form(""),
    is_deactivated: str = Form(""),
) -> HTMLResponse:
    try:
        await UserService(db).update_admin_customer(
            user_id,
            name=name,
            email=email,
            telegram_username=telegram_username,
            telegram_id=telegram_id,
            login_phone=login_phone,
            role=role,
            is_deactivated=is_deactivated in ("true", "on", "1"),
        )
        return _customers_redirect(
            customer_id=user_id,
            success="Профиль клиента сохранён",
        )
    except ValueError as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# Меняет реферера клиента (в т.ч. если есть выполненные заказы).
@router.post(
    "/internal/admin/customers/{user_id}/referrer",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_referrer_submit(
    request: Request,
    user_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    referrer_id: str = Form(""),
    referrer_change_reason: str = Form(""),
) -> HTMLResponse:
    raw = referrer_id.strip()
    referrer_id_int: int | None = None
    if raw:
        try:
            referrer_id_int = int(raw)
        except ValueError:
            return _customers_redirect(
                customer_id=user_id,
                error="Некорректный ID реферала",
            )
        if referrer_id_int <= 0:
            return _customers_redirect(
                customer_id=user_id,
                error="Некорректный ID реферала",
            )
    try:
        await UserService(db).set_admin_customer_referrer(
            user_id,
            referrer_id_int,
            admin_user_id=admin_user.id,
            reason=referrer_change_reason,
        )
        return _customers_redirect(
            customer_id=user_id,
            success="Реферал клиента обновлён",
        )
    except ValueError as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# Задаёт или очищает referral alias партнёра.
@router.post(
    "/internal/admin/customers/{user_id}/referral-alias",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_referral_alias_submit(
    request: Request,
    user_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    referral_alias: str = Form(""),
    clear_alias: str = Form(""),
) -> HTMLResponse:
    try:
        raw = None if clear_alias in ("true", "on", "1") else referral_alias
        await UserService(db).set_admin_customer_referral_alias(user_id, raw)
        if clear_alias in ("true", "on", "1"):
            msg = "Referral alias очищен"
        else:
            msg = "Referral alias сохранён"
        return _customers_redirect(customer_id=user_id, success=msg)
    except ValueError as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# Задаёт индивидуальный % реферальных начислений покупателя.
@router.post(
    "/internal/admin/customers/{user_id}/referral-commission",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_referral_commission_submit(
    request: Request,
    user_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    referral_commission_percent: str = Form(""),
    clear_referral_commission: str = Form(""),
) -> HTMLResponse:
    try:
        if clear_referral_commission in ("true", "on", "1"):
            percent: Decimal | None = None
        elif not referral_commission_percent.strip():
            percent = None
        else:
            percent = Decimal(referral_commission_percent.replace(",", "."))
            if percent < 0 or percent > 100:
                raise ValueError("Процент должен быть от 0 до 100")
        await UserService(db).set_admin_customer_referral_commission_percent(
            user_id, percent
        )
        if clear_referral_commission in ("true", "on", "1") or not (
            referral_commission_percent.strip()
        ):
            msg = "Индивидуальный % сброшен — используется глобальный"
        else:
            msg = "Индивидуальный % сохранён"
        return _customers_redirect(customer_id=user_id, success=msg)
    except (ValueError, InvalidOperation) as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# Удаляет клиента без заказов.
@router.post(
    "/internal/admin/customers/{user_id}/delete",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_delete_submit(
    request: Request,
    user_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        await UserService(db).delete_admin_customer(user_id)
        return _customers_redirect(success=f"Клиент #{user_id} удалён")
    except ValueError as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# POST: безвозвратно удалить выбранных клиентов.
@router.post(
    "/internal/admin/customers/delete-selected",
    response_class=JSONResponse,
    include_in_schema=False,
)
async def admin_customers_delete_selected(
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    user_ids: list[int] = Form(default=[]),
) -> JSONResponse:
    _ = admin_user
    try:
        result = await UserService(db).delete_admin_customers_by_ids(user_ids)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)


# Сохраняет профиль доставки клиента.
@router.post(
    "/internal/admin/customers/{user_id}/delivery",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_delivery_submit(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    last_name: str = Form(""),
    first_name: str = Form(""),
    street: str = Form(""),
    house: str = Form(""),
    apartment: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    phone: str = Form(""),
) -> RedirectResponse:
    try:
        payload = DeliveryAddressCreate(
            last_name=last_name,
            first_name=first_name,
            street=street,
            house=house,
            apartment=apartment or None,
            city=city,
            postal_code=postal_code,
            phone=phone,
        )
        await DeliveryProfileService(db).upsert_from_delivery(user_id, payload)
        return _customers_redirect(
            customer_id=user_id,
            success="Данные доставки сохранены",
        )
    except ValueError as exc:
        return _customers_redirect(customer_id=user_id, error=str(exc))


# Сбрасывает сохранённый профиль доставки клиента.
@router.post(
    "/internal/admin/customers/{user_id}/delivery/reset",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customer_delivery_reset_submit(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    deleted = await DeliveryProfileService(db).delete_profile(user_id)
    if not deleted:
        return _customers_redirect(
            customer_id=user_id,
            success="Профиль доставки уже пуст",
        )
    return _customers_redirect(
        customer_id=user_id,
        success="Данные доставки сброшены",
    )


# Частичный список клиентов для админки.
@router.get(
    "/internal/admin/customers/table",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_customers_table_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None),
    selected_id: int | None = Query(default=None, alias="id"),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    listed = await UserService(db).list_admin_users(
        page=page,
        page_size=page_size,
        q=q,
    )
    total_int = int(listed["total"])  # type: ignore[call-overload]
    total_pages = max(1, (total_int + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/customers_table.html",
        context=admin_page_context(
            request,
            admin_user,
            rows=listed["items"],
            total=total_int,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            q=q or "",
            selected_id=selected_id,
            customers_bulk_delete_enabled=True,
        ),
    )
