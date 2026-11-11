from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.repositories.database import Base


class PricingSettings(Base):
    __tablename__ = "pricing_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    eur_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("100")
    )
    markup_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, default=Decimal("1.2")
    )
    delivery_fee_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("30")
    )
    eur_rate_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    eur_rate_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    referral_commission_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("5.00")
    )
    service_commission_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("6.50")
    )


class ServiceCommissionHistory(Base):
    __tablename__ = "service_commission_history"
    __table_args__ = (
        UniqueConstraint("effective_from", name="uq_service_commission_effective_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class EurRateHistory(Base):
    __tablename__ = "eur_rate_history"
    __table_args__ = (Index("ix_eur_rate_history_recorded_at", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    eur_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    eur_rate_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class MarginRule(Base):
    __tablename__ = "margin_rules"
    __table_args__ = (
        UniqueConstraint(
            "sport_type",
            "subcategory_slug",
            name="uq_margin_rule_sport_subcategory",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sport_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subcategory_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MarginRuleHistory(Base):
    __tablename__ = "margin_rule_history"
    __table_args__ = (
        Index("ix_margin_rule_history_rule_created_at", "margin_rule_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    margin_rule_id: Mapped[int] = mapped_column(
        ForeignKey("margin_rules.id", ondelete="CASCADE"), nullable=False
    )
    previous_margin_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class PricingRecalculationJob(Base):
    __tablename__ = "pricing_recalculation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    margin_rule_id: Mapped[int] = mapped_column(
        ForeignKey("margin_rules.id"), nullable=False, index=True
    )
    rq_job_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    margin_percent: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    rule_version: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    settings_version: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PricingRecalculationJobError(Base):
    __tablename__ = "pricing_recalculation_job_errors"
    __table_args__ = (
        UniqueConstraint(
            "pricing_job_id",
            "product_id",
            name="uq_pricing_job_error_product",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pricing_job_id: Mapped[int] = mapped_column(
        ForeignKey("pricing_recalculation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class PromoCode(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (UniqueConstraint("code", name="uq_promo_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    discount_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="percent"
    )
    usage_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="multi_use"
    )
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    min_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )
    max_discount_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    usage_limit_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    active_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PromoCodeUsage(Base):
    __tablename__ = "promo_code_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(
        ForeignKey("promo_codes.id"), index=True, nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ReferralEarning(Base):
    __tablename__ = "referral_earnings"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_referral_earnings_order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    order_amount_rub: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    commission_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    commission_amount_rub: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class CustomerReferralAudit(Base):
    __tablename__ = "customer_referral_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    admin_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    old_referrer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    new_referrer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    old_attribution_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    new_attribution_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
