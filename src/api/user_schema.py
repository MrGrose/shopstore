from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.schemas.user import UserSchema
from src.services.identity_service import IdentityService


# Собирает UserSchema с telegram-полями из auth_identities.
async def build_user_schema(db: AsyncSession, user: User) -> UserSchema:
    identity_svc = IdentityService(db)
    telegram_id = await identity_svc.get_telegram_id_for_user(user)
    telegram_username = await identity_svc.get_telegram_username_for_user(user)
    base = UserSchema.model_validate(user)
    return base.model_copy(
        update={
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
        }
    )
