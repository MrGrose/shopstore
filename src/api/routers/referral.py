from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.core.user_roles import user_has_referral_program
from src.deps import get_db
from src.models.user import User
from src.schemas.referral import ReferralEarningSchema, ReferralMeSchema
from src.services.referral_service import ReferralService

router = APIRouter(prefix="/referral", tags=["referral"])


# Статистика реферальной программы текущего пользователя.
@router.get("/me", response_model=ReferralMeSchema, summary="Моя реферальная программа")
async def get_my_referral_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReferralMeSchema:
    if not user_has_referral_program(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Реферальная программа недоступна",
        )
    stats = await ReferralService(db).get_referral_stats(current_user.id)
    return ReferralMeSchema(
        referral_code=str(stats["referral_code"]),
        referral_alias=(
            str(stats["referral_alias"]) if stats.get("referral_alias") else None
        ),
        referral_link=str(stats["referral_link"]),
        commission_percent=cast(Decimal, stats["commission_percent"]),
        commission_percent_source=cast(
            str, stats.get("commission_percent_source", "global")
        ),
        invited_count=cast(int, stats["invited_count"]),
        orders_count=cast(int, stats["orders_count"]),
        total_earned_rub=cast(Decimal, stats["total_earned_rub"]),
        recent_earnings=[
            ReferralEarningSchema.model_validate(item)
            for item in cast(list[Any], stats["recent_earnings"])
        ],
    )
