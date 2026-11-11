from decimal import Decimal

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.user_display import user_display_label
from src.core.user_roles import UserRole, resolve_role_for_telegram_id
from src.models.cart import CartItem
from src.models.order import Order
from src.models.pricing import PromoCodeUsage, ReferralEarning
from src.models.user import User
from src.repositories.auth_identity_repo import AuthIdentityRepository
from src.repositories.cart_repo import CrudCart
from src.repositories.referral_repo import ReferralRepository
from src.repositories.user_repo import CrudUser
from src.schemas.user import UserCreate, UserUpdate
from src.services.identity_service import IdentityService
from src.services.orders.order_service import OrderService
from src.services.referral_service import ReferralService
from src.services.support import SupportService
from src.utils.phone import format_ru_phone_display, normalize_ru_mobile_phone

_ALLOWED_ADMIN_CUSTOMER_ROLES = frozenset({UserRole.BUYER.value, UserRole.ADMIN.value})


class UserService:
    # Инициализирует зависимости для работы с пользователем.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_crud = CrudUser(session=session, model=User)

    # Возвращает пользователя или создает его при отсутствии.
    async def ensure_user(self, user_id: int) -> User:
        return await self.user_crud.get_or_create(user_id=user_id)

    # Возвращает всех пользователей.
    async def get_users(self) -> list[User]:
        return await self.user_crud.list_all()

    # Возвращает пользователя по id или None, если не найден.
    async def get_user(self, user_id: int) -> User | None:
        return await self.user_crud.get_by_id(id=user_id)

    # Список клиентов для админки с агрегатами заказов.
    async def list_admin_users(
        self,
        page: int = 1,
        page_size: int = 30,
        q: str | None = None,
    ) -> dict[str, object]:
        offset = (page - 1) * page_size
        total = await self.user_crud.count_admin(q=q)
        items = await self.user_crud.list_admin_enriched(
            q=q,
            offset=offset,
            limit=page_size,
        )
        user_ids = [user.id for row in items if isinstance((user := row["user"]), User)]
        identity_svc = IdentityService(self.session)
        profiles = await identity_svc.map_telegram_profiles(user_ids)
        phones = await identity_svc.map_phones_for_users(user_ids)
        for row in items:
            user_obj = row["user"]
            if not isinstance(user_obj, User):
                continue
            telegram_id, telegram_username = profiles.get(user_obj.id, (None, None))
            login_phone_e164 = phones.get(user_obj.id)
            row["telegram_id"] = telegram_id
            row["telegram_username"] = telegram_username
            row["login_phone_e164"] = login_phone_e164
            row["display_name"] = user_display_label(
                user_obj,
                login_phone_e164=login_phone_e164,
            )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # Сводная статистика по клиентам для страницы админки.
    async def get_admin_customers_summary(self) -> dict[str, object]:
        return await self.user_crud.admin_customers_summary()

    # Детали клиента для админки: профиль, заказы, корзина.
    async def get_admin_customer_detail(
        self,
        user_id: int,
    ) -> dict[str, object] | None:
        user = await self.get_user(user_id)
        if not user:
            return None
        identity_svc = IdentityService(self.session)
        if not user.email:
            for item in await identity_svc.list_identities_for_user(user.id):
                if item.provider == "email" and item.email:
                    user.email = item.email
                    break
        from src.services.cart_service import CartService
        from src.services.delivery_profile_service import DeliveryProfileService

        order_service = OrderService(self.session)
        orders = await order_service.list_orders(user_id=user_id, page=1, page_size=10)
        try:
            cart = await CartService(self.session).get_cart(user_id=user_id)
        except Exception:
            cart = None
        orders_count = await order_service.count_user_orders(user_id)
        completed_orders_count = await order_service.count_completed_user_orders(
            user_id
        )
        referral_svc = ReferralService(self.session)
        referral = await referral_svc.get_admin_customer_referral_block(user_id)
        await self.session.refresh(user)
        referral_partners = await referral_svc.list_referral_partners()
        telegram_id = await identity_svc.get_telegram_id_for_user(user)
        telegram_username = await identity_svc.get_telegram_username_for_user(user)
        login_phone_e164 = await identity_svc.get_phone_e164_for_user(user)
        login_phone_display = (
            format_ru_phone_display(login_phone_e164) if login_phone_e164 else None
        )
        delivery_profile = await DeliveryProfileService(self.session).get_profile(
            user_id
        )
        can_delete_customer = user.role != UserRole.ADMIN.value
        return {
            "user": user,
            "orders": orders,
            "cart": cart,
            "orders_count": orders_count,
            "completed_orders_count": completed_orders_count,
            "can_delete_customer": can_delete_customer,
            "referral": referral,
            "referral_partners": referral_partners,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "login_phone_e164": login_phone_e164,
            "login_phone_display": login_phone_display,
            "delivery_profile": delivery_profile,
        }

    # Создает пользователя из API-пейлоада.
    async def create_user(self, user: UserCreate) -> User:
        return await self.user_crud.create(obj_in=user)

    # Меняет реферера клиента из админки (будущие заказы — новому рефереру).
    async def set_admin_customer_referrer(
        self,
        user_id: int,
        referrer_id: int | None,
        *,
        admin_user_id: int,
        reason: str,
    ) -> User:
        user = await self.get_user(user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        return await ReferralService(self.session).admin_set_referrer(
            user,
            referrer_id,
            admin_user_id=admin_user_id,
            reason=reason,
        )

    # Задаёт или очищает referral alias клиента из админки.
    async def set_admin_customer_referral_alias(
        self,
        user_id: int,
        raw_alias: str | None,
    ) -> User:
        user = await self.get_user(user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        return await ReferralService(self.session).set_admin_referral_alias(
            user, raw_alias
        )

    # Задаёт индивидуальный % реферальных начислений клиента.
    async def set_admin_customer_referral_commission_percent(
        self,
        user_id: int,
        percent: Decimal | None,
    ) -> User:
        user = await self.get_user(user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        return await ReferralService(
            self.session
        ).set_admin_referral_commission_percent(user, percent)

    # Безвозвратно удаляет клиента и все связанные данные.
    async def delete_admin_customer(
        self,
        user_id: int,
        *,
        allow_admin: bool = False,
    ) -> None:
        user = await self.get_user(user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        if user.role == UserRole.ADMIN.value and not allow_admin:
            raise ValueError("Нельзя удалить администратора")

        order_service = OrderService(self.session)
        order_ids = [
            int(order_id)
            for order_id in await self.session.scalars(
                select(Order.id).where(Order.user_id == user_id)
            )
        ]
        if order_ids:
            await order_service.admin_delete_orders_by_ids(order_ids)

        await self.session.execute(
            delete(ReferralEarning).where(
                or_(
                    ReferralEarning.referrer_id == user_id,
                    ReferralEarning.referred_user_id == user_id,
                )
            )
        )
        await SupportService(self.session).delete_for_user(user_id)
        await CrudCart(session=self.session, model=CartItem).clear_user_cart(user_id)
        await self.session.execute(
            delete(PromoCodeUsage).where(PromoCodeUsage.user_id == user_id)
        )
        referral_repo = ReferralRepository(self.session)
        await referral_repo.delete_audit_for_user(user_id)
        await self.session.execute(
            update(User).where(User.referrer_id == user_id).values(referrer_id=None)
        )
        await self.delete_user(user_id)

    # Удаляет выбранных клиентов; пропускает тех, кого нельзя удалить.
    async def delete_admin_customers_by_ids(
        self, user_ids: list[int]
    ) -> dict[str, object]:
        unique_ids = sorted({int(user_id) for user_id in user_ids if int(user_id) > 0})
        if not unique_ids:
            raise ValueError("Не выбраны клиенты")
        deleted = 0
        skipped: list[str] = []
        for user_id in unique_ids:
            try:
                await self.delete_admin_customer(user_id)
                deleted += 1
            except ValueError as exc:
                skipped.append(f"#{user_id}: {exc}")
        if deleted == 0:
            if len(skipped) == 1:
                raise ValueError(skipped[0].split(": ", 1)[-1])
            raise ValueError(f"Не удалось удалить {len(skipped)} клиентов")
        message = f"Удалено клиентов: {deleted}"
        if skipped:
            reason_counts: dict[str, int] = {}
            for item in skipped:
                reason = item.split(": ", 1)[-1]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            reason_text = "; ".join(
                f"{count}× {reason}" for reason, count in reason_counts.items()
            )
            message = f"{message}. Пропущено: {len(skipped)} ({reason_text})"
        return {
            "deleted": deleted,
            "skipped": len(skipped),
            "errors": skipped,
            "message": message,
        }

    # Обновляет профиль клиента из админки.
    async def update_admin_customer(
        self,
        user_id: int,
        name: str | None,
        email: str | None,
        telegram_username: str | None,
        telegram_id: str | None,
        login_phone: str | None,
        role: str | None,
        is_deactivated: bool = False,
    ) -> User:
        db_obj = await self.get_user(user_id)
        if db_obj is None:
            raise ValueError("Пользователь не найден")
        normalized_name = name.strip() if name and name.strip() else None
        normalized_email = email.strip().lower() if email and email.strip() else None
        phone_e164: str | None = None
        if login_phone and login_phone.strip():
            phone_e164 = normalize_ru_mobile_phone(login_phone)
        telegram_id_int: int | None = None
        if telegram_id and str(telegram_id).strip():
            try:
                telegram_id_int = int(str(telegram_id).strip())
            except ValueError as exc:
                raise ValueError("Telegram ID должен быть числом") from exc
            if telegram_id_int <= 0:
                raise ValueError("Некорректный Telegram ID")
        if normalized_email:
            existing = await self.user_crud.get_by_email(normalized_email)
            if existing is not None and existing.id != user_id:
                raise ValueError("Email уже занят другим пользователем")
        raw_username = (telegram_username or "").strip().lstrip("@")
        normalized_username = raw_username or None
        role_value = (role or "").strip().lower()
        if role_value not in _ALLOWED_ADMIN_CUSTOMER_ROLES:
            raise ValueError("Недопустимая роль")
        if is_deactivated and role_value == UserRole.ADMIN.value:
            raise ValueError("Нельзя деактивировать администратора")
        user_patch = UserUpdate(
            name=normalized_name,
            email=normalized_email,
            role=role_value,
        )
        if role_value != UserRole.ADMIN.value:
            user_patch.is_active = not is_deactivated
        updated = await self.update_user(user_id, user_patch)
        if updated is None:
            raise ValueError("Пользователь не найден")
        if role_value == UserRole.BUYER.value:
            referral_svc = ReferralService(self.session)
            updated = await referral_svc.ensure_referral_code(updated)
        identity_svc = IdentityService(self.session)
        if updated:
            await identity_svc.admin_set_email_for_user(updated, normalized_email)
            await self.session.refresh(updated)
            await identity_svc.admin_set_phone_for_user(updated, phone_e164)
            await self.session.refresh(updated)
            updated = await identity_svc.admin_set_telegram_for_user(
                updated,
                telegram_id_int,
                normalized_username,
            )
            await identity_svc.update_telegram_username_for_user(
                updated, normalized_username
            )
            updated = await self.refresh_user_role_from_telegram_allowlist(updated)
        return updated

    # Частично обновляет пользователя; возвращает None, если не найден.
    async def update_user(self, user_id: int, user: UserUpdate) -> User | None:
        db_obj = await self.user_crud.get_by_id(id=user_id)
        if db_obj is None:
            return None
        return await self.user_crud.update(db_obj=db_obj, obj_in=user)

    # Удаляет пользователя по id; бросает ValueError, если не найден.
    async def delete_user(self, user_id: int) -> User:
        await AuthIdentityRepository(self.session).delete_for_user(user_id)
        return await self.user_crud.delete(id=user_id)

    # Проверяет, есть ли пользователь с указанным email.
    async def check_email_exists(self, email: str) -> bool:
        return await self.user_crud.get_by_email(email.strip()) is not None

    # Возвращает пользователя по email или None.
    async def get_user_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        if not normalized:
            return None
        return await self.user_crud.get_by_email(normalized)

    # Регистрирует пользователя по email.
    async def register_user(
        self,
        email: str,
        name: str | None = None,
        role: str = UserRole.BUYER.value,
        referral_code: str | None = None,
    ) -> User:
        normalized_email = email.strip().lower()
        existing = await self.user_crud.get_by_email(normalized_email)
        if existing:
            raise ValueError("Пользователь с таким email уже существует")
        normalized_name = name.strip() if name else None
        user = await self.user_crud.create_user(
            email=normalized_email,
            name=normalized_name,
            role=role,
        )
        referral_svc = ReferralService(self.session)
        user = await referral_svc.ensure_referral_code(user)
        await IdentityService(self.session).ensure_email_identity_for_user(
            user, normalized_email
        )
        result = await referral_svc.attribute_referrer(user, referral_code)
        return result.user

    # Регистрирует покупателя только с phone identity.
    async def register_user_by_phone(
        self,
        phone_e164: str,
        role: str = UserRole.BUYER.value,
        referral_code: str | None = None,
    ) -> User:
        existing = await IdentityService(self.session).resolve_user_by_phone(phone_e164)
        if existing:
            raise ValueError("Пользователь с таким телефоном уже существует")
        user = await self.user_crud.create_user(
            email=None,
            name=None,
            role=role,
        )
        referral_svc = ReferralService(self.session)
        user = await referral_svc.ensure_referral_code(user)
        await IdentityService(self.session).ensure_phone_identity_for_user(
            user,
            phone_e164,
        )
        result = await referral_svc.attribute_referrer(user, referral_code)
        return result.user

    # Возвращает пользователя по telegram_id через auth_identities.
    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await IdentityService(self.session).resolve_user_by_telegram_id(
            telegram_id
        )

    # Создает или обновляет профиль пользователя из Telegram.
    async def upsert_telegram_user(
        self,
        telegram_id: int,
        telegram_username: str | None,
        name: str | None,
        referral_code: str | None = None,
        photo_url: str | None = None,
    ) -> User:
        identity_svc = IdentityService(self.session)
        user = await identity_svc.ensure_telegram_identity(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            name=name,
            photo_url=photo_url,
        )
        referral_svc = ReferralService(self.session)
        user = await referral_svc.ensure_referral_code(user)
        if referral_code:
            result = await referral_svc.attribute_referrer(user, referral_code)
            user = result.user
        return user

    # Синхронизирует роль пользователя с ADMIN_TG_IDS (например после смены env).
    async def refresh_user_role_from_telegram_allowlist(self, user: User) -> User:
        identity_svc = IdentityService(self.session)
        telegram_id = await identity_svc.get_telegram_id_for_user(user)
        if telegram_id is None:
            return user
        want = resolve_role_for_telegram_id(telegram_id)
        if user.role == want:
            return user
        user.role = want
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
