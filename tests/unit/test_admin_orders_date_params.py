from pathlib import Path

from src.services.orders.order_service import normalize_admin_order_status_filter
from src.web.admin_redirect import orders_list_url
from src.web.routers.admin_orders_pages import parse_admin_date_param
from src.web.templating import admin_orders_query


def test_parse_admin_date_param_valid() -> None:
    parsed, error = parse_admin_date_param("2026-07-04")
    assert error is None
    assert parsed is not None
    assert parsed.isoformat() == "2026-07-04"


def test_parse_admin_date_param_empty() -> None:
    parsed, error = parse_admin_date_param("")
    assert parsed is None
    assert error is None


def test_parse_admin_date_param_invalid() -> None:
    parsed, error = parse_admin_date_param("04-07-2026")
    assert parsed is None
    assert error == "Некорректная дата"


def test_orders_list_url_with_dates() -> None:
    url = orders_list_url(
        page=2,
        q="ivan",
        status="processing",
        date_from="2026-07-01",
        date_to="2026-07-04",
    )
    assert "date_from=2026-07-01" in url
    assert "date_to=2026-07-04" in url
    assert "page=2" in url
    assert "q=ivan" in url
    assert "status=processing" in url


def test_orders_list_url_without_dates() -> None:
    url = orders_list_url(page=1)
    assert "date_from" not in url
    assert "date_to" not in url


def test_admin_orders_query_order_link() -> None:
    qs = admin_orders_query(
        page=3,
        q="42",
        status="created",
        date_from="2026-07-01",
        date_to="2026-07-04",
        order_id=99,
    )
    assert "id=99" in qs
    assert "date_from=2026-07-01" in qs
    assert "date_to=2026-07-04" in qs


def test_normalize_admin_order_status_filter_single() -> None:
    assert normalize_admin_order_status_filter("processing") == ["processing"]


def test_normalize_admin_order_status_filter_multi() -> None:
    assert normalize_admin_order_status_filter("created,processing,delivery") == [
        "created",
        "processing",
        "delivery",
    ]


def test_normalize_admin_order_status_filter_ignores_invalid() -> None:
    assert normalize_admin_order_status_filter("created,unknown,processing") == [
        "created",
        "processing",
    ]


def test_normalize_admin_order_status_filter_empty() -> None:
    assert normalize_admin_order_status_filter("") is None
    assert normalize_admin_order_status_filter(None) is None


def test_date_range_picker_partial_markup() -> None:
    template = (
        Path(__file__).resolve().parents[2]
        / "src/templates/site/admin/partials/_date_range_picker.html"
    ).read_text(encoding="utf-8")
    assert "data-date-range-picker" in template
    assert 'name="date_from"' in template
    assert 'name="date_to"' in template
    assert "data-date-range-apply" in template
