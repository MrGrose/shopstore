from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.auth_identity import AuthIdentity

PROVIDER_TELEGRAM = "telegram"
PROVIDER_EMAIL = "email"
PROVIDER_PHONE = "phone"


class AuthIdentityRepository:
    # Инициализирует репозиторий auth_identities.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Ищет identity по provider и provider_user_id.
    async def get_by_provider(
        self,
        provider: str,
        provider_user_id: str,
    ) -> AuthIdentity | None:
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.provider == provider,
                AuthIdentity.provider_user_id == provider_user_id,
            )
        )
        return result.first()

    # Ищет telegram-identity пользователя.
    async def get_telegram_for_user(self, user_id: int) -> AuthIdentity | None:
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == PROVIDER_TELEGRAM,
            )
        )
        return result.first()

    # Список identities пользователя.
    async def list_for_user(self, user_id: int) -> list[AuthIdentity]:
        result = await self.session.scalars(
            select(AuthIdentity)
            .where(AuthIdentity.user_id == user_id)
            .order_by(AuthIdentity.created_at.asc())
        )
        return list(result.all())

    # Ищет email-identity по нормализованному email.
    async def get_email_by_address(self, email: str) -> AuthIdentity | None:
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.provider == PROVIDER_EMAIL,
                AuthIdentity.email == email,
            )
        )
        return result.first()

    # Ищет phone-identity по E.164.
    async def get_phone_by_number(self, phone_e164: str) -> AuthIdentity | None:
        return await self.get_by_provider(PROVIDER_PHONE, phone_e164)

    # Ищет phone-identity пользователя.
    async def get_phone_for_user(self, user_id: int) -> AuthIdentity | None:
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == PROVIDER_PHONE,
            )
        )
        return result.first()

    # Создаёт запись identity.
    async def create(
        self,
        user_id: int,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
        meta_json: dict | None = None,
        auto_commit: bool = True,
    ) -> AuthIdentity:
        identity = AuthIdentity(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            email=email,
            meta_json=meta_json,
        )
        self.session.add(identity)
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(identity)
        return identity

    # Удаляет все identities пользователя (перед удалением users).
    async def delete_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(AuthIdentity).where(AuthIdentity.user_id == user_id)
        )

    # Обновляет meta_json и email identity.
    async def update_identity(
        self,
        identity: AuthIdentity,
        email: str | None = None,
        meta_json: dict | None = None,
        auto_commit: bool = True,
    ) -> AuthIdentity:
        if email is not None:
            identity.email = email
        if meta_json is not None:
            identity.meta_json = meta_json
        self.session.add(identity)
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(identity)
        return identity
