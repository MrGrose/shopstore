from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models.user import User
from src.schemas.pricing import PromoCodeCreate
from src.services.catalog.display.pricing_nav_registry import CATALOG_SUBCATEGORIES
from src.services.pricing_service import PricingService
from src.services.promo_service import PromoService
from src.web.admin_context import admin_page_context, normalize_query_str
from src.web.deps import require_admin_user_page
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-pricing"],
    dependencies=[Depends(require_admin_user_page)],
)

EUR_RATE_HISTORY_TRIGGER_LABELS = {
    "rapira_refresh": "Rapira",
    "manual_admin": "Вручную",
    "baseline_seed": "Базовая запись",
}


def _eur_rate_history_context(rows: list) -> dict:
    page_size = PricingService.EUR_RATE_HISTORY_PAGE_SIZE
    return {
        "rows": rows,
        "has_more": len(rows) >= page_size,
        "last_id": rows[-1].id if rows else None,
        "trigger_labels": EUR_RATE_HISTORY_TRIGGER_LABELS,
    }


@router.get(
    "/internal/admin/prices",
    response_class=HTMLResponse,
    include_in_schema=False,
)
# Страница настроек цен
async def admin_prices_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error: str | None = Query(default=None),
    success: str | None = Query(default=None),
) -> HTMLResponse:
    service = PricingService(db)
    settings = await service.get_settings()
    commission_history = await service.list_service_commission_history()
    eur_history = await service.list_eur_rate_history_admin()
    eur_trend, eur_trend_dir = await service.get_eur_rate_trend_for_admin()
    return templates.TemplateResponse(
        request=request,
        name="site/admin/prices.html",
        context=admin_page_context(
            request,
            admin_user,
            settings=settings,
            commission_history=commission_history,
            eur_trend=eur_trend,
            eur_trend_dir=eur_trend_dir,
            **_eur_rate_history_context(eur_history),
            error=error,
            success=success,
        ),
    )


# Страница изменения настроек цен
@router.post(
    "/internal/admin/prices/settings",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_prices_settings_submit(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    eur_rate: str = Form(""),
    markup_multiplier: str = Form(""),
    delivery_fee_eur: str = Form(""),
    service_commission_percent: str = Form(""),
    referral_commission_percent: str = Form(""),
) -> HTMLResponse:
    service = PricingService(db)
    try:
        settings_before = await service.get_settings()
        previous_rate = settings_before.eur_rate
        referral_percent = Decimal(referral_commission_percent.replace(",", "."))
        if referral_percent < 0 or referral_percent > 100:
            raise ValueError("Реферальный % должен быть от 0 до 100")
        rate_multiplier = PricingService.normalize_markup_multiplier(
            Decimal(markup_multiplier.replace(",", "."))
        )
        if rate_multiplier <= 0:
            raise ValueError("Множитель Rapira должен быть больше 0")
        await service.update_admin_settings(
            eur_rate=Decimal(eur_rate.replace(",", ".")) if eur_rate else None,
            markup_multiplier=rate_multiplier,
            delivery_fee_eur=(
                Decimal(delivery_fee_eur.replace(",", "."))
                if delivery_fee_eur
                else None
            ),
            service_commission_percent=(
                Decimal(service_commission_percent.replace(",", "."))
                if service_commission_percent
                else None
            ),
            referral_commission_percent=referral_percent,
        )
        settings_after = await service.get_settings()
        success_msg = (
            PricingService.format_eur_rate_change_flash(
                previous_rate, settings_after.eur_rate
            )
            or "Настройки сохранены"
        )
        return await admin_prices_page(request, admin_user, db, success=success_msg)
    except (ValueError, InvalidOperation) as exc:
        return await admin_prices_page(request, admin_user, db, error=str(exc))


# Страница обновления курса EUR
@router.post(
    "/internal/admin/prices/refresh-rate",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_prices_refresh_rate(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    service = PricingService(db)
    try:
        settings_before = await service.get_settings()
        previous_rate = settings_before.eur_rate
        settings_after = await service.refresh_eur_rate()
        success_msg = (
            PricingService.format_eur_rate_change_flash(
                previous_rate, settings_after.eur_rate
            )
            or "Курс EUR обновлён"
        )
        return await admin_prices_page(request, admin_user, db, success=success_msg)
    except ValueError as exc:
        return await admin_prices_page(request, admin_user, db, error=str(exc))


@router.get(
    "/internal/admin/prices/eur-history",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_prices_eur_history_partial(
    request: Request,
    before_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    rows = await PricingService(db).list_eur_rate_history_admin(
        before_id=before_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/eur_rate_history_rows.html",
        context=_eur_rate_history_context(rows),
    )


# Страница пересчета цен всех товаров
@router.post(
    "/internal/admin/prices/recalculate",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_prices_recalculate(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    service = PricingService(db)
    try:
        updated = await service.recalculate_all_products()
        return await admin_prices_page(
            request,
            admin_user,
            db,
            success=f"Пересчитано товаров: {updated}",
        )
    except ValueError as exc:
        return await admin_prices_page(request, admin_user, db, error=str(exc))


# Страница настроек маржи
@router.get(
    "/internal/admin/margins", response_class=HTMLResponse, include_in_schema=False
)
async def admin_margins_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error: str | None = Query(default=None),
    success: str | None = Query(default=None),
    sport: str = Query(default="Padel"),
    selected: str | None = Query(default=None),
) -> HTMLResponse:
    sport_type = sport if sport in CATALOG_SUBCATEGORIES else "Padel"
    service = PricingService(db)
    data = await service.get_margin_admin_data(sport_type)
    groups = cast(list[dict[str, Any]], data["groups"])
    available_slugs = {str(group["slug"]) for group in groups}
    if data["fallback"]:
        available_slugs.add("__fallback__")
    selected_slug = selected if selected in available_slugs else None
    if selected_slug is None and groups:
        selected_slug = str(groups[0]["slug"])
    selected_rule = next(
        (group["rule"] for group in groups if group["slug"] == selected_slug),
        None,
    )
    if selected_slug == "__fallback__" and data["fallback"]:
        fallback = cast(dict[str, Any], data["fallback"])
        selected_rule = fallback["rule"]
    margin_history = (
        await service.list_margin_rule_history(selected_rule.id)
        if selected_rule is not None
        else []
    )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/margins.html",
        context=admin_page_context(
            request,
            admin_user,
            sports=("Padel", "Tennis", "Running"),
            sport_labels={"Padel": "Падел", "Tennis": "Теннис", "Running": "Бег"},
            selected_sport=sport_type,
            selected_slug=selected_slug,
            margin_groups=groups,
            fallback=data["fallback"],
            margin_history=margin_history,
            error=error,
            success=success,
        ),
    )


# Страница изменения настроек маржи
@router.post(
    "/internal/admin/margins/{rule_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_margin_update(
    request: Request,
    rule_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    margin_percent: str = Form(...),
    recalculate: str | None = Form(default=None),
    sport: str = Form("Padel"),
    selected: str | None = Form(default=None),
) -> HTMLResponse:
    service = PricingService(db)
    try:
        margin = Decimal(margin_percent.replace(",", "."))
        if margin < 0 or margin > 500:
            raise ValueError("Наценка должна быть от 0 до 500%")
        if recalculate in ("1", "on", "true"):
            _, job = await service.update_margin_rule_and_enqueue(rule_id, margin)
            msg = f"Маржа сохранена, пересчёт #{job.id} поставлен в очередь"
        else:
            await service.update_margin_rule_admin(rule_id, margin)
            msg = "Маржа сохранена"
        return await admin_margins_page(
            request,
            admin_user,
            db,
            success=msg,
            sport=sport,
            selected=selected,
        )
    except (ValueError, InvalidOperation) as exc:
        return await admin_margins_page(
            request,
            admin_user,
            db,
            error=str(exc),
            sport=sport,
            selected=selected,
        )


# HTMX-partial: текущий progress pricing job.
@router.get(
    "/internal/admin/margins/jobs/{job_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_margin_job_status(
    request: Request,
    job_id: int,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    job = await PricingService(db).repo.get_recalculation_job(job_id)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/margin_job_status.html",
        context={"job": job},
    )


# HTMX-partial: lazy-страница видимых fallback-товаров.
@router.get(
    "/internal/admin/margins/unmapped",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_margin_unmapped_products(
    request: Request,
    sport: str = Query(default="Padel"),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    sport_type = sport if sport in CATALOG_SUBCATEGORIES else "Padel"
    rows, total = await PricingService(db).get_unmapped_products(
        sport_type,
        page,
    )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/margin_unmapped_products.html",
        context={
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": 20,
            "sport": sport_type,
            "reason_labels": {
                "no_storefront_group": "Нет однозначной группы",
                "multiple_storefront_groups": "Подходит нескольким группам",
                "exact_rule_inactive": "Для группы нет активного правила",
                "sport_not_in_storefront": "Спорт не входит в витрину",
            },
        },
    )


# Страница промокодов
@router.get(
    "/internal/admin/promos", response_class=HTMLResponse, include_in_schema=False
)
async def admin_promos_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    filter_status: str = Query(default="active", alias="filter"),
    error: str | None = Query(default=None),
    success: str | None = Query(default=None),
) -> HTMLResponse:
    status_filter = normalize_query_str(filter_status, "active") or "active"
    promos, promo_filter_counts = await PromoService(db).list_promo_codes_admin_page(
        status_filter
    )
    return templates.TemplateResponse(
        request=request,
        name="site/admin/promos.html",
        context=admin_page_context(
            request,
            admin_user,
            promos=promos,
            filter_status=status_filter,
            promo_filter_counts=promo_filter_counts,
            error=error,
            success=success,
        ),
    )


# Страница создания промокода
@router.post(
    "/internal/admin/promos", response_class=HTMLResponse, include_in_schema=False
)
async def admin_promo_create(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    code: str = Form(...),
    discount_type: str = Form("percent"),
    value: str = Form(...),
    usage_mode: str = Form("multi_use"),
    active_to: str = Form(...),
) -> HTMLResponse:
    if not active_to:
        return await admin_promos_page(
            request, admin_user, db, error="Укажите дату окончания промокода"
        )
    active_to_dt = datetime.fromisoformat(f"{active_to}T23:59:59")
    payload_dict = PromoCodeCreate(
        code=code,
        discount_type=discount_type,
        value=Decimal(value.replace(",", ".")),
        usage_mode=usage_mode,
        active_to=active_to_dt,
    ).model_dump()
    service = PromoService(db)
    try:
        promo = await service.create_promo_code(payload_dict)
        return await admin_promos_page(
            request, admin_user, db, success=f"Промокод {promo.code} создан"
        )
    except ValueError as exc:
        return await admin_promos_page(request, admin_user, db, error=str(exc))


# Страница изменения статуса промокода
@router.post(
    "/internal/admin/promos/{promo_id}/toggle",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_promo_toggle(
    request: Request,
    promo_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    is_active: str = Form(...),
) -> HTMLResponse:
    next_active = is_active in ("1", "true", "on")
    service = PromoService(db)
    try:
        await service.update_promo_code(promo_id, {"is_active": next_active})
        return await admin_promos_page(
            request, admin_user, db, success="Статус промокода изменён"
        )
    except ValueError as exc:
        return await admin_promos_page(request, admin_user, db, error=str(exc))


# Страница удаления промокода
@router.post(
    "/internal/admin/promos/{promo_id}/delete",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_promo_delete(
    request: Request,
    promo_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    service = PromoService(db)
    try:
        await service.delete_promo_code(promo_id)
        return await admin_promos_page(
            request, admin_user, db, success="Промокод удалён"
        )
    except ValueError as exc:
        return await admin_promos_page(request, admin_user, db, error=str(exc))
