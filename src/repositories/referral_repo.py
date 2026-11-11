from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pricing import CustomerReferralAudit, ReferralEarning
from src.models.user import User


class ReferralRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Сохраняет пользователя (commit или flush).
    async def save_user(
        self,
        user: User,
        *,
        commit: bool = True,
        flush: bool = False,
    ) -> User:
        self.session.add(user)
        if flush:
            await self.session.flush()
        if commit:
            await self.session.commit()
            await self.session.refresh(user)
        elif flush:
            await self.session.refresh(user)
        return user

    # Число приглашённых пользователей.
    async def count_invited_users(self, referrer_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count(User.id)).where(User.referrer_id == referrer_id)
            )
            or 0
        )

    # Список приглашённых пользователей (для карточки клиента в админке).
    async def list_invited_users(self, referrer_id: int, limit: int = 50) -> list[User]:
        result = await self.session.scalars(
            select(User)
            .where(User.referrer_id == referrer_id)
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    # Число реферальных начислений рефереру.
    async def count_earnings(self, referrer_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count(ReferralEarning.id)).where(
                    ReferralEarning.referrer_id == referrer_id
                )
            )
            or 0
        )

    # Сумма начислений рефереру.
    async def sum_earnings_amount(self, referrer_id: int) -> Decimal:
        return await self.session.scalar(
            select(
                func.coalesce(func.sum(ReferralEarning.commission_amount_rub), 0)
            ).where(ReferralEarning.referrer_id == referrer_id)
        ) or Decimal("0")

    # Начисления, где пользователь реферер или приглашённый.
    async def count_earnings_for_user(self, user_id: int) -> int:
        return int(
            await self.session.scalar(
                select(func.count(ReferralEarning.id)).where(
                    or_(
                        ReferralEarning.referrer_id == user_id,
                        ReferralEarning.referred_user_id == user_id,
                    )
                )
            )
            or 0
        )

    # Последние начисления рефереру.
    async def list_earnings(
        self, referrer_id: int, limit: int = 10
    ) -> list[ReferralEarning]:
        result = await self.session.scalars(
            select(ReferralEarning)
            .where(ReferralEarning.referrer_id == referrer_id)
            .order_by(ReferralEarning.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    # Начисление по заказу (идемпотентность).
    async def get_earning_by_order_id(self, order_id: int) -> ReferralEarning | None:
        result = await self.session.scalars(
            select(ReferralEarning).where(ReferralEarning.order_id == order_id)
        )
        return result.first()

    # Начисления по списку заказов (финансовый разбор периода).
    async def list_earnings_by_order_ids(
        self, order_ids: list[int]
    ) -> dict[int, ReferralEarning]:
        if not order_ids:
            return {}
        result = await self.session.scalars(
            select(ReferralEarning).where(ReferralEarning.order_id.in_(order_ids))
        )
        return {earning.order_id: earning for earning in result.all()}

    # Создаёт запись начисления (flush в текущей транзакции, без commit).
    async def save_earning(self, earning: ReferralEarning) -> ReferralEarning:
        self.session.add(earning)
        await self.session.flush()
        await self.session.refresh(earning)
        return earning

    # Записывает audit смены реферера админом.
    async def create_referral_audit(
        self,
        *,
        customer_id: int,
        admin_user_id: int,
        old_referrer_id: int | None,
        new_referrer_id: int | None,
        old_attribution_locked: bool,
        new_attribution_locked: bool,
        reason: str,
    ) -> CustomerReferralAudit:
        row = CustomerReferralAudit(
            customer_id=customer_id,
            admin_user_id=admin_user_id,
            old_referrer_id=old_referrer_id,
            new_referrer_id=new_referrer_id,
            old_attribution_locked=old_attribution_locked,
            new_attribution_locked=new_attribution_locked,
            reason=reason,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # История смен реферера для карточки клиента.
    async def list_referral_audit(
        self, customer_id: int, limit: int = 20
    ) -> list[CustomerReferralAudit]:
        result = await self.session.scalars(
            select(CustomerReferralAudit)
            .where(CustomerReferralAudit.customer_id == customer_id)
            .order_by(CustomerReferralAudit.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    # Удаляет audit-записи, связанные с пользователем (перед delete user).
    async def delete_audit_for_user(self, user_id: int) -> None:
        await self.session.execute(
            delete(CustomerReferralAudit).where(
                or_(
                    CustomerReferralAudit.customer_id == user_id,
                    CustomerReferralAudit.admin_user_id == user_id,
                    CustomerReferralAudit.old_referrer_id == user_id,
                    CustomerReferralAudit.new_referrer_id == user_id,
                )
            )
        )
        await self.session.flush()
