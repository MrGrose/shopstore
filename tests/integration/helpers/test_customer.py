from sqlalchemy.ext.asyncio import AsyncSession

from src.core.user_roles import UserRole
from src.models.user import User
from src.services.identity_service import IdentityService
from src.services.referral_service import ReferralService
from src.services.user_service import UserService


# Создаёт buyer-клиента с email и/или Telegram для integration/e2e тестов.
async def create_test_customer(
    session: AsyncSession,
    *,
    name: str | None = None,
    email: str | None = None,
    telegram_username: str | None = None,
    telegram_id: str | None = None,
) -> User:
    user_service = UserService(session)
    normalized_name = name.strip() if name and name.strip() else None
    normalized_email = email.strip().lower() if email and email.strip() else None
    raw_username = (telegram_username or "").strip().lstrip("@")
    normalized_username = raw_username or None
    telegram_id_int: int | None = None
    if telegram_id and str(telegram_id).strip():
        try:
            telegram_id_int = int(str(telegram_id).strip())
        except ValueError as exc:
            raise ValueError("Telegram ID должен быть числом") from exc
        if telegram_id_int <= 0:
            raise ValueError("Некорректный Telegram ID")
    if not normalized_email and telegram_id_int is None:
        raise ValueError("Укажите email или Telegram ID")
    if normalized_email:
        existing = await user_service.user_crud.get_by_email(normalized_email)
        if existing:
            raise ValueError("Email уже занят")
    if telegram_id_int is not None:
        existing_tg = await user_service.get_by_telegram_id(telegram_id_int)
        if existing_tg:
            raise ValueError("Telegram ID уже занят")
    user = User(
        email=normalized_email,
        name=normalized_name,
        role=UserRole.BUYER.value,
    )
    user = await ReferralService(session).ensure_referral_code(user)
    identity_svc = IdentityService(session)
    if normalized_email:
        await identity_svc.ensure_email_identity_for_user(user, normalized_email)
    if telegram_id_int is not None:
        user = await identity_svc.link_telegram_to_user(
            user,
            telegram_id=telegram_id_int,
            telegram_username=normalized_username,
            name=normalized_name,
        )
    return user
