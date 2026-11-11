from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.order import Order
from src.models.pricing import PromoCode, ReferralEarning
from src.models.user import User
from src.services.orders.finance_report import (
    FinancePeriodFilter,
    FinancePeriodOrderDetail,
    FinanceReportService,
    build_finance_period_promo_referral_summary,
    finance_period_order_metrics,
    format_promo_discount_value_label,
)


def test_finance_period_order_metrics_subtracts_referral_payout() -> None:
    gross, net, compensation = finance_period_order_metrics(
        turnover=Decimal("1850.00"),
        cogs_rub=Decimal("0.00"),
        delivery_rub=Decimal("500.00"),
        commission_rub=Decimal("120.25"),
        referral_payout_rub=Decimal("67.50"),
    )
    assert gross == Decimal("1350.00")
    assert net == Decimal("1162.25")
    assert compensation == Decimal("1662.25")


def _period() -> FinancePeriodFilter:
    return FinancePeriodFilter(
        date_from=date(2026, 7, 22),
        date_to=date(2026, 7, 22),
        paid_from_utc=datetime(2026, 7, 21, 21, 0),
        paid_to_exclusive_utc=datetime(2026, 7, 22, 21, 0),
        preset=None,
        error=None,
    )


def test_format_promo_discount_value_label_percent_and_fixed() -> None:
    percent = PromoCode(
        id=1,
        code="EDIT10",
        discount_type="percent",
        usage_mode="multi_use",
        value=Decimal("10.00"),
        min_order_amount=Decimal("0"),
    )
    fixed = PromoCode(
        id=2,
        code="SUMMER500",
        discount_type="fixed_rub",
        usage_mode="multi_use",
        value=Decimal("500.00"),
        min_order_amount=Decimal("0"),
    )

    assert format_promo_discount_value_label(percent) == "10%"
    assert format_promo_discount_value_label(fixed) == "500,00\u00a0₽"


def test_build_finance_period_promo_referral_summary_groups_rows() -> None:
    orders = [
        FinancePeriodOrderDetail(
            order_id=1,
            paid_at_display="",
            paid_date=date(2026, 7, 22),
            turnover=Decimal("1000"),
            cogs_rub=Decimal("500"),
            delivery_rub=Decimal("0"),
            commission_percent=Decimal("6.5"),
            commission_rub=Decimal("65"),
            gross_profit=Decimal("500"),
            net_profit=Decimal("435"),
            compensation=Decimal("565"),
            items_count=1,
            items_subtotal_rub=Decimal("0"),
            missing_cogs_snapshot=False,
            promo_code_applied="EDIT10",
            promo_discount_label="10%",
            promo_discount_rub=Decimal("100.00"),
            referral_referrer_id=20,
            referral_referrer_name="Referrer",
            referral_commission_percent=Decimal("5.00"),
            referral_commission_amount_rub=Decimal("50.00"),
            lines=[],
        ),
        FinancePeriodOrderDetail(
            order_id=2,
            paid_at_display="",
            paid_date=date(2026, 7, 22),
            turnover=Decimal("2000"),
            cogs_rub=Decimal("1000"),
            delivery_rub=Decimal("0"),
            commission_percent=Decimal("6.5"),
            commission_rub=Decimal("130"),
            gross_profit=Decimal("1000"),
            net_profit=Decimal("870"),
            compensation=Decimal("1130"),
            items_count=1,
            items_subtotal_rub=Decimal("0"),
            missing_cogs_snapshot=False,
            promo_code_applied="EDIT10",
            promo_discount_label="10%",
            promo_discount_rub=Decimal("50.00"),
            referral_referrer_id=20,
            referral_referrer_name="Referrer",
            referral_commission_percent=Decimal("5.00"),
            referral_commission_amount_rub=Decimal("25.00"),
            lines=[],
        ),
    ]

    summary = build_finance_period_promo_referral_summary(orders)

    assert summary.promo_orders_count == 2
    assert summary.promo_discount_total == Decimal("150.00")
    assert len(summary.promo_rows) == 1
    assert summary.promo_rows[0].code == "EDIT10"
    assert summary.promo_rows[0].orders_count == 2
    assert summary.promo_rows[0].discount_total == Decimal("150.00")
    assert summary.referral_orders_count == 2
    assert summary.referral_payout_total == Decimal("75.00")
    assert len(summary.referral_rows) == 1
    assert summary.referral_rows[0].referrer_id == 20


@pytest.mark.asyncio
async def test_build_period_detail_includes_promo_and_referral() -> None:
    service = FinanceReportService(AsyncMock())
    order = Order(
        id=7,
        user_id=10,
        total_amount=Decimal("10000.00"),
        discount_items_amount=Decimal("150.00"),
        delivery_fee_amount=Decimal("0.00"),
        supplier_cost_eur_snapshot=Decimal("50.00"),
        eur_rate_snapshot=Decimal("100.00"),
        payment_paid_at=datetime(2026, 7, 22, 10, 0),
        promo_code_applied="SUMMER10",
    )
    promo = PromoCode(
        id=1,
        code="SUMMER10",
        discount_type="percent",
        usage_mode="multi_use",
        value=Decimal("10.00"),
        min_order_amount=Decimal("0"),
    )
    earning = ReferralEarning(
        id=1,
        referrer_id=20,
        referred_user_id=10,
        order_id=7,
        order_amount_rub=Decimal("10000.00"),
        commission_percent=Decimal("5.00"),
        commission_amount_rub=Decimal("500.00"),
        created_at=datetime(2026, 7, 22, 12, 0, 0),
    )
    referrer = User(id=20, name="Referrer")

    service.order_crud = AsyncMock()
    service.order_crud.list_paid_orders_for_finance_detail = AsyncMock(
        return_value=[order]
    )
    service.order_crud.list_order_items_grouped = AsyncMock(return_value={7: []})
    service.session = AsyncMock()
    service.session.scalars = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[referrer]))
    )

    pricing = AsyncMock()
    pricing.list_service_commission_history = AsyncMock(return_value=[])
    pricing.get_settings = AsyncMock(
        return_value=MagicMock(service_commission_percent=Decimal("6.50"))
    )
    pricing.service_commission_percent_for_date = MagicMock(
        return_value=Decimal("6.50")
    )

    referral_repo = AsyncMock()
    referral_repo.list_earnings_by_order_ids = AsyncMock(return_value={7: earning})
    promo_repo = AsyncMock()
    promo_repo.map_by_codes = AsyncMock(return_value={"summer10": promo})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.services.orders.finance_report.PricingService",
            lambda session: pricing,
        )
        mp.setattr(
            "src.services.orders.finance_report.ReferralRepository",
            lambda session: referral_repo,
        )
        mp.setattr(
            "src.services.orders.finance_report.PromoRepository",
            lambda session: promo_repo,
        )
        detail = await service.build_period_detail(_period())

    assert len(detail.orders) == 1
    row = detail.orders[0]
    assert row.promo_code_applied == "SUMMER10"
    assert row.promo_discount_label == "10%"
    assert row.promo_discount_rub == Decimal("150.00")
    assert row.referral_referrer_id == 20
    assert row.referral_commission_amount_rub == Decimal("500.00")
    assert row.net_profit == Decimal("3850.00")
    assert row.compensation == Decimal("8850.00")
    assert detail.promo_referral_summary.promo_orders_count == 1
    assert detail.promo_referral_summary.promo_discount_total == Decimal("150.00")
    assert detail.promo_referral_summary.referral_payout_total == Decimal("500.00")
