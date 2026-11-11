from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.referral import (
    build_referral_link_for_user,
    calculate_commission_amount,
    generate_opaque_referral_code,
    is_legacy_ps_referral_code,
    normalize_referral_alias,
    order_amount_for_referral_commission,
    pending_referral_code,
    validate_referral_alias,
)
from src.core.user_roles import (
    UserRole,
    user_can_be_referred,
    user_can_be_referrer,
    user_has_referral_program,
)
from src.models.order import Order, OrderStatus
from src.models.pricing import ReferralEarning
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.repositories.referral_repo import ReferralRepository
from src.repositories.user_repo import CrudUser
from src.schemas.referral import ReferralAttributionStatus
from src.services.identity_service import IdentityService
from src.services.pricing_service import PricingService

# Начисление реферального % — только при переходе заказа в статус completed.
REFERRAL_ACCRUAL_ORDER_STATUS = OrderStatus.COMPLETED


# Глобальный % реферальной программы.
async def global_commission_percent(session: AsyncSession) -> Decimal:
    pricing = await PricingService(session).get_settings()
    return pricing.referral_commission_percent


ReferralCommissionSource = Literal["global", "individual", "disabled"]


@dataclass(frozen=True)
class ReferralAttributionResult:
    status: ReferralAttributionStatus
    user: User


def user_referral_attribution_locked(user: User) -> bool:
    return bool(user.referral_attribution_locked)


def referral_commission_percent_source(user: User) -> ReferralCommissionSource:
    if user.referral_commission_percent is None:
        return "global"
    if user.referral_commission_percent == Decimal("0"):
        return "disabled"
    return "individual"


async def effective_commission_percent(
    referrer: User, session: AsyncSession
) -> Decimal:
    if referrer.referral_commission_percent is not None:
        return referrer.referral_commission_percent
    return await global_commission_percent(session)


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = CrudUser(session=session, model=User)
        self.referral_repo = ReferralRepository(session)

    # Выделяет уникальный opaque referral_code для покупателя.
    async def _allocate_opaque_referral_code(self, user_id: int) -> str:
        for _ in range(12):
            code = generate_opaque_referral_code()
            existing = await self.user_repo.get_by_referral_code(code)
            if existing is None or existing.id == user_id:
                return code
        raise ValueError("Не удалось сгенерировать уникальный referral code")

    # Генерирует постоянный opaque-код для покупателя.
    async def ensure_referral_code(self, user: User) -> User:
        if not user_has_referral_program(user.role):
            return user
        if user.referral_code and not is_legacy_ps_referral_code(user.referral_code):
            return user
        if user.id is None:
            user.referral_code = pending_referral_code()
            user = await self.referral_repo.save_user(user, commit=False, flush=True)
        user.referral_code = await self._allocate_opaque_referral_code(user.id)
        return await self.referral_repo.save_user(user)

    # Находит id реферера по коду или alias.
    async def resolve_referrer(self, code: str | None) -> int | None:
        raw = (code or "").strip()
        if not raw or is_legacy_ps_referral_code(raw):
            return None
        normalized = normalize_referral_alias(raw)
        if normalized:
            alias_user = await self.user_repo.get_by_referral_alias(normalized)
            if alias_user and user_can_be_referrer(
                alias_user.role, is_active=alias_user.is_active
            ):
                return alias_user.id
        referrer = await self.user_repo.get_by_referral_code(raw)
        if not referrer or not user_can_be_referrer(
            referrer.role, is_active=referrer.is_active
        ):
            return None
        return referrer.id

    # Задаёт или очищает referral alias (только админка, покупатели).
    async def set_admin_referral_alias(self, user: User, raw_alias: str | None) -> User:
        if not user_has_referral_program(user.role):
            raise ValueError(
                "Referral alias доступен только пользователям с ролью «Покупатель»"
            )
        normalized = normalize_referral_alias(raw_alias)
        if not normalized:
            user.referral_alias = None
            return await self.referral_repo.save_user(user)
        error = validate_referral_alias(normalized)
        if error:
            raise ValueError(error)
        existing_alias = await self.user_repo.get_by_referral_alias(normalized)
        if existing_alias and existing_alias.id != user.id:
            raise ValueError("Этот alias уже занят")
        code_owner = await self.user_repo.get_by_referral_code_normalized(normalized)
        if code_owner and code_owner.id != user.id:
            raise ValueError("Alias совпадает с системным кодом другого пользователя")
        user.referral_alias = normalized
        return await self.referral_repo.save_user(user)

    # Задаёт индивидуальный % (NULL — глобальный, 0 — отключить начисления).
    async def set_admin_referral_commission_percent(
        self,
        user: User,
        percent: Decimal | None,
    ) -> User:
        if not user_has_referral_program(user.role):
            raise ValueError(
                "Индивидуальный % доступен только пользователям с ролью «Покупатель»"
            )
        if percent is not None and (percent < 0 or percent > 100):
            raise ValueError("Процент должен быть от 0 до 100")
        user.referral_commission_percent = percent
        return await self.referral_repo.save_user(user)

    # Эффективный % и источник для отображения в ЛК/админке.
    async def referral_commission_view(
        self, user: User
    ) -> tuple[Decimal, ReferralCommissionSource]:
        source = referral_commission_percent_source(user)
        percent = await effective_commission_percent(user, self.session)
        return percent, source

    # Число выполненных заказов покупателя.
    async def count_completed_orders(self, user_id: int) -> int:
        return await CrudOrder(session=self.session, model=Order).count_by_user_status(
            user_id, REFERRAL_ACCRUAL_ORDER_STATUS.value
        )

    # Привязывает реферера, пока referrer_id пуст (без self-referral).
    async def attribute_referrer(
        self, user: User, code: str | None
    ) -> ReferralAttributionResult:
        if not user_can_be_referred(user.role):
            return ReferralAttributionResult(status="not_eligible", user=user)
        if user_referral_attribution_locked(user):
            return ReferralAttributionResult(status="attribution_locked", user=user)
        if user.referrer_id is not None:
            return ReferralAttributionResult(status="already_attributed", user=user)
        raw = (code or "").strip()
        if not raw:
            return ReferralAttributionResult(status="not_eligible", user=user)
        referrer_id = await self.resolve_referrer(raw)
        if referrer_id == user.id:
            return ReferralAttributionResult(status="self_referral", user=user)
        if referrer_id is None:
            return ReferralAttributionResult(status="invalid_code", user=user)
        user.referrer_id = referrer_id
        saved = await self.referral_repo.save_user(user)
        return ReferralAttributionResult(status="attributed", user=saved)

    # Список активных покупателей-рефереров для админки.
    async def list_referral_partners(self) -> list[User]:
        buyers = await self.user_repo.list_by_role(UserRole.BUYER.value)
        return [
            user
            for user in buyers
            if user_can_be_referrer(user.role, is_active=user.is_active)
        ]

    # Проверяет, что назначение реферера не создаст цикл.
    async def _would_create_referrer_cycle(
        self, customer_id: int, referrer_id: int
    ) -> bool:
        seen = {customer_id}
        current_id: int | None = referrer_id
        for _ in range(64):
            if current_id is None:
                return False
            if current_id in seen:
                return True
            seen.add(current_id)
            user = await self.user_repo.get_by_id(current_id)
            if user is None:
                return False
            current_id = user.referrer_id
        return True

    # Назначает реферера из админки (в т.ч. при выполненных заказах).
    async def admin_set_referrer(
        self,
        user: User,
        referrer_id: int | None,
        *,
        admin_user_id: int,
        reason: str,
    ) -> User:
        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise ValueError("Укажите причину изменения реферера")
        if not user_can_be_referred(user.role):
            raise ValueError("Назначение реферера доступно только покупателям")

        old_referrer_id = user.referrer_id
        old_locked = user.referral_attribution_locked

        if referrer_id is not None:
            if referrer_id == user.id:
                raise ValueError("Нельзя назначить клиента рефералом самому себе")
            if await self._would_create_referrer_cycle(user.id, referrer_id):
                raise ValueError("Нельзя назначить реферера: получится цикл в цепочке")
            referrer = await self.user_repo.get_by_id(referrer_id)
            if not referrer:
                raise ValueError("Реферал не найден")
            if not user_can_be_referrer(referrer.role, is_active=referrer.is_active):
                raise ValueError(
                    "У выбранного пользователя нет активной реферальной программы"
                )

        if referrer_id is None:
            if old_referrer_id is None and old_locked:
                raise ValueError("Автопривязка уже заблокирована")
            user.referrer_id = None
            user.referral_attribution_locked = True
        elif referrer_id == old_referrer_id:
            raise ValueError("Реферер не изменился")
        else:
            user.referrer_id = referrer_id
            if old_referrer_id is None:
                user.referral_attribution_locked = False

        await self.referral_repo.save_user(user, commit=False, flush=True)
        await self.referral_repo.create_referral_audit(
            customer_id=user.id,
            admin_user_id=admin_user_id,
            old_referrer_id=old_referrer_id,
            new_referrer_id=user.referrer_id,
            old_attribution_locked=old_locked,
            new_attribution_locked=user.referral_attribution_locked,
            reason=normalized_reason,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Статус привязки покупателя к рефереру для личного кабинета.
    async def get_my_referrer_status(self, user: User) -> dict[str, object]:
        referrer_name: str | None = None
        if user.referrer_id is not None:
            referrer = await self.user_repo.get_by_id(user.referrer_id)
            if referrer:
                tg_username = await IdentityService(
                    self.session
                ).get_telegram_username_for_user(referrer)
                referrer_name = (
                    referrer.name
                    or referrer.email
                    or (f"@{tg_username}" if tg_username else f"Клиент #{referrer.id}")
                )
        return {
            "referrer_id": user.referrer_id,
            "referrer_name": referrer_name,
        }

    # Статистика реферальной программы для личного кабинета.
    async def get_referral_stats(self, user_id: int) -> dict[str, object]:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        if not user_has_referral_program(user.role):
            raise ValueError("Реферальная программа недоступна для этой роли")
        user = await self.ensure_referral_code(user)
        invited_count = await self.referral_repo.count_invited_users(user_id)
        orders_count = await self.referral_repo.count_earnings(user_id)
        total_earned = await self.referral_repo.sum_earnings_amount(user_id)
        recent = await self.referral_repo.list_earnings(referrer_id=user_id, limit=10)
        percent, source = await self.referral_commission_view(user)
        link = build_referral_link_for_user(
            user.referral_alias,
            user.referral_code or "",
        )
        return {
            "referral_code": user.referral_code,
            "referral_alias": user.referral_alias,
            "referral_link": link,
            "commission_percent": percent,
            "commission_percent_source": source,
            "invited_count": invited_count,
            "orders_count": orders_count,
            "total_earned_rub": total_earned,
            "recent_earnings": recent,
        }

    # Данные рефералов для карточки клиента в админке.
    async def get_admin_customer_referral_block(
        self, user_id: int
    ) -> dict[str, object]:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            return {}
        user = await self.ensure_referral_code(user)
        referrer = (
            await self.user_repo.get_by_id(user.referrer_id)
            if user.referrer_id
            else None
        )
        invited_count = await self.referral_repo.count_invited_users(user_id)
        invited_users = await self.referral_repo.list_invited_users(user_id, limit=50)
        total_earned = await self.referral_repo.sum_earnings_amount(user_id)
        earnings = await self.referral_repo.list_earnings(referrer_id=user_id, limit=10)
        audit_rows = await self.referral_repo.list_referral_audit(user_id, limit=10)
        percent, source = await self.referral_commission_view(user)
        link = build_referral_link_for_user(
            user.referral_alias,
            user.referral_code or "",
        )
        return {
            "referral_code": user.referral_code,
            "referral_alias": user.referral_alias,
            "referral_link": link,
            "commission_percent": percent,
            "commission_percent_source": source,
            "referrer": referrer,
            "invited_count": invited_count,
            "invited_users": invited_users,
            "total_earned_rub": total_earned,
            "recent_earnings": earnings,
            "referral_attribution_locked": user.referral_attribution_locked,
            "referral_audit": audit_rows,
        }

    # Начисляет реферальный % за заказ (идемпотентно по order_id).
    async def accrue_for_order(self, order: Order) -> ReferralEarning | None:
        if order.status != REFERRAL_ACCRUAL_ORDER_STATUS:
            return None
        buyer = await self.user_repo.get_by_id(order.user_id)
        if not buyer or not buyer.referrer_id:
            return None
        existing = await self.referral_repo.get_earning_by_order_id(order.id)
        if existing:
            return existing
        referrer = await self.user_repo.get_by_id(buyer.referrer_id)
        if not referrer or not user_can_be_referrer(
            referrer.role, is_active=referrer.is_active
        ):
            return None
        order_base = order_amount_for_referral_commission(order)
        if order_base <= 0:
            return None
        percent = await effective_commission_percent(referrer, self.session)
        if percent <= 0:
            return None
        amount = calculate_commission_amount(order_base, percent)
        earning = ReferralEarning(
            referrer_id=buyer.referrer_id,
            referred_user_id=buyer.id,
            order_id=order.id,
            order_amount_rub=order_base,
            commission_percent=percent,
            commission_amount_rub=amount,
        )
        try:
            async with self.session.begin_nested():
                return await self.referral_repo.save_earning(earning)
        except IntegrityError:
            raced = await self.referral_repo.get_earning_by_order_id(order.id)
            if raced:
                return raced
            raise
