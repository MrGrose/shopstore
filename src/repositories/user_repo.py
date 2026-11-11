import re
from decimal import Decimal

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.core.referral import pending_referral_code
from src.core.user_display import user_display_label
from src.models.auth_identity import AuthIdentity
from src.models.order import Order
from src.models.user import User
from src.repositories.auth_identity_repo import (
    PROVIDER_EMAIL,
    PROVIDER_PHONE,
    PROVIDER_TELEGRAM,
)
from src.repositories.base_repo import CRUDBase


class CrudUser(CRUDBase):
    # Инициализирует репозиторий пользователей.
    def __init__(self, session: AsyncSession, model: type[User]) -> None:
        self.model = model
        self.session = session

    # Возвращает пользователя или создает его.
    async def get_or_create(self, user_id: int) -> User:
        user = (
            await self.session.scalars(
                select(self.model).where(self.model.id == user_id)
            )
        ).first()
        if user:
            return user
        user = self.model(id=user_id)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Возвращает всех пользователей.
    async def list_all(self) -> list[User]:
        result = await self.session.scalars(select(self.model))
        return list(result.all())

    # Фильтр поиска клиентов в админке (имя, email, телефон, Telegram, ID).
    def _admin_search_filter(self, q: str | None):
        if not q or not q.strip():
            return None
        raw = q.strip()
        needle = f"%{raw}%"
        telegram_needle = f"%{raw.lstrip('@')}%"
        identity_clauses = [
            (AuthIdentity.provider == PROVIDER_TELEGRAM)
            & (
                AuthIdentity.meta_json["username"].as_string().ilike(telegram_needle)
                | AuthIdentity.provider_user_id.ilike(needle)
            ),
            (AuthIdentity.provider == PROVIDER_EMAIL)
            & (AuthIdentity.email.ilike(needle)),
        ]
        phone_digits = re.sub(r"\D", "", raw)
        if len(phone_digits) >= 3:
            identity_clauses.append(
                (AuthIdentity.provider == PROVIDER_PHONE)
                & (
                    func.replace(AuthIdentity.provider_user_id, "+", "").ilike(
                        f"%{phone_digits}%"
                    )
                )
            )
        identity_user_ids = select(AuthIdentity.user_id).where(or_(*identity_clauses))
        user_clauses = [
            self.model.name.ilike(needle),
            self.model.email.ilike(needle),
            cast(self.model.id, String).ilike(needle),
            self.model.id.in_(identity_user_ids),
        ]
        id_token = raw.lstrip("#")
        if id_token.isdigit():
            user_clauses.append(self.model.id == int(id_token))
        return or_(*user_clauses)

    # Количество клиентов для админки.
    async def count_admin(self, q: str | None = None) -> int:
        stmt = select(func.count(self.model.id))
        search = self._admin_search_filter(q)
        if search is not None:
            stmt = stmt.where(search)
        total = await self.session.scalar(stmt)
        return int(total or 0)

    # Список клиентов с агрегатами заказов для таблицы админки.
    async def list_admin_enriched(
        self,
        q: str | None = None,
        offset: int = 0,
        limit: int = 30,
    ) -> list[dict[str, object]]:
        orders_count = func.count(Order.id)
        total_spent = func.coalesce(
            func.sum(Order.total_amount).filter(Order.payment_paid_at.is_not(None)),
            0,
        )
        Referrer = aliased(self.model)
        stmt = (
            select(self.model, orders_count, total_spent, Referrer)
            .outerjoin(Order, Order.user_id == self.model.id)
            .outerjoin(Referrer, Referrer.id == self.model.referrer_id)
            .group_by(self.model.id, Referrer.id)
        )
        search = self._admin_search_filter(q)
        if search is not None:
            stmt = stmt.where(search)
        stmt = stmt.order_by(self.model.id.desc()).offset(offset).limit(limit)
        rows = await self.session.execute(stmt)
        result: list[dict[str, object]] = []
        for user, oc, spent, referrer in rows.all():
            count = int(oc or 0)
            referrer_name = (
                user_display_label(referrer)
                if referrer is not None and referrer.id is not None
                else None
            )
            result.append(
                {
                    "user": user,
                    "orders_count": count,
                    "total_spent": spent if spent is not None else Decimal("0"),
                    "has_referrer": user.referrer_id is not None,
                    "referrer_name": referrer_name,
                }
            )
        return result

    # Сводка по клиентам для шапки страницы админки.
    async def admin_customers_summary(self) -> dict[str, object]:
        total_clients = await self.count_admin(q=None)
        total_orders = int(await self.session.scalar(select(func.count(Order.id))) or 0)
        total_revenue = await self.session.scalar(
            select(func.coalesce(func.sum(Order.total_amount), 0))
        ) or Decimal("0")
        active_subq = (
            select(self.model.id)
            .join(Order, Order.user_id == self.model.id)
            .group_by(self.model.id)
            .having(func.count(Order.id) >= 2)
            .subquery()
        )
        active_count = int(
            await self.session.scalar(select(func.count()).select_from(active_subq))
            or 0
        )
        return {
            "total_clients": total_clients,
            "active_count": active_count,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
        }

    # Ищет пользователя по email.
    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.email == email)
        )
        return result.first()

    # Список пользователей с указанной ролью (для выбора реферера в админке).
    async def list_by_role(self, role: str) -> list[User]:
        result = await self.session.scalars(
            select(self.model)
            .where(self.model.role == role.strip().lower())
            .order_by(self.model.name.asc().nulls_last(), self.model.id.asc())
        )
        return list(result.all())

    # Ищет пользователя по реферальному коду.
    async def get_by_referral_code(self, code: str) -> User | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.referral_code == code)
        )
        return result.first()

    # Ищет пользователя по referral alias (уже normalized).
    async def get_by_referral_alias(self, normalized: str) -> User | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.referral_alias == normalized)
        )
        return result.first()

    # Ищет пользователя по referral_code без учёта регистра.
    async def get_by_referral_code_normalized(self, normalized: str) -> User | None:
        result = await self.session.scalars(
            select(self.model).where(func.lower(self.model.referral_code) == normalized)
        )
        return result.first()

    # Создает нового пользователя с email и именем.
    async def create_user(
        self,
        email: str | None = None,
        name: str | None = None,
        role: str = "buyer",
    ) -> User:
        user = self.model(
            email=email,
            name=name,
            role=role,
            referral_code=pending_referral_code(),
        )
        self.session.add(user)
        try:
            await self.session.commit()
            await self.session.refresh(user)
            return user
        except IntegrityError as exc:
            await self.session.rollback()
            raise exc
