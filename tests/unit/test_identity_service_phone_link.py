from unittest.mock import AsyncMock

import pytest

from src.models.auth_identity import AuthIdentity
from src.models.user import User
from src.repositories.auth_identity_repo import PROVIDER_PHONE
from src.services.identity_service import IdentityService

PHONE = "+79991234567"
CONFLICT = "Телефон уже привязан к другому аккаунту"


@pytest.fixture
def identity_service() -> IdentityService:
    session = AsyncMock()
    service = IdentityService(session)
    service.identity_repo = AsyncMock()
    service.user_crud = AsyncMock()
    service.ensure_phone_identity_for_user = AsyncMock()
    service._try_merge_complementary_accounts = AsyncMock(return_value=True)
    return service


def _phone_identity(user_id: int, phone: str = PHONE) -> AuthIdentity:
    return AuthIdentity(
        id=1,
        user_id=user_id,
        provider=PROVIDER_PHONE,
        provider_user_id=phone,
        email=None,
        meta_json=None,
    )


def _survivor(user_id: int = 10) -> User:
    return User(id=user_id, email=None, name="Survivor")


async def test_link_free_phone(identity_service: IdentityService) -> None:
    survivor = _survivor()
    identity_service.identity_repo.get_phone_by_number.return_value = None
    identity_service.identity_repo.get_phone_for_user.return_value = None

    result = await identity_service.link_phone_to_user(survivor, PHONE)

    assert result is survivor
    identity_service.ensure_phone_identity_for_user.assert_awaited_once_with(
        survivor,
        PHONE,
    )


async def test_link_same_phone_idempotent(identity_service: IdentityService) -> None:
    survivor = _survivor()
    identity_service.identity_repo.get_phone_by_number.return_value = _phone_identity(
        survivor.id
    )

    result = await identity_service.link_phone_to_user(survivor, PHONE)

    assert result is survivor
    identity_service.ensure_phone_identity_for_user.assert_not_awaited()
    identity_service._try_merge_complementary_accounts.assert_not_awaited()


async def test_link_merge_phone_only_donor(identity_service: IdentityService) -> None:
    survivor = _survivor(10)
    donor = User(id=20, email=None, name="Donor")
    identity_service.identity_repo.get_phone_by_number.return_value = _phone_identity(
        20
    )
    identity_service.identity_repo.get_phone_for_user.return_value = None
    identity_service.user_crud.get_by_id.return_value = donor
    refreshed = User(id=10, email=None, name="Survivor")
    identity_service.user_crud.get_by_id.side_effect = [donor, refreshed]

    result = await identity_service.link_phone_to_user(survivor, PHONE)

    assert result is refreshed
    identity_service._try_merge_complementary_accounts.assert_awaited_once_with(
        donor=donor,
        survivor=survivor,
        donor_provider=PROVIDER_PHONE,
    )


async def test_link_409_when_donor_multi_identity(
    identity_service: IdentityService,
) -> None:
    survivor = _survivor()
    donor = User(id=20, email=None, name="Donor")
    identity_service.identity_repo.get_phone_by_number.return_value = _phone_identity(
        20
    )
    identity_service.identity_repo.get_phone_for_user.return_value = None
    identity_service.user_crud.get_by_id.return_value = donor
    identity_service._try_merge_complementary_accounts.return_value = False

    with pytest.raises(ValueError, match=CONFLICT):
        await identity_service.link_phone_to_user(survivor, PHONE)


async def test_link_409_when_survivor_already_has_other_phone(
    identity_service: IdentityService,
) -> None:
    survivor = _survivor()
    identity_service.identity_repo.get_phone_by_number.return_value = None
    identity_service.identity_repo.get_phone_for_user.return_value = _phone_identity(
        survivor.id,
        "+79997654321",
    )

    with pytest.raises(ValueError, match=CONFLICT):
        await identity_service.link_phone_to_user(survivor, PHONE)


async def test_link_409_race_before_merge(identity_service: IdentityService) -> None:
    survivor = _survivor()
    identity_service.identity_repo.get_phone_by_number.return_value = _phone_identity(
        20
    )
    identity_service.identity_repo.get_phone_for_user.return_value = _phone_identity(
        survivor.id,
        "+79997654321",
    )

    with pytest.raises(ValueError, match=CONFLICT):
        await identity_service.link_phone_to_user(survivor, PHONE)

    identity_service._try_merge_complementary_accounts.assert_not_awaited()


async def test_link_merge_into_email_telegram_survivor(
    identity_service: IdentityService,
) -> None:
    survivor = _survivor(10)
    donor = User(id=20, email=None, name="Donor")
    identity_service.identity_repo.get_phone_by_number.return_value = _phone_identity(
        20
    )
    identity_service.identity_repo.get_phone_for_user.return_value = None
    identity_service.user_crud.get_by_id.return_value = donor
    identity_service._try_merge_complementary_accounts.return_value = True
    refreshed = User(id=10, email="a@b.c", name="Survivor")
    identity_service.user_crud.get_by_id.side_effect = [donor, refreshed]

    result = await identity_service.link_phone_to_user(survivor, PHONE)

    assert result is refreshed
    identity_service._try_merge_complementary_accounts.assert_awaited_once()
