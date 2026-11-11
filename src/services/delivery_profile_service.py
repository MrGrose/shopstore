from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_delivery_profile import UserDeliveryProfile
from src.repositories.user_delivery_profile_repo import UserDeliveryProfileRepository
from src.schemas.order import DeliveryAddressCreate


class DeliveryProfileService:
    # Инициализирует сервис профиля доставки.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserDeliveryProfileRepository(session)

    # Возвращает профиль доставки пользователя.
    async def get_profile(self, user_id: int) -> UserDeliveryProfile | None:
        return await self.repo.get_by_user_id(user_id)

    # Сохраняет профиль доставки из валидированного адреса.
    async def upsert_from_delivery(
        self,
        user_id: int,
        delivery: DeliveryAddressCreate,
        auto_commit: bool = True,
    ) -> UserDeliveryProfile:
        return await self.repo.upsert(
            user_id,
            delivery.model_dump(),
            auto_commit=auto_commit,
        )

    # Удаляет сохранённый профиль доставки.
    async def delete_profile(self, user_id: int) -> bool:
        return await self.repo.delete_by_user_id(user_id)
