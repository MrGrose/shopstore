from dataclasses import dataclass

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.user_access import assert_user_can_authenticate
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.identity_service import IdentityService
from src.services.login_finalize_service import finalize_login
from src.services.user_service import UserService
from src.services.verification.phone.call_service import PhoneCallAuthService
from src.services.verification.phone.errors import PhoneCallConflictError


@dataclass(frozen=True, slots=True)
class PhoneCallLoginResult:
    access_token: str
    user: User
    is_new_user: bool


class PhoneAuthService:
    # Подготавливает сервисы пользователя и identity для phone auth.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_service = UserService(session)
        self.identity_service = IdentityService(session)

    # Находит или создаёт пользователя по подтверждённому телефону.
    async def authenticate_by_phone(self, phone_e164: str) -> tuple[User, bool]:
        user = await self.identity_service.resolve_user_by_phone(phone_e164)
        if user is not None:
            assert_user_can_authenticate(user)
            await self.identity_service.ensure_phone_identity_for_user(user, phone_e164)
            return user, False

        user = await self.user_service.register_user_by_phone(phone_e164)
        return user, True


class PhoneCallLoginService:
    # Подготавливает подтверждённый call flow к общему login pipeline.
    def __init__(self, flow_service: PhoneCallAuthService | None = None) -> None:
        self.flow_service = flow_service or PhoneCallAuthService()

    # Завершает phone login через существующие identity и finalize_login.
    async def complete(
        self,
        flow_id: str,
        request: Request,
        response: Response,
        referral_code: str | None = None,
    ) -> PhoneCallLoginResult:
        flow = await self.flow_service.consume_verified(flow_id)
        try:
            async with async_session_maker() as session:
                user, is_new_user = await PhoneAuthService(
                    session
                ).authenticate_by_phone(flow.phone_e164)
                access_token, user = await finalize_login(
                    session,
                    user,
                    request,
                    response,
                    referral_code=referral_code,
                )
        except ValueError as exc:
            raise PhoneCallConflictError(str(exc)) from exc
        return PhoneCallLoginResult(
            access_token=access_token,
            user=user,
            is_new_user=is_new_user,
        )
