from datetime import date, datetime
from decimal import Decimal

import pytest

from src.services.orders.finance_report import (
    FinanceReportBucket,
    finance_bucket_date_range,
    finance_bucket_row_label,
    finance_row_metrics,
    format_finance_bucket_label,
    msk_month_end,
    msk_today,
    msk_week_end,
    msk_week_start,
    resolve_finance_period,
)


def test_finance_row_metrics_with_commission_6_5():
    turnover = Decimal("10000.00")
    cogs = Decimal("6000.00")
    delivery = Decimal("500.00")
    commission = Decimal("650.00")
    gross, net, compensation = finance_row_metrics(
        turnover=turnover,
        cogs_rub=cogs,
        delivery_rub=delivery,
        commission_rub=commission,
    )
    assert gross == Decimal("3500.00")
    assert net == Decimal("2850.00")
    assert compensation == Decimal("9350.00")


def test_finance_row_metrics_with_commission_5():
    turnover = Decimal("10000.00")
    gross, net, compensation = finance_row_metrics(
        turnover=turnover,
        cogs_rub=Decimal("7000.00"),
        delivery_rub=Decimal("0.00"),
        commission_rub=Decimal("500.00"),
    )
    assert gross == Decimal("3000.00")
    assert net == Decimal("2500.00")
    assert compensation == Decimal("9500.00")


def test_resolve_finance_period_preset_today():
    today = msk_today()
    period = resolve_finance_period("today", None, None)
    assert period.date_from == today
    assert period.date_to == today
    assert period.preset == "today"
    assert period.error is None


def test_resolve_finance_period_preset_week_full_calendar():
    today = msk_today()
    period = resolve_finance_period("week", None, None)
    assert period.date_from == msk_week_start(today)
    assert period.date_to == msk_week_end(today)


def test_resolve_finance_period_preset_month_full_calendar():
    today = msk_today()
    period = resolve_finance_period("month", None, None)
    assert period.date_from == today.replace(day=1)
    assert period.date_to == msk_month_end(today)


def test_resolve_finance_period_invalid_range():
    period = resolve_finance_period(
        None,
        msk_today(),
        msk_today().replace(day=1) if msk_today().day > 1 else msk_today(),
    )
    if period.date_from > period.date_to:
        assert period.error == "Дата «от» не может быть позже даты «до»"


def test_format_finance_bucket_labels():
    day = datetime(2026, 7, 5)
    assert format_finance_bucket_label(day, FinanceReportBucket.DAY) == "05.07.2026"
    assert (
        format_finance_bucket_label(day, FinanceReportBucket.WEEK) == "05.07–11.07.2026"
    )
    assert format_finance_bucket_label(day, FinanceReportBucket.MONTH) == "07.2026"


def test_finance_bucket_date_range_day_week_month():
    day = datetime(2026, 7, 5)
    assert finance_bucket_date_range(day, FinanceReportBucket.DAY) == (
        date(2026, 7, 5),
        date(2026, 7, 5),
    )
    assert finance_bucket_date_range(day, FinanceReportBucket.WEEK) == (
        date(2026, 7, 5),
        date(2026, 7, 11),
    )
    assert finance_bucket_date_range(day, FinanceReportBucket.MONTH) == (
        date(2026, 7, 1),
        date(2026, 7, 31),
    )


def test_finance_bucket_date_range_clipped_to_period():
    monday = datetime(2026, 6, 29)
    assert finance_bucket_date_range(
        monday,
        FinanceReportBucket.WEEK,
        period_from=date(2026, 7, 1),
        period_to=date(2026, 7, 31),
    ) == (date(2026, 7, 1), date(2026, 7, 5))


def test_format_finance_bucket_label_week_clipped():
    monday = datetime(2026, 6, 29)
    assert (
        format_finance_bucket_label(
            monday,
            FinanceReportBucket.WEEK,
            period_from=date(2026, 7, 1),
            period_to=date(2026, 7, 31),
        )
        == "01.07–05.07.2026"
    )


def test_finance_bucket_row_label():
    assert finance_bucket_row_label(FinanceReportBucket.DAY) == "по дням"
    assert finance_bucket_row_label(FinanceReportBucket.WEEK) == "по неделям"
    assert finance_bucket_row_label(FinanceReportBucket.MONTH) == "по месяцам"


def test_format_finance_rub_zero_and_value():
    from src.schemas.money import format_finance_count, format_finance_rub

    assert format_finance_rub(0) == "—"
    assert format_finance_rub(None) == "—"
    assert format_finance_rub(Decimal("48320.50")) == "48\u00a0320,50\u00a0₽"
    assert format_finance_rub(Decimal("109176.67")) == "109\u00a0176,67\u00a0₽"
    assert (
        format_finance_rub(Decimal("48320.50"), with_symbol=False) == "48\u00a0320,50"
    )
    assert format_finance_count(0) == "—"
    assert format_finance_count(125) == "125"
    assert format_finance_count(12500) == "12\u00a0500"


def test_service_commission_percent_for_date():
    from datetime import date
    from decimal import Decimal

    from src.models.pricing import ServiceCommissionHistory
    from src.services.pricing_service import PricingService

    history = [
        ServiceCommissionHistory(
            id=1,
            effective_from=date(2020, 1, 1),
            commission_percent=Decimal("6.50"),
        ),
        ServiceCommissionHistory(
            id=2,
            effective_from=date(2026, 7, 6),
            commission_percent=Decimal("5.00"),
        ),
    ]
    assert PricingService.service_commission_percent_for_date(
        date(2026, 7, 5), history, Decimal("6.50")
    ) == Decimal("6.50")
    assert PricingService.service_commission_percent_for_date(
        date(2026, 7, 6), history, Decimal("6.50")
    ) == Decimal("5.00")


def test_finance_margin_percent():
    from src.schemas.money import finance_margin_percent

    assert finance_margin_percent(Decimal("3500"), Decimal("10000")) == "35"
    assert finance_margin_percent(Decimal("0"), Decimal("0")) is None


def test_finance_avg_order_rub():
    from src.schemas.money import finance_avg_order_rub

    assert finance_avg_order_rub(Decimal("50000"), 4) == "12\u00a0500,00\u00a0₽"
    assert finance_avg_order_rub(Decimal("0"), 0) is None
    assert finance_avg_order_rub(Decimal("10000"), 0) is None


def test_finance_line_item_metrics():
    from src.services.orders.finance_report import finance_line_item_metrics

    sale, cogs, margin, margin_pct, missing = finance_line_item_metrics(
        quantity=2,
        unit_price=Decimal("6300.00"),
        supplier_price_eur=Decimal("50.00"),
        eur_rate=Decimal("105.00"),
    )
    assert sale == Decimal("12600.00")
    assert cogs == Decimal("10500.00")
    assert margin == Decimal("2100.00")
    assert margin_pct == "16,7"
    assert missing is False


def test_finance_line_item_metrics_missing_snapshot():
    from src.services.orders.finance_report import finance_line_item_metrics

    sale, cogs, margin, margin_pct, missing = finance_line_item_metrics(
        quantity=1,
        unit_price=Decimal("10000.00"),
        supplier_price_eur=None,
        eur_rate=Decimal("105.00"),
    )
    assert sale == Decimal("10000.00")
    assert cogs == Decimal("0.00")
    assert margin == Decimal("10000.00")
    assert missing is True


def test_order_paid_date_msk():
    from datetime import datetime, timezone

    from src.services.orders.finance_report import order_paid_date_msk

    paid_at = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
    assert order_paid_date_msk(paid_at) == date(2026, 7, 2)


def test_build_finance_report_csv_bytes():
    from datetime import datetime

    from src.services.orders.finance_report import (
        FinancePeriodFilter,
        FinanceReportBucket,
        FinanceReportResult,
        FinanceReportRow,
        FinanceReportTotals,
        build_finance_report_csv_bytes,
    )

    period = FinancePeriodFilter(
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
        paid_from_utc=datetime(2026, 6, 30, 21, 0),
        paid_to_exclusive_utc=datetime(2026, 7, 31, 21, 0),
        preset="month",
    )
    row = FinanceReportRow(
        bucket=datetime(2026, 7, 1),
        label="01.07.2026",
        orders_count=2,
        items_count=3,
        turnover=Decimal("10000.00"),
        cogs_rub=Decimal("5000.00"),
        delivery_rub=Decimal("500.00"),
        gross_profit=Decimal("4500.00"),
        net_profit=Decimal("4000.00"),
        compensation=Decimal("3500.00"),
        paid_date_from=date(2026, 7, 1),
        paid_date_to=date(2026, 7, 1),
    )
    totals = FinanceReportTotals(
        orders_count=2,
        items_count=3,
        turnover=Decimal("10000.00"),
        cogs_rub=Decimal("5000.00"),
        delivery_rub=Decimal("500.00"),
        gross_profit=Decimal("4500.00"),
        net_profit=Decimal("4000.00"),
        compensation=Decimal("3500.00"),
    )
    report = FinanceReportResult(
        rows=[row],
        totals=totals,
        commission_percent=Decimal("6.50"),
        period=period,
        bucket=FinanceReportBucket.DAY,
    )
    body = build_finance_report_csv_bytes(report).decode("utf-8-sig")
    lines = body.strip().splitlines()
    assert lines[0].startswith("Период,Заказы,Товары")
    assert "01.07.2026,2,3,10000.00" in lines[1]
    assert lines[2].startswith("Итого,2,3,10000.00")


@pytest.mark.asyncio
async def test_aggregate_paid_orders_finance_orders_buckets_desc() -> None:
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.sql.elements import UnaryExpression

    from src.models.order import Order
    from src.repositories.order_repo import CrudOrder

    session = AsyncMock()
    captured: dict[str, object] = {}

    async def fake_execute(stmt):
        captured["stmt"] = stmt
        result = MagicMock()
        result.all.return_value = []
        return result

    session.execute = fake_execute
    crud = CrudOrder(session=session, model=Order)

    await crud.aggregate_paid_orders_finance(
        paid_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
        paid_to_exclusive=datetime(2026, 8, 1, tzinfo=timezone.utc),
        bucket="day",
    )

    stmt = captured["stmt"]
    assert stmt is not None
    order_by = list(getattr(stmt, "_order_by_clauses", ()))
    assert order_by
    assert isinstance(order_by[0], UnaryExpression)
    assert order_by[0].modifier is not None
