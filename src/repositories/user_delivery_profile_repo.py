from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_delivery_profile import UserDeliveryProfile


class UserDeliveryProfileRepository:
    # Инициализирует репозиторий профилей доставки.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Возвращает профиль доставки пользователя.
    async def get_by_user_id(self, user_id: int) -> UserDeliveryProfile | None:
        result = await self.session.scalars(
            select(UserDeliveryProfile).where(UserDeliveryProfile.user_id == user_id)
        )
        return result.first()

    # Создаёт или обновляет профиль доставки пользователя.
    async def upsert(
        self,
        user_id: int,
        payload: dict[str, str | None],
        auto_commit: bool = True,
    ) -> UserDeliveryProfile:
        profile = await self.get_by_user_id(user_id)
        if profile is None:
            profile = UserDeliveryProfile(user_id=user_id, **payload)
            self.session.add(profile)
        else:
            for key, value in payload.items():
                setattr(profile, key, value)
            self.session.add(profile)
        if auto_commit:
            await self.session.commit()
            await self.session.refresh(profile)
        return profile

    # Удаляет профиль доставки пользователя.
    async def delete_by_user_id(self, user_id: int, auto_commit: bool = True) -> bool:
        profile = await self.get_by_user_id(user_id)
        if profile is None:
            return False
        await self.session.delete(profile)
        if auto_commit:
            await self.session.commit()
        return True
