from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PricingSettingsSchema(BaseModel):
    id: int
    eur_rate: Decimal
    markup_multiplier: Decimal
    delivery_fee_eur: Decimal
    eur_rate_source: str | None = None
    eur_rate_updated_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PricingSettingsUpdate(BaseModel):
    eur_rate: Decimal | None = Field(default=None, gt=0)
    markup_multiplier: Decimal | None = Field(default=None, gt=0)
    delivery_fee_eur: Decimal | None = Field(default=None, ge=0)


class MarginRuleSchema(BaseModel):
    id: int
    sport_type: str
    subcategory_slug: str
    margin_percent: Decimal
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MarginRuleUpdate(BaseModel):
    margin_percent: Decimal = Field(ge=0, le=1000)
    is_active: bool | None = None


class PromoCodeSchema(BaseModel):
    id: int
    code: str
    discount_type: str
    usage_mode: str
    value: Decimal
    min_order_amount: Decimal
    max_discount_amount: Decimal | None = None
    usage_limit_total: int | None = None
    is_active: bool
    active_from: datetime | None = None
    active_to: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PromoCodeCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    discount_type: str = Field(default="percent")
    usage_mode: str = Field(default="multi_use")
    value: Decimal = Field(gt=0)
    min_order_amount: Decimal = Field(default=Decimal("0"), ge=0)
    max_discount_amount: Decimal | None = Field(default=None, ge=0)
    usage_limit_total: int | None = Field(default=None, ge=1)
    is_active: bool = True
    active_from: datetime | None = None
    active_to: datetime | None = None


class PromoCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=64)
    discount_type: str | None = None
    usage_mode: str | None = None
    value: Decimal | None = Field(default=None, gt=0)
    min_order_amount: Decimal | None = Field(default=None, ge=0)
    max_discount_amount: Decimal | None = Field(default=None, ge=0)
    usage_limit_total: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    active_from: datetime | None = None
    active_to: datetime | None = None
