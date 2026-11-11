from unittest.mock import AsyncMock, patch

import pytest

from src.core.config import validate_sbp_startup_settings
from src.services.payment_service import PaymentService


@pytest.fixture
def payment_service() -> PaymentService:
    session = AsyncMock()
    sbp = AsyncMock()
    service = PaymentService(session, sbp_client=sbp)
    service.order_crud = AsyncMock()
    service.order_crud.get_by_id = AsyncMock()
    service.order_crud.get_by_id_for_update = AsyncMock()
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.create_payment_attempt = AsyncMock()
    return service


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
async def test_init_payment_disabled_raises(
    mock_settings, payment_service: PaymentService
) -> None:
    mock_settings.SBP_ENABLED = False

    with pytest.raises(
        ValueError, match="Платёжная интеграция на этом окружении отключена"
    ):
        await payment_service.init_payment(1, 10)


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
)
async def test_init_payment_disabled_no_side_effects(
    mock_lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = False

    with pytest.raises(ValueError):
        await payment_service.init_payment(1, 10)

    payment_service.order_crud.get_by_id.assert_not_called()
    mock_lock.assert_not_called()
    payment_service.order_crud.create_payment_attempt.assert_not_called()
    payment_service.sbp.create_order.assert_not_called()
    payment_service.sbp.get_order.assert_not_called()


def _patch_sbp_settings(
    *,
    enabled: bool,
    app_env: str = "prod",
    login: str = "",
    password: str = "",
    callback_url: str = "",
    webhook_key: str = "",
) -> patch:
    return patch.multiple(
        "src.core.config.settings",
        SBP_ENABLED=enabled,
        APP_ENV=app_env,
        SBP_LOGIN=login,
        SBP_PASSWORD=password,
        SBP_CALLBACK_URL=callback_url,
        SBP_WEBHOOK_PUBLIC_KEY=webhook_key,
    )


def test_validate_sbp_startup_missing_credentials() -> None:
    with _patch_sbp_settings(enabled=True):
        with pytest.raises(RuntimeError, match="SBP_LOGIN"):
            validate_sbp_startup_settings()


def test_validate_sbp_startup_fails_in_dev() -> None:
    with _patch_sbp_settings(enabled=True, app_env="dev"):
        with pytest.raises(RuntimeError, match="SBP_ENABLED=true"):
            validate_sbp_startup_settings()


def test_validate_sbp_startup_skips_when_disabled() -> None:
    with _patch_sbp_settings(enabled=False):
        validate_sbp_startup_settings()


def test_validate_sbp_startup_ok_when_filled() -> None:
    with _patch_sbp_settings(
        enabled=True,
        login="user",
        password="secret",
        callback_url="https://example.com/payments/sbp/callback",
        webhook_key="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----",
    ):
        validate_sbp_startup_settings()
