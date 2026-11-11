from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models.order import Order
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.services.catalog.importing.product_complete import HOLD_DOM_LAST_ERRORS
from src.web.admin_context import admin_page_context
from src.web.admin_dashboard import (
    _dom_errors_by_reason,
    build_dashboard_metrics,
    build_health_rows,
    build_parsing_overview,
    bulk_deactivate_by_dom_error,
    bulk_reset_dom_error,
    clear_stuck_dom_claims,
    count_failed_dom_products,
    count_retry_eligible_dom_products,
    deactivate_dom_failed_product,
    failed_dom_breakdown_by_sport,
    health_summary,
    load_failed_dom_products,
    oldest_dom_error_age,
    reset_dom_failed_product,
)
from src.web.admin_labels import ORDER_STATUS_LABELS
from src.web.deps import require_admin_user_page
from src.web.templating import templates

# HTML-страницы ops-раздела: дашборд, парсинг.
router = APIRouter(
    tags=["web-admin-ops"],
    dependencies=[Depends(require_admin_user_page)],
)


# HTMX: после POST обновить overview и таблицу ошибок.
_PARSING_HX_TRIGGER = "parsing-refresh"
_FAILED_PAGE_SIZE = 30


# HTMX-ответ partial алертов после POST-действий парсинга.
async def _parsing_alerts_response(
    request: Request,
    admin_user: User,
    db: AsyncSession,
    parsing_notice: str | None = None,
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    response = templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_alerts.html",
        context=_ctx(
            request,
            admin_user,
            overview=overview,
            parsing_notice=parsing_notice,
        ),
    )
    response.headers["HX-Trigger"] = _PARSING_HX_TRIGGER
    return response


# Собирает контекст partial таблицы DOM-ошибок.
async def _failed_dom_products_context(
    request: Request,
    admin_user: User,
    db: AsyncSession,
    error_filter: str | None = None,
    retry_only: bool = False,
    hold_only: bool = False,
    page: int = 1,
    action_message: str | None = None,
    action_error: str | None = None,
) -> dict[str, Any]:
    from src.scraper.config.settings import load_settings
    from src.utils.datetime_fmt import utc_now_naive
    from src.web.parsing_health import format_relative_age

    env = load_settings()
    max_attempts = max(1, env.dom_max_attempts)
    now = utc_now_naive()
    page = max(1, page)
    offset = (page - 1) * _FAILED_PAGE_SIZE
    total = await count_failed_dom_products(
        db,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        max_attempts=max_attempts,
    )
    total_pages = max(1, (total + _FAILED_PAGE_SIZE - 1) // _FAILED_PAGE_SIZE)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * _FAILED_PAGE_SIZE
    failed_products = await load_failed_dom_products(
        db,
        limit=_FAILED_PAGE_SIZE,
        offset=offset,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        max_attempts=max_attempts,
    )
    for product in failed_products:
        product.dom_error_age = format_relative_age(product.dom_last_attempt_at, now)

    errors_by_reason = await _dom_errors_by_reason(db)
    return _ctx(
        request,
        admin_user,
        failed_products=failed_products,
        error_filter=error_filter or "",
        retry_only=retry_only,
        hold_only=hold_only,
        page=page,
        total_pages=total_pages,
        failed_total=total,
        errors_by_reason=errors_by_reason,
        errors_total=sum(errors_by_reason.values()),
        retry_eligible=await count_retry_eligible_dom_products(db, max_attempts),
        hold_eligible=await count_failed_dom_products(
            db, hold_only=True, max_attempts=max_attempts
        ),
        hold_dom_errors=HOLD_DOM_LAST_ERRORS,
        max_attempts=max_attempts,
        oldest_error_age=await oldest_dom_error_age(db, now),
        failure_breakdown=await failed_dom_breakdown_by_sport(db),
        action_message=action_message,
        action_error=action_error,
    )


# Рендер partial таблицы DOM-ошибок.
async def _failed_dom_products_partial(
    request: Request,
    admin_user: User,
    db: AsyncSession,
    error_filter: str | None = None,
    retry_only: bool = False,
    hold_only: bool = False,
    page: int = 1,
    action_message: str | None = None,
    action_error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_failed_products.html",
        context=await _failed_dom_products_context(
            request,
            admin_user,
            db,
            error_filter=error_filter,
            retry_only=retry_only,
            hold_only=hold_only,
            page=page,
            action_message=action_message,
            action_error=action_error,
        ),
    )


# Собирает контекст Jinja для страниц админки (навигация, flash, extra).
def _ctx(
    request: Request,
    admin_user: User,
    error: str | None = None,
    success: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return admin_page_context(
        request,
        admin_user,
        error=error,
        success=success,
        **extra,
    )


# Последние заказы для дашборда (новые сверху).
async def _recent_orders(db: AsyncSession, limit: int = 8) -> list[Order]:
    repo = CrudOrder(db, Order)
    return await repo.list_all(limit=limit, offset=0)


# Заказы + имя покупателя для таблицы на дашборде.
async def _recent_order_rows(
    db: AsyncSession, limit: int = 8
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for order in await _recent_orders(db, limit=limit):
        user = await db.get(User, order.user_id) if order.user_id else None
        rows.append(
            {
                "order": order,
                "user_name": user.name if user else None,
            }
        )
    return rows


# Главная страница дашборда: метрики, здоровье, заказы, парсинг.
@router.get(
    "/internal/admin/dashboard", response_class=HTMLResponse, include_in_schema=False
)
async def admin_dashboard_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    metrics = await build_dashboard_metrics(db)
    health_rows = await build_health_rows(db)
    metrics["health"] = health_summary(health_rows)
    recent_order_rows = await _recent_order_rows(db)
    parsing_overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/dashboard.html",
        context=_ctx(
            request,
            admin_user,
            success=success,
            error=error,
            metrics=metrics,
            recent_order_rows=recent_order_rows,
            health_rows=health_rows,
            parsing=parsing_overview["parsing"],
            session_file=parsing_overview["session_file"],
            status_labels=ORDER_STATUS_LABELS,
        ),
    )


# HTMX-partial: блок «Парсинг каталога» на дашборде (poll / обновить).
@router.get(
    "/internal/admin/dashboard/parsing",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_dashboard_parsing_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/dashboard_parsing_mini.html",
        context=_ctx(
            request,
            admin_user,
            parsing=overview["parsing"],
            session_file=overview["session_file"],
        ),
    )


# HTMX-partial: «Состояние системы» на дашборде.
@router.get(
    "/internal/admin/dashboard/health",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_dashboard_health_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    health_rows = await build_health_rows(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/dashboard_health.html",
        context=_ctx(request, admin_user, health_rows=health_rows),
    )


# HTMX-partial: таблица «Последние заказы» на дашборде.
@router.get(
    "/internal/admin/dashboard/recent-orders",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_dashboard_recent_orders_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    recent_order_rows = await _recent_order_rows(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/dashboard_recent_orders.html",
        context=_ctx(
            request,
            admin_user,
            recent_order_rows=recent_order_rows,
            status_labels=ORDER_STATUS_LABELS,
        ),
    )


# HTMX-partial: четыре карточки метрик сверху дашборда.
@router.get(
    "/internal/admin/dashboard/metrics",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_dashboard_metrics_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    metrics = await build_dashboard_metrics(db)
    health_rows = await build_health_rows(db)
    metrics["health"] = health_summary(health_rows)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/dashboard_metrics.html",
        context=_ctx(request, admin_user, metrics=metrics),
    )


# Страница «Парсинг»: очереди и товары с ошибками DOM-скрапинга.
@router.get(
    "/internal/admin/parsing", response_class=HTMLResponse, include_in_schema=False
)
async def admin_parsing_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str | None = Query(default=None),
    retry_only: bool = Query(default=False),
    hold_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    context = await _failed_dom_products_context(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        page=page,
    )
    context["overview"] = overview
    context["success"] = success
    context["error"] = error
    return templates.TemplateResponse(
        request=request,
        name="site/admin/parsing.html",
        context=context,
    )


# HTMX-partial: центр алертов парсинга.
@router.get(
    "/internal/admin/parsing/alerts",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_alerts_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_alerts.html",
        context=_ctx(request, admin_user, overview=overview),
    )


# HTMX-partial: визуализация пайплайна.
@router.get(
    "/internal/admin/parsing/pipeline",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_pipeline_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_pipeline.html",
        context=_ctx(request, admin_user, overview=overview),
    )


# HTMX-partial: метрики и воркеры парсинга.
@router.get(
    "/internal/admin/parsing/metrics",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_metrics_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_sidebar.html",
        context=_ctx(request, admin_user, overview=overview),
    )


# HTMX-partial: технические метрики парсинга.
@router.get(
    "/internal/admin/parsing/technical",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_technical_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    overview = await build_parsing_overview(db)
    return templates.TemplateResponse(
        request=request,
        name="site/admin/partials/parsing_technical.html",
        context=_ctx(request, admin_user, overview=overview),
    )


# HTMX POST: удалить failed jobs из catalog-очередей RQ.
@router.post(
    "/internal/admin/parsing/clear-failed-jobs",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_clear_failed_jobs(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from src.jobs.queue import clear_all_catalog_failed_jobs

    counts = clear_all_catalog_failed_jobs()
    return await _parsing_alerts_response(
        request,
        admin_user,
        db,
        parsing_notice=(
            f"Очищено failed jobs: DOM {counts['dom']}, "
            f"import {counts['import']}, finalize {counts['finalize']}, "
            f"translation {counts['translation']}"
        ),
    )


# HTMX POST: сброс просроченных dom_processing меток.
@router.post(
    "/internal/admin/parsing/clear-stuck-claims",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_clear_stuck_claims(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    cleared = await clear_stuck_dom_claims(db)
    return await _parsing_alerts_response(
        request,
        admin_user,
        db,
        parsing_notice=f"Очищено меток: {cleared}",
    )


# HTMX POST: ручной тик DOM scheduler (дублирует cron при необходимости).
@router.post(
    "/internal/admin/parsing/backfill",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_backfill(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from src.jobs.dom_scheduler import enqueue_dom_scheduler
    from src.jobs.queue import dom_queue_overloaded
    from src.scraper.config.settings import load_settings

    env = load_settings()
    if dom_queue_overloaded(env):
        notice = "DOM scheduler: пропуск — очередь перегружена"
        enqueued = 0
    else:
        result = await enqueue_dom_scheduler()
        enqueued = int(result.get("enqueued_products") or 0)
        notice = (
            f"DOM scheduler: поставлено {enqueued} SKU"
            if enqueued
            else "DOM scheduler: нет подходящих SKU"
        )
    return await _parsing_alerts_response(
        request,
        admin_user,
        db,
        parsing_notice=notice,
    )


# HTMX POST: переотправить зависшие DOM jobs (watchdog --apply).
@router.post(
    "/internal/admin/parsing/watchdog",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_watchdog(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from src.jobs.admin_job_snapshots import (
        DOM_WATCHDOG_SNAPSHOT,
        save_admin_job_snapshot,
    )
    from src.jobs.dom_watchdog import run_dom_watchdog

    result = run_dom_watchdog(apply=True)
    save_admin_job_snapshot(
        DOM_WATCHDOG_SNAPSHOT,
        {
            "ok": True,
            "apply": True,
            "checked": result.checked,
            "requeued": result.requeued,
            "skipped_active": result.skipped_active,
            "skipped_fresh": result.skipped_fresh,
            "missing": result.missing,
        },
    )
    return await _parsing_alerts_response(
        request,
        admin_user,
        db,
        parsing_notice=(
            f"Страж DOM: проверено {result.checked}, переотправлено {result.requeued}"
        ),
    )


# HTMX-partial: таблица товаров с DOM-ошибками.
@router.get(
    "/internal/admin/parsing/failed-products",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_failed_products_partial(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str | None = Query(default=None),
    retry_only: bool = Query(default=False),
    hold_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    return await _failed_dom_products_partial(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        page=page,
    )


# HTMX POST: снять один товар с витрины.
@router.post(
    "/internal/admin/parsing/products/{product_id}/deactivate",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_deactivate_product(
    request: Request,
    product_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str | None = Query(default=None),
    retry_only: bool = Query(default=False),
    hold_only: bool = Query(default=False),
) -> HTMLResponse:
    action_error = await deactivate_dom_failed_product(db, product_id)
    response = await _failed_dom_products_partial(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        action_message=None if action_error else f"#{product_id} снят с витрины",
        action_error=action_error,
    )
    if not action_error:
        response.headers["HX-Trigger"] = _PARSING_HX_TRIGGER
    return response


# HTMX POST: сбросить DOM-ошибку у одного товара.
@router.post(
    "/internal/admin/parsing/products/{product_id}/reset-error",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_reset_product_error(
    request: Request,
    product_id: int,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str | None = Query(default=None),
    retry_only: bool = Query(default=False),
    hold_only: bool = Query(default=False),
) -> HTMLResponse:
    action_error = await reset_dom_failed_product(db, product_id)
    response = await _failed_dom_products_partial(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        retry_only=retry_only,
        hold_only=hold_only,
        action_message=None if action_error else f"#{product_id}: ошибка сброшена",
        action_error=action_error,
    )
    if not action_error:
        response.headers["HX-Trigger"] = _PARSING_HX_TRIGGER
    return response


# HTMX POST: массово снять с витрины по типу ошибки.
@router.post(
    "/internal/admin/parsing/bulk/deactivate",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_bulk_deactivate(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str = Query(...),
) -> HTMLResponse:
    updated = await bulk_deactivate_by_dom_error(db, error_filter)
    response = await _failed_dom_products_partial(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        action_message=f"Снято с витрины: {updated} ({error_filter})",
    )
    if updated:
        response.headers["HX-Trigger"] = _PARSING_HX_TRIGGER
    return response


# HTMX POST: массово сбросить DOM-ошибку по типу.
@router.post(
    "/internal/admin/parsing/bulk/reset-error",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_parsing_bulk_reset_error(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    error_filter: str = Query(...),
) -> HTMLResponse:
    updated = await bulk_reset_dom_error(db, error_filter)
    response = await _failed_dom_products_partial(
        request,
        admin_user,
        db,
        error_filter=error_filter,
        action_message=f"Сброшено ошибок: {updated} ({error_filter})",
    )
    if updated:
        response.headers["HX-Trigger"] = _PARSING_HX_TRIGGER
    return response
