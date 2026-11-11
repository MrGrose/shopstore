from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.referral import pending_referral_code
from src.core.user_roles import resolve_role_for_telegram_id, user_has_referral_program
from src.models.auth_identity import AuthIdentity
from src.models.order import Order
from src.models.pricing import ReferralEarning
from src.models.user import User
from src.models.user_delivery_profile import UserDeliveryProfile
from src.repositories.auth_identity_repo import (
    PROVIDER_EMAIL,
    PROVIDER_PHONE,
    PROVIDER_TELEGRAM,
    AuthIdentityRepository,
)
from src.repositories.referral_repo import ReferralRepository
from src.repositories.user_repo import CrudUser

# Способы входа: phone (звонок / код в TG), telegram (Mini App / widget).
_LOGIN_PROVIDERS = frozenset({PROVIDER_PHONE, PROVIDER_TELEGRAM})


class IdentityService:
    # Инициализирует сервис identities.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity_repo = AuthIdentityRepository(session)
        self.user_crud = CrudUser(session=session, model=User)

    # Ищет пользователя по telegram_id через auth_identities.
    async def resolve_user_by_telegram_id(self, telegram_id: int) -> User | None:
        identity = await self.identity_repo.get_by_provider(
            PROVIDER_TELEGRAM,
            str(telegram_id),
        )
        if identity is None:
            return None
        return await self.user_crud.get_by_id(id=identity.user_id)

    # Возвращает telegram_id пользователя из identity.
    async def get_telegram_id_for_user(self, user: User) -> int | None:
        identity = await self.identity_repo.get_telegram_for_user(user.id)
        if identity is None:
            return None
        try:
            return int(identity.provider_user_id)
        except ValueError:
            return None

    # Возвращает telegram username из meta_json identity.
    async def get_telegram_username_for_user(self, user: User) -> str | None:
        identity = await self.identity_repo.get_telegram_for_user(user.id)
        if identity is None or not isinstance(identity.meta_json, dict):
            return None
        raw = identity.meta_json.get("username")
        if not raw:
            return None
        normalized = str(raw).strip().lstrip("@")
        return normalized or None

    # Возвращает E.164 телефона входа из phone-identity.
    async def get_phone_e164_for_user(self, user: User) -> str | None:
        for identity in await self.identity_repo.list_for_user(user.id):
            if identity.provider == PROVIDER_PHONE:
                value = identity.provider_user_id.strip()
                return value or None
        return None

    # Пакетно возвращает E.164 телефонов входа для списка user_id.
    async def map_phones_for_users(self, user_ids: list[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.user_id.in_(user_ids),
                AuthIdentity.provider == PROVIDER_PHONE,
            )
        )
        phones: dict[int, str] = {}
        for identity in result.all():
            value = identity.provider_user_id.strip()
            if value:
                phones[identity.user_id] = value
        return phones

    # Пакетно возвращает telegram-профили для списка user_id.
    async def map_telegram_profiles(
        self,
        user_ids: list[int],
    ) -> dict[int, tuple[int | None, str | None]]:
        if not user_ids:
            return {}
        result = await self.session.scalars(
            select(AuthIdentity).where(
                AuthIdentity.user_id.in_(user_ids),
                AuthIdentity.provider == PROVIDER_TELEGRAM,
            )
        )
        profiles: dict[int, tuple[int | None, str | None]] = {}
        for identity in result.all():
            telegram_id: int | None = None
            try:
                telegram_id = int(identity.provider_user_id)
            except ValueError:
                pass
            username: str | None = None
            if isinstance(identity.meta_json, dict):
                raw = identity.meta_json.get("username")
                if raw:
                    username = str(raw).strip().lstrip("@") or None
            profiles[identity.user_id] = (telegram_id, username)
        return profiles

    # Создаёт или обновляет telegram-identity пользователя.
    async def ensure_telegram_identity(
        self,
        telegram_id: int,
        telegram_username: str | None,
        name: str | None,
        photo_url: str | None = None,
    ) -> User:
        normalized_name = name.strip() if name else None
        normalized_username = (
            telegram_username.strip().lstrip("@") if telegram_username else None
        )
        meta = {
            "username": normalized_username,
            "photo_url": photo_url.strip() if photo_url else None,
        }
        role = resolve_role_for_telegram_id(telegram_id)
        provider_user_id = str(telegram_id)

        identity = await self.identity_repo.get_by_provider(
            PROVIDER_TELEGRAM,
            provider_user_id,
        )
        if identity is not None:
            user = await self.user_crud.get_by_id(id=identity.user_id)
            if user is None:
                raise ValueError("Пользователь identity не найден")
            return await self._sync_telegram_user(
                user=user,
                identity=identity,
                name=normalized_name,
                photo_url=photo_url,
                role=role,
                meta=meta,
            )

        user = User(
            name=normalized_name,
            role=role,
            referral_code=pending_referral_code(),
        )
        if photo_url and photo_url.strip():
            user.avatar = photo_url.strip()
        self.session.add(user)
        await self.session.flush()

        await self.identity_repo.create(
            user_id=user.id,
            provider=PROVIDER_TELEGRAM,
            provider_user_id=provider_user_id,
            meta_json=meta,
            auto_commit=False,
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Создаёт email-identity с UUID provider_user_id.
    async def ensure_email_identity_for_user(
        self,
        user: User,
        email: str,
    ) -> AuthIdentity:
        normalized = email.strip().lower()
        existing = await self.identity_repo.get_email_by_address(normalized)
        if existing is not None:
            if existing.user_id != user.id:
                raise ValueError("Email уже привязан к другому аккаунту")
            return existing
        existing_for_user = await self._find_email_identity_for_user(user.id)
        if existing_for_user is not None:
            existing_for_user.email = normalized
            self.session.add(existing_for_user)
            await self.session.commit()
            await self.session.refresh(existing_for_user)
            return existing_for_user
        return await self.identity_repo.create(
            user_id=user.id,
            provider=PROVIDER_EMAIL,
            provider_user_id=str(uuid4()),
            email=normalized,
        )

    # Возвращает пользователя по email через identity → users.email.
    async def resolve_user_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        identity = await self.identity_repo.get_email_by_address(normalized)
        if identity is not None:
            return await self.user_crud.get_by_id(id=identity.user_id)
        return await self.user_crud.get_by_email(normalized)

    # Возвращает пользователя по phone identity (E.164).
    async def resolve_user_by_phone(self, phone_e164: str) -> User | None:
        identity = await self.identity_repo.get_phone_by_number(phone_e164)
        if identity is None:
            return None
        return await self.user_crud.get_by_id(id=identity.user_id)

    # Создаёт phone-identity для пользователя.
    async def ensure_phone_identity_for_user(
        self,
        user: User,
        phone_e164: str,
    ) -> AuthIdentity:
        existing = await self.identity_repo.get_phone_by_number(phone_e164)
        if existing is not None:
            if existing.user_id != user.id:
                raise ValueError("Телефон уже привязан к другому аккаунту")
            return existing
        existing_for_user = await self.identity_repo.get_phone_for_user(user.id)
        if existing_for_user is not None:
            existing_for_user.provider_user_id = phone_e164
            self.session.add(existing_for_user)
            await self.session.commit()
            await self.session.refresh(existing_for_user)
            return existing_for_user
        return await self.identity_repo.create(
            user_id=user.id,
            provider=PROVIDER_PHONE,
            provider_user_id=phone_e164,
        )

    # Привязывает phone к текущему пользователю после verify (с merge phone-only donor).
    async def link_phone_to_user(self, user: User, phone_e164: str) -> User:
        conflict_msg = "Телефон уже привязан к другому аккаунту"
        existing = await self.identity_repo.get_phone_by_number(phone_e164)

        if existing is not None and existing.user_id == user.id:
            return user

        if existing is None:
            if await self.identity_repo.get_phone_for_user(user.id) is not None:
                raise ValueError(conflict_msg)
            await self.ensure_phone_identity_for_user(user, phone_e164)
            await self.session.refresh(user)
            return user

        if await self.identity_repo.get_phone_for_user(user.id) is not None:
            raise ValueError(conflict_msg)

        donor = await self.user_crud.get_by_id(id=existing.user_id)
        if donor is None or not await self._try_merge_complementary_accounts(
            donor=donor,
            survivor=user,
            donor_provider=PROVIDER_PHONE,
        ):
            raise ValueError(conflict_msg)

        refreshed = await self.user_crud.get_by_id(id=user.id)
        if refreshed is None:
            raise ValueError("Пользователь не найден")
        return refreshed

    # Привязывает email к текущему пользователю после OTP.
    async def link_email_to_user(self, user: User, email: str) -> User:
        normalized = email.strip().lower()
        existing = await self.identity_repo.get_email_by_address(normalized)
        if existing is not None and existing.user_id != user.id:
            donor = await self.user_crud.get_by_id(id=existing.user_id)
            if donor is None or not await self._try_merge_complementary_accounts(
                donor=donor,
                survivor=user,
                donor_provider=PROVIDER_EMAIL,
            ):
                raise ValueError("Email уже привязан к другому аккаунту")
            merged = await self.user_crud.get_by_id(id=user.id)
            if merged is None:
                raise ValueError("Пользователь не найден")
            if not merged.email:
                merged.email = normalized
                self.session.add(merged)
                await self.session.commit()
            await self.session.refresh(merged)
            return merged
        await self.ensure_email_identity_for_user(user, normalized)
        user.email = normalized
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Привязывает Telegram к текущему пользователю (не создаёт новый аккаунт).
    async def link_telegram_to_user(
        self,
        user: User,
        telegram_id: int,
        telegram_username: str | None,
        name: str | None,
        photo_url: str | None = None,
    ) -> User:
        provider_user_id = str(telegram_id)
        conflict = await self.identity_repo.get_by_provider(
            PROVIDER_TELEGRAM,
            provider_user_id,
        )
        if conflict is not None and conflict.user_id != user.id:
            donor = await self.user_crud.get_by_id(id=conflict.user_id)
            if donor is None or not await self._try_merge_complementary_accounts(
                donor=donor,
                survivor=user,
                donor_provider=PROVIDER_TELEGRAM,
            ):
                raise ValueError("Telegram уже привязан к другому аккаунту")
            refreshed = await self.user_crud.get_by_id(id=user.id)
            if refreshed is None:
                raise ValueError("Пользователь не найден")
            user = refreshed

        normalized_username = (
            telegram_username.strip().lstrip("@") if telegram_username else None
        )
        meta = {
            "username": normalized_username,
            "photo_url": photo_url.strip() if photo_url else None,
        }
        identity = await self.identity_repo.get_telegram_for_user(user.id)
        if identity is None:
            identity = await self.identity_repo.create(
                user_id=user.id,
                provider=PROVIDER_TELEGRAM,
                provider_user_id=provider_user_id,
                meta_json=meta,
                auto_commit=False,
            )
        else:
            identity.provider_user_id = provider_user_id
            identity.meta_json = meta
            self.session.add(identity)

        user.name = name or user.name
        if photo_url and photo_url.strip():
            user.avatar = photo_url.strip()
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Обновляет telegram username в meta_json identity пользователя.
    async def update_telegram_username_for_user(
        self,
        user: User,
        telegram_username: str | None,
    ) -> None:
        identity = await self.identity_repo.get_telegram_for_user(user.id)
        if identity is None:
            return
        normalized = (
            telegram_username.strip().lstrip("@") if telegram_username else None
        )
        meta = identity.meta_json if isinstance(identity.meta_json, dict) else {}
        meta = {**meta, "username": normalized}
        identity.meta_json = meta
        self.session.add(identity)
        await self.session.commit()

    # Список identities пользователя для API.
    async def list_identities_for_user(self, user_id: int) -> list[AuthIdentity]:
        return await self.identity_repo.list_for_user(user_id)

    # Меняет или снимает email-identity из админки.
    async def admin_set_email_for_user(
        self,
        user: User,
        email: str | None,
    ) -> None:
        current = await self._find_email_identity_for_user(user.id)
        if email:
            normalized = email.strip().lower()
            existing = await self.identity_repo.get_email_by_address(normalized)
            if existing is not None and existing.user_id != user.id:
                raise ValueError("Email уже привязан к другому аккаунту")
            if (
                current is not None
                and current.email == normalized
                and user.email == normalized
            ):
                return
            if current is not None:
                current.email = normalized
                self.session.add(current)
            else:
                await self.identity_repo.create(
                    user_id=user.id,
                    provider=PROVIDER_EMAIL,
                    provider_user_id=str(uuid4()),
                    email=normalized,
                    auto_commit=False,
                )
            user.email = normalized
            self.session.add(user)
            await self.session.commit()
            return
        if current is None and not user.email:
            return
        if current is not None:
            await self.session.delete(current)
        user.email = None
        self.session.add(user)
        await self.session.commit()

    # Меняет или снимает phone-identity из админки (E.164 или None = удалить).
    async def admin_set_phone_for_user(
        self,
        user: User,
        phone_e164: str | None,
    ) -> None:
        current = await self.identity_repo.get_phone_for_user(user.id)
        if phone_e164:
            existing = await self.identity_repo.get_phone_by_number(phone_e164)
            if existing is not None and existing.user_id != user.id:
                raise ValueError("Телефон уже привязан к другому аккаунту")
            if current is not None and current.provider_user_id == phone_e164:
                return
            if current is not None:
                current.provider_user_id = phone_e164
                self.session.add(current)
            else:
                await self.identity_repo.create(
                    user_id=user.id,
                    provider=PROVIDER_PHONE,
                    provider_user_id=phone_e164,
                    auto_commit=False,
                )
            await self.session.commit()
            return
        if current is None:
            return
        if not await self._user_has_other_login_identity(
            user.id,
            exclude_provider=PROVIDER_PHONE,
        ):
            raise ValueError("Нельзя удалить последний способ входа")
        await self.session.delete(current)
        await self.session.commit()

    # Меняет или снимает telegram-identity из админки.
    async def admin_set_telegram_for_user(
        self,
        user: User,
        telegram_id: int | None,
        telegram_username: str | None = None,
    ) -> User:
        current = await self.identity_repo.get_telegram_for_user(user.id)
        normalized_username = (
            telegram_username.strip().lstrip("@") if telegram_username else None
        )
        if telegram_id is not None:
            provider_user_id = str(telegram_id)
            conflict = await self.identity_repo.get_by_provider(
                PROVIDER_TELEGRAM,
                provider_user_id,
            )
            if conflict is not None and conflict.user_id != user.id:
                raise ValueError("Telegram ID уже привязан к другому аккаунту")
            meta: dict[str, object] = {}
            if current is not None and isinstance(current.meta_json, dict):
                meta = dict(current.meta_json)
            if normalized_username is not None:
                meta["username"] = normalized_username
            elif "username" not in meta:
                meta["username"] = None
            if (
                current is not None
                and current.provider_user_id == provider_user_id
                and current.meta_json == meta
            ):
                return user
            if current is not None:
                current.provider_user_id = provider_user_id
                current.meta_json = meta
                self.session.add(current)
            else:
                await self.identity_repo.create(
                    user_id=user.id,
                    provider=PROVIDER_TELEGRAM,
                    provider_user_id=provider_user_id,
                    meta_json=meta,
                    auto_commit=False,
                )
            role = resolve_role_for_telegram_id(telegram_id)
            if user.role != role:
                user.role = role
                self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            return user
        if current is None:
            return user
        if not await self._user_has_other_login_identity(
            user.id,
            exclude_provider=PROVIDER_TELEGRAM,
        ):
            raise ValueError("Нельзя удалить последний способ входа")
        await self.session.delete(current)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    # Ищет email-identity пользователя.
    async def _find_email_identity_for_user(
        self,
        user_id: int,
    ) -> AuthIdentity | None:
        for identity in await self.identity_repo.list_for_user(user_id):
            if identity.provider == PROVIDER_EMAIL:
                return identity
        return None

    # True, если есть другой способ входа (телефон/Telegram), кроме exclude_provider.
    async def _user_has_other_login_identity(
        self,
        user_id: int,
        *,
        exclude_provider: str,
    ) -> bool:
        identities = await self.identity_repo.list_for_user(user_id)
        return any(
            identity.provider in _LOGIN_PROVIDERS
            and identity.provider != exclude_provider
            for identity in identities
        )

    # Сливает donor (только email или только TG) в текущий аккаунт.
    async def _try_merge_complementary_accounts(
        self,
        donor: User,
        survivor: User,
        donor_provider: str,
    ) -> bool:
        if donor.id == survivor.id:
            return True
        donor_identities = await self.identity_repo.list_for_user(donor.id)
        if len(donor_identities) != 1:
            return False
        if donor_identities[0].provider != donor_provider:
            return False
        for identity in await self.identity_repo.list_for_user(survivor.id):
            if identity.provider == donor_provider:
                return False
        await self._merge_donor_into_survivor(donor, survivor)
        return True

    # Переносит identity, корзину, заказы и профиль доставки donor → survivor.
    async def _merge_donor_into_survivor(self, donor: User, survivor: User) -> None:
        from src.services.cart_service import CartService

        donor_identities = await self.identity_repo.list_for_user(donor.id)
        for identity in donor_identities:
            identity.user_id = survivor.id
            self.session.add(identity)

        await CartService(self.session).merge_user_cart(donor.id, survivor.id)

        await self.session.execute(
            update(Order).where(Order.user_id == donor.id).values(user_id=survivor.id)
        )

        donor_profile = await self.session.scalar(
            select(UserDeliveryProfile).where(UserDeliveryProfile.user_id == donor.id)
        )
        survivor_profile = await self.session.scalar(
            select(UserDeliveryProfile).where(
                UserDeliveryProfile.user_id == survivor.id
            )
        )
        if donor_profile is not None and survivor_profile is None:
            donor_profile.user_id = survivor.id
            self.session.add(donor_profile)
        elif donor_profile is not None and survivor_profile is not None:
            await self.session.delete(donor_profile)

        await self._merge_referral_assets(donor, survivor)

        donor_email = donor.email
        donor_name = donor.name
        donor_avatar = donor.avatar
        donor_referrer_id = donor.referrer_id
        donor_referral_code = donor.referral_code

        if donor_email:
            donor.email = None
            self.session.add(donor)
            await self.session.flush()

        if not survivor.email and donor_email:
            survivor.email = donor_email

        if not survivor.referral_code and donor_referral_code:
            donor.referral_code = pending_referral_code()
            self.session.add(donor)
            await self.session.flush()
            survivor.referral_code = donor_referral_code

        if not survivor.name and donor_name:
            survivor.name = donor_name
        if not survivor.avatar and donor_avatar:
            survivor.avatar = donor_avatar
        if survivor.referrer_id is None and donor_referrer_id is not None:
            survivor.referrer_id = donor_referrer_id
        self.session.add(survivor)

        await self.session.delete(donor)
        await self.session.commit()
        await self.session.refresh(survivor)

    # Переносит реферальные начисления, приглашённых и код donor → survivor.
    async def _merge_referral_assets(self, donor: User, survivor: User) -> None:
        referral_repo = ReferralRepository(self.session)
        invited = await referral_repo.count_invited_users(donor.id)
        earnings = await referral_repo.count_earnings(donor.id)
        donor_is_referrer = (
            user_has_referral_program(donor.role) or invited > 0 or earnings > 0
        )

        if earnings > 0:
            await self.session.execute(
                update(ReferralEarning)
                .where(ReferralEarning.referrer_id == donor.id)
                .values(referrer_id=survivor.id)
            )
        await self.session.execute(
            update(ReferralEarning)
            .where(ReferralEarning.referred_user_id == donor.id)
            .values(referred_user_id=survivor.id)
        )
        await self.session.execute(
            update(User)
            .where(User.referrer_id == donor.id)
            .values(referrer_id=survivor.id)
        )

        if survivor.referrer_id is None and donor.referrer_id is not None:
            survivor.referrer_id = donor.referrer_id

        if donor_is_referrer:
            donor_code = donor.referral_code
            if (
                donor_code
                and survivor.referral_code
                and donor_code != survivor.referral_code
            ):
                donor.referral_code = pending_referral_code()
                self.session.add(donor)
                await self.session.flush()
                survivor.referral_code = donor_code
            elif donor_code and not survivor.referral_code:
                survivor.referral_code = donor_code

            donor_alias = donor.referral_alias
            if donor_alias:
                if survivor.referral_alias:
                    donor.referral_alias = None
                    self.session.add(donor)
                    await self.session.flush()
                else:
                    donor.referral_alias = None
                    self.session.add(donor)
                    await self.session.flush()
                    survivor.referral_alias = donor_alias

        self.session.add(survivor)

    # Обновляет users и telegram-identity.
    async def _sync_telegram_user(
        self,
        user: User,
        identity: AuthIdentity,
        name: str | None,
        photo_url: str | None,
        role: str,
        meta: dict,
    ) -> User:
        user.name = name or user.name
        if photo_url and photo_url.strip():
            user.avatar = photo_url.strip()
        if user.role != role:
            user.role = role
        identity.meta_json = meta
        self.session.add(user)
        self.session.add(identity)
        await self.session.commit()
        await self.session.refresh(user)
        return user
