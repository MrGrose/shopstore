from sqlalchemy.ext.asyncio import AsyncSession

from src.api.user_schema import build_user_schema
from src.core.user_roles import user_can_be_referred, user_has_referral_program
from src.models.user import User
from src.schemas.user import IdentitySchema, UserMeSchema
from src.services.identity_service import IdentityService
from src.services.referral_service import ReferralService


# Собирает UserMeSchema с identities и флагами рефералки.
async def build_user_me_schema(
    db: AsyncSession,
    user: User,
) -> UserMeSchema:
    user = await ReferralService(db).ensure_referral_code(user)
    identities_raw = await IdentityService(db).list_identities_for_user(user.id)
    identities: list[IdentitySchema] = []
    for item in identities_raw:
        meta = item.meta_json if isinstance(item.meta_json, dict) else {}
        username = meta.get("username")
        identities.append(
            IdentitySchema(
                provider=item.provider,
                provider_user_id=item.provider_user_id,
                email=item.email,
                telegram_username=str(username) if username else None,
                created_at=item.created_at,
            )
        )
    base = await build_user_schema(db, user)
    return UserMeSchema(
        **base.model_dump(),
        can_be_referred=user_can_be_referred(user.role),
        has_referral_program=user_has_referral_program(user.role),
        identities=identities,
    )
