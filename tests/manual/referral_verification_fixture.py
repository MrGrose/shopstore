import argparse
import asyncio
import os
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.core.config import settings
from src.core.referral import build_referral_link_for_user, is_legacy_ps_referral_code
from src.core.user_roles import UserRole
from src.models.auth_identity import AuthIdentity
from src.models.user import User
from src.repositories.session import async_session_maker
from src.services.referral_service import ReferralService
from src.services.user_service import UserService

# Manual seed/check для referral migration (Buyer A/B/C/Inactive).
#
# Seed (только APP_ENV=dev):
#   ALLOW_REFERRAL_VERIFICATION_SEED=1 REFERRAL_VERIFICATION_ACTION=seed \
#     pytest -s tests/manual/referral_verification_fixture.py
# Seed + сброс referrer у B/C:
#   ALLOW_REFERRAL_VERIFICATION_SEED=1 REFERRAL_VERIFICATION_ACTION=seed \
#     RESET_ATTRIBUTION=1 \
#     pytest -s tests/manual/referral_verification_fixture.py
# Check:
#   REFERRAL_VERIFICATION_ACTION=check pytest -s \
#     tests/manual/referral_verification_fixture.py

FIXTURE_TELEGRAM_IDS = {
    "buyer_a": 920_001_001,
    "buyer_b": 920_001_002,
    "buyer_c": 920_001_003,
    "buyer_inactive": 920_001_004,
}


@dataclass(frozen=True)
class FixtureSpec:
    key: str
    label: str
    telegram_id: int
    telegram_username: str
    name: str
    is_active: bool = True
    alias: str | None = None
    reset_attribution: bool = False
    individual_percent: Decimal | None = None


FIXTURES: tuple[FixtureSpec, ...] = (
    FixtureSpec(
        key="buyer_a",
        label="Buyer A (реферер)",
        telegram_id=FIXTURE_TELEGRAM_IDS["buyer_a"],
        telegram_username="ref_verify_a",
        name="Referral Verify A",
        alias="ref-verify-a",
    ),
    FixtureSpec(
        key="buyer_b",
        label="Buyer B (новый реферал)",
        telegram_id=FIXTURE_TELEGRAM_IDS["buyer_b"],
        telegram_username="ref_verify_b",
        name="Referral Verify B",
        reset_attribution=True,
    ),
    FixtureSpec(
        key="buyer_c",
        label="Buyer C (Last Touch / админ)",
        telegram_id=FIXTURE_TELEGRAM_IDS["buyer_c"],
        telegram_username="ref_verify_c",
        name="Referral Verify C",
        reset_attribution=True,
    ),
    FixtureSpec(
        key="buyer_inactive",
        label="Buyer Inactive",
        telegram_id=FIXTURE_TELEGRAM_IDS["buyer_inactive"],
        telegram_username="ref_verify_inactive",
        name="Referral Verify Inactive",
        is_active=False,
    ),
)


def require_dev_environment() -> None:
    if not settings.is_dev:
        raise SystemExit(
            "referral_verification_fixture seed разрешён только при APP_ENV=dev "
            f"(сейчас APP_ENV={settings.APP_ENV!r})"
        )


# Проверяет guard-условия manual seed/check.
def resolve_verification_action() -> str:
    action = os.environ.get("REFERRAL_VERIFICATION_ACTION", "").strip().lower()
    if not action:
        pytest.skip("Задайте REFERRAL_VERIFICATION_ACTION=seed или check")
    if action not in {"seed", "check"}:
        pytest.fail(f"Неизвестное REFERRAL_VERIFICATION_ACTION={action!r}")
    if action == "seed":
        if not settings.is_dev:
            pytest.fail("referral verification seed запрещён вне dev (APP_ENV != dev)")
        if os.environ.get("ALLOW_REFERRAL_VERIFICATION_SEED") != "1":
            pytest.skip("Задайте ALLOW_REFERRAL_VERIFICATION_SEED=1")
    return action


# Создаёт или обновляет фиксированного BUYER для сценариев проверки.
async def upsert_fixture(session, spec: FixtureSpec, *, reset: bool) -> User:
    user_svc = UserService(session)
    ref_svc = ReferralService(session)

    user = await user_svc.upsert_telegram_user(
        telegram_id=spec.telegram_id,
        telegram_username=spec.telegram_username,
        name=spec.name,
    )
    user.role = UserRole.BUYER.value
    user.is_active = spec.is_active
    if reset and spec.reset_attribution:
        user.referrer_id = None
        user.referral_attribution_locked = False
    if spec.individual_percent is not None:
        user.referral_commission_percent = spec.individual_percent
    session.add(user)
    await session.flush()

    code = (user.referral_code or "").strip()
    if not code or is_legacy_ps_referral_code(code) or code.startswith("T"):
        user.referral_code = None
        session.add(user)
        await session.flush()

    user = await ref_svc.ensure_referral_code(user)
    if spec.alias:
        user = await ref_svc.set_admin_referral_alias(user, spec.alias)
    await session.commit()
    await session.refresh(user)
    return user


def admin_customer_url(user_id: int) -> str:
    base = (settings.PUBLIC_SITE_URL or "http://localhost:8001").strip().rstrip("/")
    return f"{base}/internal/admin/customers?id={user_id}"


def print_user_block(user: User, spec: FixtureSpec) -> None:
    link = build_referral_link_for_user(user.referral_alias, user.referral_code or "")
    short_link = (
        f"/ref/{user.referral_alias}"
        if user.referral_alias
        else f"/?ref={user.referral_code}"
    )
    print(f"## {spec.label}")
    print(f"- user_id: {user.id}")
    print(f"- telegram: @{spec.telegram_username} (id {spec.telegram_id})")
    print(f"- is_active: {user.is_active}")
    print(f"- referrer_id: {user.referrer_id}")
    print(f"- referral_attribution_locked: {user.referral_attribution_locked}")
    print(f"- referral_code: {user.referral_code}")
    print(f"- referral_alias: {user.referral_alias or '—'}")
    print(f"- referral_link: {link}")
    print(f"- short_path: {short_link}")
    if user.referral_commission_percent is not None:
        print(f"- referral_commission_percent: {user.referral_commission_percent}")
    print(f"- admin: {admin_customer_url(user.id)}")
    print()


async def prepare_fixtures(
    *, reset_attribution: bool
) -> list[tuple[FixtureSpec, User]]:
    async with async_session_maker() as session:
        users: list[tuple[FixtureSpec, User]] = []
        for spec in FIXTURES:
            user = await upsert_fixture(session, spec, reset=reset_attribution)
            users.append((spec, user))
    return users


async def check_fixtures() -> None:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(User, AuthIdentity.provider_user_id)
                .join(AuthIdentity, AuthIdentity.user_id == User.id)
                .where(
                    AuthIdentity.provider == "telegram",
                    AuthIdentity.provider_user_id.in_(
                        str(value) for value in FIXTURE_TELEGRAM_IDS.values()
                    ),
                )
            )
        ).all()
    by_telegram_id = {int(telegram_id): user for user, telegram_id in rows}

    failures: list[str] = []
    for key, telegram_id in FIXTURE_TELEGRAM_IDS.items():
        user = by_telegram_id.get(telegram_id)
        if user is None:
            failures.append(f"{key}: fixture is missing")
            print(f"FAIL {key}: fixture is missing")
            continue
        fixture_failed = False
        if user.role != UserRole.BUYER.value:
            failures.append(f"{key}: role={user.role}")
            fixture_failed = True
        if not user.referral_code or is_legacy_ps_referral_code(user.referral_code):
            failures.append(f"{key}: missing opaque referral_code")
            fixture_failed = True
        if key == "buyer_inactive" and user.is_active:
            failures.append(f"{key}: expected inactive")
            fixture_failed = True
        print(
            f"{'FAIL' if fixture_failed else 'OK'} {key}: id={user.id} "
            f"active={user.is_active} code={user.referral_code}"
        )
    if failures:
        raise RuntimeError("; ".join(failures))


@pytest.mark.asyncio
async def test_referral_verification_fixture() -> None:
    action = resolve_verification_action()
    if action == "seed":
        reset = os.environ.get("RESET_ATTRIBUTION", "").strip() in {
            "1",
            "true",
            "yes",
            "on",
        }
        users = await prepare_fixtures(reset_attribution=reset)
        print("# Referral verification fixtures\n")
        print("Перед сценариями с новой привязкой:")
        print("- используйте отдельный аккаунт или RESET_ATTRIBUTION=1;")
        print("- очистите cookies / откройте инкогнито;")
        print("- после первой привязки пользователь сам реферера не меняет.\n")
        for spec, user in users:
            print_user_block(user, spec)
        return
    try:
        await check_fixtures()
    except RuntimeError as exc:
        pytest.fail(str(exc))


async def _cli_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-attribution",
        action="store_true",
        help="Сбросить referrer_id и lock у Buyer B и C.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Подготовить фикстуры (APP_ENV=dev)")
    sub.add_parser("check", help="Проверить фикстуры")
    args = parser.parse_args()
    if args.command == "seed":
        require_dev_environment()
        users = await prepare_fixtures(reset_attribution=args.reset_attribution)
        for spec, user in users:
            print_user_block(user, spec)
        return
    try:
        await check_fixtures()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    asyncio.run(_cli_main())
