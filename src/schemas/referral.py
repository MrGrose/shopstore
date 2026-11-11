from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReferralCommissionSource = Literal["global", "individual", "disabled"]

ReferralAttributionStatus = Literal[
    "attributed",
    "already_attributed",
    "invalid_code",
    "self_referral",
    "attribution_locked",
    "not_eligible",
]


class ReferralEarningSchema(BaseModel):
    order_id: int
    order_amount_rub: Decimal
    commission_percent: Decimal
    commission_amount_rub: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MyReferrerSchema(BaseModel):
    referrer_id: int | None = None
    referrer_name: str | None = None


class ReferrerApplyResponse(BaseModel):
    status: ReferralAttributionStatus


class ReferralMeSchema(BaseModel):
    referral_code: str
    referral_alias: str | None = None
    referral_link: str
    commission_percent: Decimal
    commission_percent_source: ReferralCommissionSource = "global"
    invited_count: int
    orders_count: int
    total_earned_rub: Decimal
    recent_earnings: list[ReferralEarningSchema]
