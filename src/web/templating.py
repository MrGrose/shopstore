from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

from src.core.customer_activity import customer_activity_status
from src.schemas.money import (
    finance_avg_order_rub,
    finance_margin_percent,
    format_eur,
    format_finance_count,
    format_finance_rub,
    format_grouped_count,
    format_rub,
)
from src.services.catalog.read.scope import CATALOG_TOP_ORDER
from src.services.catalog.read.sort import (
    CATALOG_ADMIN_SORT_OPTIONS,
    CATALOG_SORT_PRICE_OPTIONS,
)
from src.services.pricing_service import PricingService
from src.utils.datetime_fmt import (
    format_datetime_msk,
    format_datetime_msk_short,
    format_iso_datetime_msk_short,
)
from src.utils.labels import (
    translate_category_l2,
    translate_gender,
    translate_sport_type,
)
from src.utils.pagination import pagination_page_window
from src.web.admin_customer_status import CUSTOMER_ACTIVITY_LABELS
from src.web.admin_icons import admin_icon
from src.web.admin_labels import USER_ROLE_LABELS
from src.web.storefront_legal import storefront_legal_context


# Собирает query string для ссылок списка заказов в админке.
def admin_orders_query(
    page: int = 1,
    q: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    paid_from: str | None = None,
    paid_to: str | None = None,
    order_id: int | None = None,
    queue: str | None = None,
) -> str:
    query: dict[str, str] = {"page": str(max(1, page))}
    if q:
        query["q"] = q
    if status:
        query["status"] = status
    if queue:
        query["queue"] = queue
    if date_from:
        query["date_from"] = date_from
    if date_to:
        query["date_to"] = date_to
    if paid_from:
        query["paid_from"] = paid_from
    if paid_to:
        query["paid_to"] = paid_to
    if order_id is not None:
        query["id"] = str(order_id)
    return urlencode(query)


# Собирает query string для финансового отчёта в админке.
def admin_finance_query(
    preset: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    group: str | None = None,
) -> str:
    query: dict[str, str] = {}
    if preset:
        query["preset"] = preset
    if date_from:
        query["date_from"] = date_from
    if date_to:
        query["date_to"] = date_to
    if group:
        query["group"] = group
    return urlencode(query)


# Собирает query string для разбора периода + возврат к отчёту.
def admin_finance_period_query(
    paid_from: str,
    paid_to: str,
    preset: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    group: str | None = None,
) -> str:
    query: dict[str, str] = {
        "paid_from": paid_from,
        "paid_to": paid_to,
    }
    if preset:
        query["preset"] = preset
    if date_from:
        query["report_date_from"] = date_from
    if date_to:
        query["report_date_to"] = date_to
    if group:
        query["group"] = group
    return urlencode(query)


# Собирает query string для списка обращений в админке.
def admin_support_query(
    page: int = 1,
    status: str | None = None,
    order_id: int | None = None,
    ticket_id: int | None = None,
) -> str:
    query: dict[str, str] = {}
    if ticket_id is not None:
        query["id"] = str(ticket_id)
    if page > 1:
        query["page"] = str(page)
    if status:
        query["status"] = status
    if order_id is not None:
        query["order_id"] = str(order_id)
    return urlencode(query)


# Заказ считается «новым» для бейджа в админке, если создан за последние N часов.
def admin_order_is_new(created_at: datetime | None, *, hours: int = 24) -> bool:
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return created_at >= cutoff


# Общий Jinja2-движок: HTML-шаблоны сайта, админки, бота.
templates = Jinja2Templates(directory="src/templates")
templates.env.globals["admin_icon"] = admin_icon
templates.env.globals["customer_activity_labels"] = CUSTOMER_ACTIVITY_LABELS
templates.env.globals["customer_activity_status"] = customer_activity_status
templates.env.globals["user_role_labels"] = USER_ROLE_LABELS
templates.env.globals["admin_orders_query"] = admin_orders_query
templates.env.globals["admin_finance_query"] = admin_finance_query
templates.env.globals["admin_finance_period_query"] = admin_finance_period_query
templates.env.globals["admin_support_query"] = admin_support_query
templates.env.globals["admin_order_is_new"] = admin_order_is_new
templates.env.globals["translate_gender"] = translate_gender
templates.env.globals["translate_sport_type"] = translate_sport_type
templates.env.globals["translate_category_l2"] = translate_category_l2
templates.env.globals["format_datetime_msk"] = format_datetime_msk
templates.env.globals["format_datetime_msk_short"] = format_datetime_msk_short
templates.env.globals["format_iso_datetime_msk_short"] = format_iso_datetime_msk_short
templates.env.globals["format_eur"] = format_eur
templates.env.globals["format_eur_rate_source_display"] = (
    PricingService.format_eur_rate_source_display
)
templates.env.globals["format_rub"] = format_rub
templates.env.globals["format_finance_rub"] = format_finance_rub
templates.env.globals["format_finance_count"] = format_finance_count
templates.env.globals["format_grouped_count"] = format_grouped_count
templates.env.globals["finance_margin_percent"] = finance_margin_percent
templates.env.globals["finance_avg_order_rub"] = finance_avg_order_rub
templates.env.globals["pagination_page_window"] = pagination_page_window
templates.env.globals["catalog_sort_price_options"] = CATALOG_SORT_PRICE_OPTIONS
templates.env.globals["catalog_admin_sort_options"] = CATALOG_ADMIN_SORT_OPTIONS
templates.env.globals["catalog_top_order"] = CATALOG_TOP_ORDER
# Обновляется при каждом импорте модуля; после смены .env — restart api.
templates.env.globals["legal"] = storefront_legal_context()


# Обновляет контекст юридических страниц.
def refresh_legal_template_globals() -> None:
    templates.env.globals["legal"] = storefront_legal_context()
