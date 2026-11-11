from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pricing import PromoCode
from src.repositories.promo_repo import PromoRepository


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PromoRepository(session)

    # Валидирует временной диапазон действия промокода.
    @staticmethod
    def _validate_active_period(payload: dict) -> None:
        active_from = payload.get("active_from")
        active_to = payload.get("active_to")
        if active_to is None:
            raise ValueError("Для промокода нужно указать дату окончания действия")
        if active_from and active_to and active_to < active_from:
            raise ValueError("Дата окончания не может быть раньше даты начала")

    # Возвращает список всех промокодов.
    async def list_promo_codes(self) -> list[PromoCode]:
        return await self.repo.list_all()

    # Список промокодов с фильтром active/inactive/all.
    async def list_promo_codes_filtered(
        self, status_filter: str = "active"
    ) -> list[PromoCode]:
        promos = await self.list_promo_codes()
        return self._filter_promo_codes(promos, status_filter)

    # Список промокодов и счётчики фильтров для HTML-страницы админки.
    async def list_promo_codes_admin_page(
        self, status_filter: str = "active"
    ) -> tuple[list[PromoCode], dict[str, int]]:
        promos = await self.list_promo_codes()
        return self._filter_promo_codes(
            promos, status_filter
        ), self._promo_filter_counts(promos)

    @staticmethod
    def _filter_promo_codes(
        promos: list[PromoCode], status_filter: str
    ) -> list[PromoCode]:
        if status_filter == "active":
            return [promo for promo in promos if promo.is_active]
        if status_filter == "inactive":
            return [promo for promo in promos if not promo.is_active]
        return promos

    @staticmethod
    def _promo_filter_counts(promos: list[PromoCode]) -> dict[str, int]:
        active = sum(1 for promo in promos if promo.is_active)
        total = len(promos)
        return {"active": active, "inactive": total - active, "all": total}

    # Создает промокод в админке.
    async def create_promo_code(self, payload: dict) -> PromoCode:
        payload["code"] = str(payload["code"]).strip().upper()
        self._validate_active_period(payload)
        if await self.repo.get_by_code(payload["code"]):
            raise ValueError("Промокод уже существует")
        return await self.repo.create(payload)

    # Обновляет промокод в админке.
    async def update_promo_code(self, promo_id: int, payload: dict) -> PromoCode:
        promo = await self.repo.get_by_id(promo_id)
        if not promo:
            raise ValueError("Промокод не найден")
        if "code" in payload:
            payload["code"] = str(payload["code"]).strip().upper()
        if "active_from" in payload or "active_to" in payload:
            merged_payload = {
                "active_from": promo.active_from,
                "active_to": promo.active_to,
                **payload,
            }
            self._validate_active_period(merged_payload)
        return await self.repo.update(promo, payload)

    # Удаляет промокод, если он не использовался в заказах.
    async def delete_promo_code(self, promo_id: int) -> None:
        promo = await self.repo.get_by_id(promo_id)
        if not promo:
            raise ValueError("Промокод не найден")
        usages_total = await self.repo.count_total_usages(promo.id)
        if usages_total > 0:
            raise ValueError("Нельзя удалить использованный промокод, отключите его")
        await self.repo.delete(promo)

    # Рассчитывает скидку по промокоду для суммы товаров.
    async def calculate_discount(
        self,
        promo_code: str | None,
        items_subtotal: Decimal,
        user_id: int,
    ) -> tuple[Decimal, PromoCode | None]:
        if not promo_code:
            return Decimal("0"), None
        promo = await self.repo.get_by_code(promo_code)
        if not promo or not promo.is_active:
            raise ValueError("Промокод недействителен")
        now = datetime.utcnow()
        if promo.active_from and promo.active_from > now:
            raise ValueError("Промокод еще не активен")
        if promo.active_to and promo.active_to < now:
            raise ValueError("Срок промокода истек")
        if items_subtotal < Decimal(promo.min_order_amount or 0):
            raise ValueError("Сумма товаров меньше минимальной для промокода")

        usages_total = await self.repo.count_total_usages(promo.id)
        if promo.usage_limit_total is not None and usages_total >= int(
            promo.usage_limit_total
        ):
            raise ValueError("Лимит применений промокода исчерпан")
        if promo.usage_mode == "single_use":
            if usages_total > 0:
                raise ValueError("Промокод уже использован")
        if promo.usage_mode == "single_use_per_user":
            if await self.repo.has_user_usage(promo.id, user_id):
                raise ValueError("Промокод уже использован этим пользователем")

        if promo.discount_type == "fixed_rub":
            discount = Decimal(promo.value)
        else:
            discount = (
                items_subtotal * Decimal(promo.value) / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if promo.max_discount_amount is not None:
            discount = min(discount, Decimal(promo.max_discount_amount))
        discount = min(discount, items_subtotal)
        return max(discount, Decimal("0")), promo

    # Пересчитывает скидку уже применённого промокода при редактировании заказа.
    async def calculate_discount_for_order_edit(
        self,
        promo_code: str | None,
        items_subtotal: Decimal,
    ) -> tuple[Decimal, PromoCode | None, bool]:
        if not promo_code:
            return Decimal("0"), None, False
        promo = await self.repo.get_by_code(promo_code)
        if not promo:
            return Decimal("0"), None, True
        if items_subtotal < Decimal(promo.min_order_amount or 0):
            return Decimal("0"), None, True
        if promo.discount_type == "fixed_rub":
            discount = Decimal(promo.value)
        else:
            discount = (
                items_subtotal * Decimal(promo.value) / Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if promo.max_discount_amount is not None:
            discount = min(discount, Decimal(promo.max_discount_amount))
        discount = min(discount, items_subtotal)
        return max(discount, Decimal("0")), promo, False

    # Снимает промокод с заказа и освобождает usage без commit.
    async def release_promo_for_order(self, order_id: int) -> None:
        await self.repo.delete_usage_for_order(order_id)

    # Фиксирует факт применения промокода в заказе.
    async def register_usage(
        self, promo: PromoCode | None, order_id: int, user_id: int
    ) -> None:
        if not promo:
            return
        await self.repo.create_usage(
            promo_code_id=promo.id, order_id=order_id, user_id=user_id
        )
