import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.user_display import user_display_label
from src.models.order import Order, OrderItem, variant_label_from_options
from src.models.pricing import PromoCode
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.repositories.promo_repo import PromoRepository
from src.repositories.referral_repo import ReferralRepository
from src.schemas.money import finance_margin_percent, format_finance_rub
from src.services.pricing_service import PricingService
from src.utils.datetime_fmt import (
    MSK,
    format_datetime_msk,
    msk_date_end_exclusive_utc_naive,
    msk_date_start_utc_naive,
    msk_today,
)


class FinanceReportBucket(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


FINANCE_PRESETS = frozenset({"today", "yesterday", "week", "month"})

FINANCE_REPORT_CSV_FIELDS = [
    "Период",
    "Заказы",
    "Товары",
    "Оборот",
    "Себестоимость",
    "Доставка",
    "ВП",
    "ЧП",
    "Компенсация",
]


# Период финансового отчёта.
@dataclass(frozen=True)
class FinancePeriodFilter:
    date_from: date
    date_to: date
    paid_from_utc: datetime
    paid_to_exclusive_utc: datetime
    preset: str | None
    error: str | None = None


# Строка финансового отчёта.
@dataclass(frozen=True)
class FinanceReportRow:
    bucket: datetime
    label: str
    orders_count: int
    items_count: int
    turnover: Decimal
    cogs_rub: Decimal
    delivery_rub: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    compensation: Decimal
    paid_date_from: date
    paid_date_to: date


# Итоги финансового отчёта.
@dataclass(frozen=True)
class FinanceReportTotals:
    orders_count: int
    items_count: int
    turnover: Decimal
    cogs_rub: Decimal
    delivery_rub: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    compensation: Decimal


# Результат финансового отчёта.
@dataclass(frozen=True)
class FinanceReportResult:
    rows: list[FinanceReportRow]
    totals: FinanceReportTotals
    commission_percent: Decimal
    period: FinancePeriodFilter
    bucket: FinanceReportBucket
    error: str | None = None


@dataclass(frozen=True)
class FinancePeriodLineItem:
    title: str
    variant_label: str | None
    quantity: int
    unit_price: Decimal
    sale_rub: Decimal
    supplier_price_eur: Decimal | None
    eur_rate: Decimal
    cogs_rub: Decimal
    margin_rub: Decimal
    margin_percent: str | None
    missing_snapshot: bool


@dataclass(frozen=True)
class FinancePeriodPromoCodeRow:
    code: str
    discount_label: str
    orders_count: int
    discount_total: Decimal


@dataclass(frozen=True)
class FinancePeriodReferrerRow:
    referrer_id: int
    referrer_name: str
    orders_count: int
    payout_total: Decimal


@dataclass(frozen=True)
class FinancePeriodPromoReferralSummary:
    promo_orders_count: int
    promo_discount_total: Decimal
    promo_rows: list[FinancePeriodPromoCodeRow]
    referral_orders_count: int
    referral_payout_total: Decimal
    referral_rows: list[FinancePeriodReferrerRow]


@dataclass(frozen=True)
class FinancePeriodOrderDetail:
    order_id: int
    paid_at_display: str
    paid_date: date
    turnover: Decimal
    cogs_rub: Decimal
    delivery_rub: Decimal
    commission_percent: Decimal
    commission_rub: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    compensation: Decimal
    items_count: int
    items_subtotal_rub: Decimal
    missing_cogs_snapshot: bool
    promo_code_applied: str | None
    promo_discount_label: str | None
    promo_discount_rub: Decimal | None
    referral_referrer_id: int | None
    referral_referrer_name: str | None
    referral_commission_percent: Decimal | None
    referral_commission_amount_rub: Decimal | None
    lines: list[FinancePeriodLineItem]


@dataclass(frozen=True)
class FinancePeriodDetailResult:
    period: FinancePeriodFilter
    orders: list[FinancePeriodOrderDetail]
    totals: FinanceReportTotals
    promo_referral_summary: FinancePeriodPromoReferralSummary
    error: str | None = None


# Понедельник текущей недели (MSK).
def msk_week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


# Воскресенье недели, в которую попадает дата (MSK).
def msk_week_end(value: date) -> date:
    return msk_week_start(value) + timedelta(days=6)


# Последний день месяца для даты (MSK).
def msk_month_end(value: date) -> date:
    if value.month == 12:
        next_month = date(value.year + 1, 1, 1)
    else:
        next_month = date(value.year, value.month + 1, 1)
    return next_month - timedelta(days=1)


# Считает метрики одной строки отчёта по сумме комиссии.
def finance_row_metrics(
    turnover: Decimal,
    cogs_rub: Decimal,
    delivery_rub: Decimal,
    commission_rub: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    gross_profit = (turnover - cogs_rub - delivery_rub).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    net_profit = (gross_profit - commission_rub).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    compensation = (turnover - commission_rub).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return gross_profit, net_profit, compensation


# Считает метрики позиции заказа для разбора периода.


# Метрики заказа для разбора периода: ЧП и компенсация минус реферальное начисление.
def finance_period_order_metrics(
    turnover: Decimal,
    cogs_rub: Decimal,
    delivery_rub: Decimal,
    commission_rub: Decimal,
    referral_payout_rub: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal]:
    gross_profit, net_profit, compensation = finance_row_metrics(
        turnover,
        cogs_rub,
        delivery_rub,
        commission_rub,
    )
    payout = referral_payout_rub or Decimal("0.00")
    if payout <= 0:
        return gross_profit, net_profit, compensation
    net_profit = (net_profit - payout).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    compensation = (compensation - payout).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return gross_profit, net_profit, compensation


def finance_line_item_metrics(
    quantity: int,
    unit_price: Decimal,
    supplier_price_eur: Decimal | None,
    eur_rate: Decimal,
) -> tuple[Decimal, Decimal, Decimal, str | None, bool]:
    qty = int(quantity)
    sale_rub = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    supplier_eur = Decimal("0")
    missing_snapshot = supplier_price_eur is None
    if supplier_price_eur is not None:
        supplier_eur = Decimal(str(supplier_price_eur))
    cogs_rub = (supplier_eur * qty * eur_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    margin_rub = (sale_rub - cogs_rub).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    margin_percent = finance_margin_percent(margin_rub, sale_rub)
    return sale_rub, cogs_rub, margin_rub, margin_percent, missing_snapshot


# Дата оплаты заказа в MSK.
def order_paid_date_msk(payment_paid_at: datetime | None) -> date | None:
    if payment_paid_at is None:
        return None
    if payment_paid_at.tzinfo is None:
        paid_at = payment_paid_at.replace(tzinfo=timezone.utc)
    else:
        paid_at = payment_paid_at
    return paid_at.astimezone(MSK).date()


# Подпись варианта из snapshot позиции заказа.
def _order_item_variant_label(item: OrderItem) -> str | None:
    return variant_label_from_options(
        item.variant_option1_captured,
        item.variant_option2_captured,
        item.variant_option3_captured,
        separator=", ",
    )


# Диапазон дат MSK для bucket строки отчёта (для ссылок в список заказов).
def finance_bucket_date_range(
    bucket: datetime,
    granularity: FinanceReportBucket,
    period_from: date | None = None,
    period_to: date | None = None,
) -> tuple[date, date]:
    bucket_date = bucket.date() if isinstance(bucket, datetime) else bucket
    if granularity == FinanceReportBucket.DAY:
        row_from = row_to = bucket_date
    elif granularity == FinanceReportBucket.WEEK:
        row_from = bucket_date
        row_to = bucket_date + timedelta(days=6)
    else:
        row_from = bucket_date.replace(day=1)
        if row_from.month == 12:
            next_month = date(row_from.year + 1, 1, 1)
        else:
            next_month = date(row_from.year, row_from.month + 1, 1)
        row_to = next_month - timedelta(days=1)

    if period_from is not None and row_from < period_from:
        row_from = period_from
    if period_to is not None and row_to > period_to:
        row_to = period_to
    return row_from, row_to


# Форматирует подпись bucket для таблицы.
def format_finance_bucket_label(
    bucket: datetime,
    granularity: FinanceReportBucket,
    period_from: date | None = None,
    period_to: date | None = None,
) -> str:
    bucket_date = bucket.date() if isinstance(bucket, datetime) else bucket
    if granularity == FinanceReportBucket.DAY:
        return bucket_date.strftime("%d.%m.%Y")
    if granularity == FinanceReportBucket.WEEK:
        week_from, week_to = finance_bucket_date_range(
            bucket,
            FinanceReportBucket.WEEK,
            period_from,
            period_to,
        )
        return f"{week_from.strftime('%d.%m')}–{week_to.strftime('%d.%m.%Y')}"
    month_from, month_to = finance_bucket_date_range(
        bucket,
        FinanceReportBucket.MONTH,
        period_from,
        period_to,
    )
    if month_from == month_to:
        return month_from.strftime("%d.%m.%Y")
    if month_from.month == month_to.month and month_from.year == month_to.year:
        return month_from.strftime("%m.%Y")
    return f"{month_from.strftime('%d.%m')}–{month_to.strftime('%d.%m.%Y')}"


# Разбирает preset или явный диапазон дат для отчёта.
def resolve_finance_period(
    preset: str | None,
    date_from_raw: date | None,
    date_to_raw: date | None,
    parse_error: str | None = None,
) -> FinancePeriodFilter:
    if parse_error:
        today = msk_today()
        return FinancePeriodFilter(
            date_from=today,
            date_to=today,
            paid_from_utc=msk_date_start_utc_naive(today),
            paid_to_exclusive_utc=msk_date_end_exclusive_utc_naive(today),
            preset=None,
            error=parse_error,
        )

    normalized_preset = (preset or "").strip().lower()
    today = msk_today()

    if normalized_preset in FINANCE_PRESETS:
        if normalized_preset == "today":
            date_from = date_to = today
        elif normalized_preset == "yesterday":
            yesterday = today - timedelta(days=1)
            date_from = date_to = yesterday
        elif normalized_preset == "week":
            date_from = msk_week_start(today)
            date_to = msk_week_end(today)
        else:
            date_from = today.replace(day=1)
            date_to = msk_month_end(today)
        return FinancePeriodFilter(
            date_from=date_from,
            date_to=date_to,
            paid_from_utc=msk_date_start_utc_naive(date_from),
            paid_to_exclusive_utc=msk_date_end_exclusive_utc_naive(date_to),
            preset=normalized_preset,
        )

    if date_from_raw is None and date_to_raw is None:
        date_from = today.replace(day=1)
        date_to = msk_month_end(today)
        return FinancePeriodFilter(
            date_from=date_from,
            date_to=date_to,
            paid_from_utc=msk_date_start_utc_naive(date_from),
            paid_to_exclusive_utc=msk_date_end_exclusive_utc_naive(date_to),
            preset="month",
        )

    effective_from = date_from_raw or date_to_raw
    effective_to = date_to_raw or date_from_raw
    assert effective_from is not None and effective_to is not None

    if effective_from > effective_to:
        return FinancePeriodFilter(
            date_from=effective_from,
            date_to=effective_to,
            paid_from_utc=msk_date_start_utc_naive(effective_from),
            paid_to_exclusive_utc=msk_date_end_exclusive_utc_naive(effective_to),
            preset=None,
            error="Дата «от» не может быть позже даты «до»",
        )

    return FinancePeriodFilter(
        date_from=effective_from,
        date_to=effective_to,
        paid_from_utc=msk_date_start_utc_naive(effective_from),
        paid_to_exclusive_utc=msk_date_end_exclusive_utc_naive(effective_to),
        preset=None,
    )


# Человекочитаемая подпись группировки для UI.
def finance_bucket_row_label(bucket: FinanceReportBucket) -> str:
    if bucket == FinanceReportBucket.WEEK:
        return "по неделям"
    if bucket == FinanceReportBucket.MONTH:
        return "по месяцам"
    return "по дням"


# Нормализует параметр группировки отчёта.
def parse_finance_bucket(value: str | None) -> FinanceReportBucket:
    normalized = (value or "").strip().lower()
    if normalized == FinanceReportBucket.WEEK:
        return FinanceReportBucket.WEEK
    if normalized == FinanceReportBucket.MONTH:
        return FinanceReportBucket.MONTH
    return FinanceReportBucket.DAY


# Подпись значения промокода для финансового разбора (% или фикс ₽).
def format_promo_discount_value_label(promo: PromoCode) -> str:
    value = Decimal(str(promo.value))
    if promo.discount_type == "fixed_rub":
        return format_finance_rub(value)
    normalized = value.normalize()
    text_value = format(normalized, "f")
    if "." in text_value:
        text_value = text_value.rstrip("0").rstrip(".")
    return f"{text_value}%"


# Собирает сводку промокодов и рефералов за период.
def build_finance_period_promo_referral_summary(
    orders: list[FinancePeriodOrderDetail],
) -> FinancePeriodPromoReferralSummary:
    promo_buckets: dict[str, dict[str, Any]] = {}
    promo_orders_count = 0
    promo_discount_total = Decimal("0.00")

    referral_buckets: dict[int, dict[str, Any]] = {}
    referral_orders_count = 0
    referral_payout_total = Decimal("0.00")

    for order in orders:
        if order.promo_code_applied:
            promo_orders_count += 1
            discount = order.promo_discount_rub or Decimal("0.00")
            promo_discount_total += discount
            code_key = order.promo_code_applied.strip().lower()
            bucket = promo_buckets.setdefault(
                code_key,
                {
                    "code": order.promo_code_applied,
                    "discount_label": order.promo_discount_label or "",
                    "orders_count": 0,
                    "discount_total": Decimal("0.00"),
                },
            )
            bucket["orders_count"] = int(bucket["orders_count"]) + 1
            bucket["discount_total"] = Decimal(str(bucket["discount_total"])) + discount

        if order.referral_commission_amount_rub is not None:
            referral_orders_count += 1
            payout = order.referral_commission_amount_rub
            referral_payout_total += payout
            referrer_id = order.referral_referrer_id
            if referrer_id is not None:
                bucket = referral_buckets.setdefault(
                    referrer_id,
                    {
                        "referrer_id": referrer_id,
                        "referrer_name": order.referral_referrer_name
                        or f"#{referrer_id}",
                        "orders_count": 0,
                        "payout_total": Decimal("0.00"),
                    },
                )
                bucket["orders_count"] = int(bucket["orders_count"]) + 1
                bucket["payout_total"] = Decimal(str(bucket["payout_total"])) + payout

    promo_rows = [
        FinancePeriodPromoCodeRow(
            code=str(bucket["code"]),
            discount_label=str(bucket["discount_label"]),
            orders_count=int(bucket["orders_count"]),
            discount_total=Decimal(str(bucket["discount_total"])),
        )
        for bucket in sorted(
            promo_buckets.values(),
            key=lambda row: Decimal(str(row["discount_total"])),
            reverse=True,
        )
    ]
    referral_rows = [
        FinancePeriodReferrerRow(
            referrer_id=int(bucket["referrer_id"]),
            referrer_name=str(bucket["referrer_name"]),
            orders_count=int(bucket["orders_count"]),
            payout_total=Decimal(str(bucket["payout_total"])),
        )
        for bucket in sorted(
            referral_buckets.values(),
            key=lambda row: Decimal(str(row["payout_total"])),
            reverse=True,
        )
    ]

    return FinancePeriodPromoReferralSummary(
        promo_orders_count=promo_orders_count,
        promo_discount_total=promo_discount_total.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        promo_rows=promo_rows,
        referral_orders_count=referral_orders_count,
        referral_payout_total=referral_payout_total.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        referral_rows=referral_rows,
    )


class FinanceReportService:
    # Сервис сборки финансового отчёта по оплаченным заказам.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session, Order)

    # Собирает финансовый отчёт по оплаченным заказам.
    async def build_report(
        self,
        period: FinancePeriodFilter,
        bucket: FinanceReportBucket,
    ) -> FinanceReportResult:
        pricing = await PricingService(self.session).get_settings()
        commission_percent = Decimal(pricing.service_commission_percent)

        if period.error:
            empty = _empty_totals()
            return FinanceReportResult(
                rows=[],
                totals=empty,
                commission_percent=commission_percent,
                period=period,
                bucket=bucket,
                error=period.error,
            )

        raw_rows = await self.order_crud.aggregate_paid_orders_finance(
            paid_from=period.paid_from_utc,
            paid_to_exclusive=period.paid_to_exclusive_utc,
            bucket=bucket.value,
        )

        rows: list[FinanceReportRow] = []
        totals_acc = _empty_totals()

        for raw in raw_rows:
            bucket_raw = raw["bucket"]
            if isinstance(bucket_raw, datetime):
                bucket_dt = bucket_raw
            elif isinstance(bucket_raw, date):
                bucket_dt = datetime.combine(bucket_raw, datetime.min.time())
            else:
                continue

            orders_count = int(str(raw.get("orders_count") or 0))
            items_count = int(str(raw.get("items_count") or 0))
            turnover = Decimal(str(raw["turnover"] or 0))
            cogs_rub = Decimal(str(raw["cogs_rub"] or 0))
            delivery_rub = Decimal(str(raw["delivery_rub"] or 0))
            commission_rub = Decimal(str(raw["commission_rub"] or 0)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            gross_profit, net_profit, compensation = finance_row_metrics(
                turnover,
                cogs_rub,
                delivery_rub,
                commission_rub,
            )
            paid_from, paid_to = finance_bucket_date_range(
                bucket_dt,
                bucket,
                period.date_from,
                period.date_to,
            )
            rows.append(
                FinanceReportRow(
                    bucket=bucket_dt,
                    label=format_finance_bucket_label(
                        bucket_dt,
                        bucket,
                        period.date_from,
                        period.date_to,
                    ),
                    orders_count=orders_count,
                    items_count=items_count,
                    turnover=turnover,
                    cogs_rub=cogs_rub,
                    delivery_rub=delivery_rub,
                    gross_profit=gross_profit,
                    net_profit=net_profit,
                    compensation=compensation,
                    paid_date_from=paid_from,
                    paid_date_to=paid_to,
                )
            )
            totals_acc = _add_totals(
                totals_acc,
                orders_count,
                items_count,
                turnover,
                cogs_rub,
                delivery_rub,
                gross_profit,
                net_profit,
                compensation,
            )

        return FinanceReportResult(
            rows=rows,
            totals=totals_acc,
            commission_percent=commission_percent,
            period=period,
            bucket=bucket,
        )

    # Собирает разбор периода: заказы и позиции для drill-down из отчёта.
    async def build_period_detail(
        self,
        period: FinancePeriodFilter,
    ) -> FinancePeriodDetailResult:
        empty = _empty_totals()
        if period.error:
            return FinancePeriodDetailResult(
                period=period,
                orders=[],
                totals=empty,
                promo_referral_summary=_empty_promo_referral_summary(),
                error=period.error,
            )

        pricing = PricingService(self.session)
        commission_history = await pricing.list_service_commission_history()
        settings = await pricing.get_settings()
        fallback_rate = Decimal(str(settings.service_commission_percent))

        orders = await self.order_crud.list_paid_orders_for_finance_detail(
            paid_from=period.paid_from_utc,
            paid_to_exclusive=period.paid_to_exclusive_utc,
        )
        items_by_order = await self.order_crud.list_order_items_grouped(
            [order.id for order in orders]
        )
        order_ids = [order.id for order in orders]
        earnings_by_order = await ReferralRepository(
            self.session
        ).list_earnings_by_order_ids(order_ids)
        referrer_ids = sorted(
            {earning.referrer_id for earning in earnings_by_order.values()}
        )
        referrers_by_id: dict[int, User] = {}
        if referrer_ids:
            referrers = await self.session.scalars(
                select(User).where(User.id.in_(referrer_ids))
            )
            referrers_by_id = {user.id: user for user in referrers.all()}

        promo_codes = [
            order.promo_code_applied for order in orders if order.promo_code_applied
        ]
        promos_by_code = await PromoRepository(self.session).map_by_codes(promo_codes)

        detail_orders: list[FinancePeriodOrderDetail] = []
        totals_acc = _empty_totals()

        for order in orders:
            paid_date = order_paid_date_msk(order.payment_paid_at)
            if paid_date is None:
                continue

            eur_rate = Decimal(str(order.eur_rate_snapshot))
            lines: list[FinancePeriodLineItem] = []
            items_count = 0
            missing_cogs_snapshot = False

            for item in items_by_order.get(order.id, []):
                qty = int(item.quantity)
                items_count += qty
                supplier_eur = (
                    Decimal(str(item.supplier_price_eur_captured))
                    if item.supplier_price_eur_captured is not None
                    else None
                )
                sale_rub, cogs_rub, margin_rub, margin_percent, missing_snapshot = (
                    finance_line_item_metrics(
                        qty,
                        Decimal(str(item.unit_price)),
                        supplier_eur,
                        eur_rate,
                    )
                )
                if missing_snapshot:
                    missing_cogs_snapshot = True
                title = (item.product_title_captured or "Товар").strip()
                lines.append(
                    FinancePeriodLineItem(
                        title=title,
                        variant_label=_order_item_variant_label(item),
                        quantity=qty,
                        unit_price=Decimal(str(item.unit_price)),
                        sale_rub=sale_rub,
                        supplier_price_eur=supplier_eur,
                        eur_rate=eur_rate,
                        cogs_rub=cogs_rub,
                        margin_rub=margin_rub,
                        margin_percent=margin_percent,
                        missing_snapshot=missing_snapshot,
                    )
                )

            items_subtotal_rub = sum(
                (line.sale_rub for line in lines), Decimal("0.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            turnover = Decimal(str(order.total_amount))
            cogs_rub = (
                Decimal(str(order.supplier_cost_eur_snapshot)) * eur_rate
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            delivery_rub = Decimal(str(order.delivery_fee_amount))
            commission_percent = pricing.service_commission_percent_for_date(
                paid_date,
                commission_history,
                fallback_rate,
            )
            commission_rub = (turnover * commission_percent / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            earning = earnings_by_order.get(order.id)
            referrer = (
                referrers_by_id.get(earning.referrer_id)
                if earning is not None
                else None
            )
            referral_payout_rub = (
                earning.commission_amount_rub if earning is not None else None
            )

            promo_discount_label = None
            promo_discount_rub = None
            if order.promo_code_applied:
                promo = promos_by_code.get(order.promo_code_applied.strip().lower())
                if promo is not None:
                    promo_discount_label = format_promo_discount_value_label(promo)
                promo_discount_rub = Decimal(
                    str(order.discount_items_amount or 0)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            gross_profit, net_profit, compensation = finance_period_order_metrics(
                turnover,
                cogs_rub,
                delivery_rub,
                commission_rub,
                referral_payout_rub,
            )

            paid_at_display = ""
            if order.payment_paid_at is not None:
                paid_at_display = format_datetime_msk(order.payment_paid_at) or ""

            detail_orders.append(
                FinancePeriodOrderDetail(
                    order_id=order.id,
                    paid_at_display=paid_at_display,
                    paid_date=paid_date,
                    turnover=turnover,
                    cogs_rub=cogs_rub,
                    delivery_rub=delivery_rub,
                    commission_percent=commission_percent,
                    commission_rub=commission_rub,
                    gross_profit=gross_profit,
                    net_profit=net_profit,
                    compensation=compensation,
                    items_count=items_count,
                    items_subtotal_rub=items_subtotal_rub,
                    missing_cogs_snapshot=missing_cogs_snapshot,
                    promo_code_applied=order.promo_code_applied,
                    promo_discount_label=promo_discount_label,
                    promo_discount_rub=promo_discount_rub,
                    referral_referrer_id=earning.referrer_id if earning else None,
                    referral_referrer_name=(
                        user_display_label(referrer) if referrer is not None else None
                    ),
                    referral_commission_percent=(
                        earning.commission_percent if earning else None
                    ),
                    referral_commission_amount_rub=referral_payout_rub,
                    lines=lines,
                )
            )
            totals_acc = _add_totals(
                totals_acc,
                1,
                items_count,
                turnover,
                cogs_rub,
                delivery_rub,
                gross_profit,
                net_profit,
                compensation,
            )

        return FinancePeriodDetailResult(
            period=period,
            orders=detail_orders,
            totals=totals_acc,
            promo_referral_summary=build_finance_period_promo_referral_summary(
                detail_orders
            ),
        )


# Имя CSV-файла для выгрузки финансового отчёта.
def finance_report_export_filename(
    period: FinancePeriodFilter,
    bucket: FinanceReportBucket,
) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return (
        f"finance-{period.date_from.isoformat()}-"
        f"{period.date_to.isoformat()}-{bucket.value}-{ts}.csv"
    )


# Форматирует сумму для CSV (точка как разделитель дробной части).
def _finance_csv_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


# Преобразует строку отчёта в строку CSV.
def finance_report_row_to_csv(row: FinanceReportRow) -> list[str]:
    return [
        row.label,
        str(row.orders_count),
        str(row.items_count),
        _finance_csv_decimal(row.turnover),
        _finance_csv_decimal(row.cogs_rub),
        _finance_csv_decimal(row.delivery_rub),
        _finance_csv_decimal(row.gross_profit),
        _finance_csv_decimal(row.net_profit),
        _finance_csv_decimal(row.compensation),
    ]


# Преобразует итоги отчёта в строку CSV.
def finance_report_totals_to_csv(totals: FinanceReportTotals) -> list[str]:
    return [
        "Итого",
        str(totals.orders_count),
        str(totals.items_count),
        _finance_csv_decimal(totals.turnover),
        _finance_csv_decimal(totals.cogs_rub),
        _finance_csv_decimal(totals.delivery_rub),
        _finance_csv_decimal(totals.gross_profit),
        _finance_csv_decimal(totals.net_profit),
        _finance_csv_decimal(totals.compensation),
    ]


# Собирает CSV финансового отчёта (utf-8-sig) в память.
def build_finance_report_csv_bytes(report: FinanceReportResult) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(FINANCE_REPORT_CSV_FIELDS)
    for row in report.rows:
        writer.writerow(finance_report_row_to_csv(row))
    if report.rows:
        writer.writerow(finance_report_totals_to_csv(report.totals))
    return buffer.getvalue().encode("utf-8-sig")


# Пустые итоги для ошибочного периода или старта суммирования.
def _empty_promo_referral_summary() -> FinancePeriodPromoReferralSummary:
    return FinancePeriodPromoReferralSummary(
        promo_orders_count=0,
        promo_discount_total=Decimal("0.00"),
        promo_rows=[],
        referral_orders_count=0,
        referral_payout_total=Decimal("0.00"),
        referral_rows=[],
    )


def _empty_totals() -> FinanceReportTotals:
    zero = Decimal("0")
    return FinanceReportTotals(
        orders_count=0,
        items_count=0,
        turnover=zero,
        cogs_rub=zero,
        delivery_rub=zero,
        gross_profit=zero,
        net_profit=zero,
        compensation=zero,
    )


# Складывает строку отчёта в накопительные итоги.
def _add_totals(
    current: FinanceReportTotals,
    orders_count: int,
    items_count: int,
    turnover: Decimal,
    cogs_rub: Decimal,
    delivery_rub: Decimal,
    gross_profit: Decimal,
    net_profit: Decimal,
    compensation: Decimal,
) -> FinanceReportTotals:
    return FinanceReportTotals(
        orders_count=current.orders_count + orders_count,
        items_count=current.items_count + items_count,
        turnover=current.turnover + turnover,
        cogs_rub=current.cogs_rub + cogs_rub,
        delivery_rub=current.delivery_rub + delivery_rub,
        gross_profit=current.gross_profit + gross_profit,
        net_profit=current.net_profit + net_profit,
        compensation=current.compensation + compensation,
    )
