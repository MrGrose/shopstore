from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pricing import PromoCode, PromoCodeUsage


class PromoRepository:
    # Репозиторий промокодов и фактов их применения.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Возвращает промокод по строковому коду.
    async def get_by_code(self, code: str) -> PromoCode | None:
        result = await self.session.scalars(
            select(PromoCode).where(func.lower(PromoCode.code) == code.strip().lower())
        )
        return result.first()

    # Возвращает промокод по id.
    async def get_by_id(self, promo_id: int) -> PromoCode | None:
        return await self.session.get(PromoCode, promo_id)

    # Возвращает промокоды по списку кодов (ключ — lower code).
    async def map_by_codes(self, codes: list[str]) -> dict[str, PromoCode]:
        normalized = sorted(
            {code.strip().lower() for code in codes if code and code.strip()}
        )
        if not normalized:
            return {}
        result = await self.session.scalars(
            select(PromoCode).where(func.lower(PromoCode.code).in_(normalized))
        )
        return {promo.code.lower(): promo for promo in result.all()}

    # Возвращает список промокодов для админки.
    async def list_all(self) -> list[PromoCode]:
        result = await self.session.scalars(
            select(PromoCode).order_by(PromoCode.id.desc())
        )
        return list(result.all())

    # Создает новый промокод.
    async def create(self, payload: dict) -> PromoCode:
        promo = PromoCode(**payload)
        self.session.add(promo)
        await self.session.commit()
        await self.session.refresh(promo)
        return promo

    # Обновляет существующий промокод.
    async def update(self, promo: PromoCode, payload: dict) -> PromoCode:
        for key, value in payload.items():
            setattr(promo, key, value)
        promo.updated_at = datetime.utcnow()
        self.session.add(promo)
        await self.session.commit()
        await self.session.refresh(promo)
        return promo

    # Удаляет промокод.
    async def delete(self, promo: PromoCode) -> None:
        await self.session.delete(promo)
        await self.session.commit()

    # Добавляет запись использования промокода.
    async def create_usage(
        self, promo_code_id: int, order_id: int, user_id: int
    ) -> PromoCodeUsage:
        usage = PromoCodeUsage(
            promo_code_id=promo_code_id, order_id=order_id, user_id=user_id
        )
        self.session.add(usage)
        await self.session.commit()
        await self.session.refresh(usage)
        return usage

    # Добавляет запись использования промокода без commit (для edit flow).
    async def create_usage_flush(
        self, promo_code_id: int, order_id: int, user_id: int
    ) -> PromoCodeUsage:
        usage = PromoCodeUsage(
            promo_code_id=promo_code_id, order_id=order_id, user_id=user_id
        )
        self.session.add(usage)
        await self.session.flush()
        await self.session.refresh(usage)
        return usage

    # Удаляет usage промокода для заказа без commit.
    async def delete_usage_for_order(self, order_id: int) -> None:
        await self.session.execute(
            delete(PromoCodeUsage).where(PromoCodeUsage.order_id == order_id)
        )
        await self.session.flush()

    # Считает общее число применений промокода.
    async def count_total_usages(self, promo_code_id: int) -> int:
        count = await self.session.scalar(
            select(func.count(PromoCodeUsage.id)).where(
                PromoCodeUsage.promo_code_id == promo_code_id
            )
        )
        return int(count or 0)

    # Проверяет, применял ли пользователь промокод ранее.
    async def has_user_usage(self, promo_code_id: int, user_id: int) -> bool:
        result = await self.session.scalar(
            select(PromoCodeUsage.id).where(
                PromoCodeUsage.promo_code_id == promo_code_id,
                PromoCodeUsage.user_id == user_id,
            )
        )
        return result is not None
