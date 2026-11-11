import uuid

import pytest
from sqlalchemy import delete, select

from src.models.auth_identity import AuthIdentity
from src.models.user import User
from src.repositories.auth_identity_repo import PROVIDER_PHONE
from src.repositories.session import async_session_maker
from src.services.auth.phone import PhoneAuthService

pytestmark = pytest.mark.integration


# Проверяет создание phone identity и повторный вход в того же пользователя.
@pytest.mark.asyncio
async def test_phone_auth_creates_identity_and_reuses_user() -> None:
    phone_e164 = f"+7998{int(uuid.uuid4().hex[:7], 16) % 10_000_000:07d}"
    user_id: int | None = None
    try:
        async with async_session_maker() as session:
            service = PhoneAuthService(session)
            first_user, is_new = await service.authenticate_by_phone(phone_e164)
            user_id = first_user.id
            second_user, is_new_second = await service.authenticate_by_phone(phone_e164)
            identity = await session.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == PROVIDER_PHONE,
                    AuthIdentity.provider_user_id == phone_e164,
                )
            )

            assert is_new is True
            assert is_new_second is False
            assert second_user.id == first_user.id
            assert identity is not None
            assert identity.user_id == first_user.id
    finally:
        if user_id is not None:
            async with async_session_maker() as session:
                await session.execute(
                    delete(AuthIdentity).where(AuthIdentity.user_id == user_id)
                )
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
