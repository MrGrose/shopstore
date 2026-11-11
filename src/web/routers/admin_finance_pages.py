from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db
from src.models.user import User
from src.services.orders.finance_report import (
    FinanceReportService,
    build_finance_report_csv_bytes,
    finance_bucket_row_label,
    finance_report_export_filename,
    parse_finance_bucket,
    resolve_finance_period,
)
from src.web.admin_context import admin_page_context
from src.web.deps import require_admin_user_page
from src.web.routers.admin_orders_pages import parse_admin_date_param
from src.web.templating import templates

router = APIRouter(
    tags=["web-admin-finance"],
    dependencies=[Depends(require_admin_user_page)],
)


# Подпись периода для заголовка страниц финансов.
def _finance_period_label(date_from, date_to) -> str:
    if date_from == date_to:
        return date_from.strftime("%d.%m.%Y")
    return f"{date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}"


# Парсит query-параметры периода и группировки финансового отчёта.
def _parse_finance_report_params(
    preset: str | None,
    date_from: str | None,
    date_to: str | None,
    group: str | None,
) -> tuple:
    date_from_parsed, err_from = parse_admin_date_param(date_from)
    date_to_parsed, err_to = parse_admin_date_param(date_to)
    parse_error = err_from or err_to
    period = resolve_finance_period(
        preset=preset,
        date_from_raw=date_from_parsed,
        date_to_raw=date_to_parsed,
        parse_error=parse_error,
    )
    bucket = parse_finance_bucket(group)
    return period, bucket


# Страница финансового отчёта.
@router.get(
    "/internal/admin/finance",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_finance_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    preset: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    group: str | None = Query(default="day"),
) -> HTMLResponse:
    period, bucket = _parse_finance_report_params(preset, date_from, date_to, group)
    report = await FinanceReportService(db).build_report(period=period, bucket=bucket)
    bucket_label = finance_bucket_row_label(bucket)
    period_label = _finance_period_label(period.date_from, period.date_to)

    return templates.TemplateResponse(
        request=request,
        name="site/admin/finance.html",
        context=admin_page_context(
            request,
            admin_user,
            report=report,
            preset=period.preset or "",
            date_from=period.date_from.isoformat(),
            date_to=period.date_to.isoformat(),
            group=bucket.value,
            bucket_label=bucket_label,
            error=report.error,
            period_label=period_label,
        ),
    )


# Отдаёт CSV-выгрузку финансового отчёта по выбранному периоду и группировке.
@router.get(
    "/internal/admin/finance/export.csv",
    include_in_schema=False,
)
async def admin_finance_export_csv(
    db: AsyncSession = Depends(get_db),
    preset: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    group: str | None = Query(default="day"),
) -> Response:
    period, bucket = _parse_finance_report_params(preset, date_from, date_to, group)
    report = await FinanceReportService(db).build_report(period=period, bucket=bucket)
    if report.error:
        raise HTTPException(status_code=400, detail=report.error)
    body = build_finance_report_csv_bytes(report)
    filename = finance_report_export_filename(report.period, report.bucket)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Разбор периода: заказы и позиции для drill-down из отчёта.
@router.get(
    "/internal/admin/finance/period",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def admin_finance_period_page(
    request: Request,
    admin_user: User = Depends(require_admin_user_page),
    db: AsyncSession = Depends(get_db),
    paid_from: str | None = Query(default=None),
    paid_to: str | None = Query(default=None),
    preset: str | None = Query(default=None),
    report_date_from: str | None = Query(default=None),
    report_date_to: str | None = Query(default=None),
    group: str | None = Query(default="day"),
) -> HTMLResponse:
    paid_from_parsed, err_from = parse_admin_date_param(paid_from)
    paid_to_parsed, err_to = parse_admin_date_param(paid_to)
    parse_error = err_from or err_to
    if not paid_from or not paid_to:
        parse_error = parse_error or "Укажите период (paid_from и paid_to)"

    period = resolve_finance_period(
        preset=None,
        date_from_raw=paid_from_parsed,
        date_to_raw=paid_to_parsed,
        parse_error=parse_error,
    )
    detail = await FinanceReportService(db).build_period_detail(period=period)
    period_label = _finance_period_label(period.date_from, period.date_to)

    report_back_query = {
        "preset": preset or "",
        "date_from": report_date_from or period.date_from.isoformat(),
        "date_to": report_date_to or period.date_to.isoformat(),
        "group": parse_finance_bucket(group).value,
    }

    return templates.TemplateResponse(
        request=request,
        name="site/admin/finance_period.html",
        context=admin_page_context(
            request,
            admin_user,
            detail=detail,
            period_label=period_label,
            error=detail.error,
            report_back=report_back_query,
        ),
    )
