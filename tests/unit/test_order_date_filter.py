from datetime import date, datetime

from sqlalchemy.dialects import postgresql

from src.models.order import Order
from src.repositories.order_repo import CrudOrder
from src.utils.datetime_fmt import (
    msk_date_end_exclusive_utc_naive,
    msk_date_start_utc_naive,
)
from src.web.routers.admin_orders_pages import resolve_admin_date_range_filter


def test_msk_date_start_utc_naive() -> None:
    assert msk_date_start_utc_naive(date(2026, 7, 4)) == datetime(2026, 7, 3, 21, 0, 0)


def test_msk_date_end_exclusive_utc_naive() -> None:
    end = msk_date_end_exclusive_utc_naive(date(2026, 7, 4))
    assert end == datetime(2026, 7, 4, 21, 0, 0)


def test_msk_boundary_order_included_on_moscow_day() -> None:
    created_at = datetime(2026, 7, 3, 21, 30, 0)
    start = msk_date_start_utc_naive(date(2026, 7, 4))
    end = msk_date_end_exclusive_utc_naive(date(2026, 7, 4))
    assert start <= created_at < end


def test_resolve_admin_date_range_single_from() -> None:
    result = resolve_admin_date_range_filter("2026-07-04", None)
    assert result.error is None
    assert result.date_from == date(2026, 7, 4)
    assert result.date_to is None
    assert result.created_from_utc == msk_date_start_utc_naive(date(2026, 7, 4))
    assert result.created_to_exclusive_utc == msk_date_end_exclusive_utc_naive(
        date(2026, 7, 4)
    )


def test_resolve_admin_date_range_single_to() -> None:
    result = resolve_admin_date_range_filter(None, "2026-07-04")
    assert result.error is None
    assert result.date_to == date(2026, 7, 4)
    assert result.created_from_utc == msk_date_start_utc_naive(date(2026, 7, 4))


def test_resolve_admin_date_range_period() -> None:
    result = resolve_admin_date_range_filter("2026-07-01", "2026-07-04")
    assert result.error is None
    assert result.created_from_utc == msk_date_start_utc_naive(date(2026, 7, 1))
    assert result.created_to_exclusive_utc == msk_date_end_exclusive_utc_naive(
        date(2026, 7, 4)
    )


def test_resolve_admin_date_range_invalid_format() -> None:
    result = resolve_admin_date_range_filter("not-a-date", None)
    assert result.error == "Некорректная дата"
    assert result.created_from_utc is None


def test_resolve_admin_date_range_from_after_to() -> None:
    result = resolve_admin_date_range_filter("2026-07-10", "2026-07-01")
    assert result.error == "Дата начала позже даты окончания"
    assert result.created_from_utc is None


def test_list_all_filters_include_created_at_bounds() -> None:
    repo = CrudOrder(session=None, model=Order)  # type: ignore[arg-type]
    start = datetime(2026, 7, 1, 0, 0, 0)
    end = datetime(2026, 7, 5, 0, 0, 0)
    filters = repo._list_all_filters(
        None,
        None,
        created_from_utc=start,
        created_to_exclusive_utc=end,
    )
    assert len(filters) == 2
    compiled = str(
        filters[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert ">=" in compiled
    compiled_end = str(
        filters[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "<" in compiled_end
