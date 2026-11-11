from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.identity_service import IdentityService
from src.services.orders.order_service import OrderService, TelegramRequiredError


@pytest.mark.asyncio
async def test_create_order_requires_selected_notification_channel() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(id=7))
    service = OrderService(session)
    service.order_crud.get_by_idempotency_key = AsyncMock(return_value=None)
    service.cart_crud.get_user_cart = AsyncMock(return_value=[MagicMock()])

    identity_svc = IdentityService(session)
    identity_svc.get_telegram_id_for_user = AsyncMock(return_value=None)
    service.session.get = AsyncMock(return_value=SimpleNamespace(id=7))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.services.orders.order_service.IdentityService",
            lambda _session: identity_svc,
        )
        with pytest.raises(ValueError, match="Выберите канал уведомлений"):
            await service.create_order(
                user_id=7,
                idempotency_key=None,
                delivery_payload={
                    "last_name": "Ivanov",
                    "first_name": "Ivan",
                    "street": "Test",
                    "house": "1",
                    "city": "Moscow",
                    "postal_code": "101000",
                    "phone": "+79991234567",
                },
            )

    service.cart_crud.get_user_cart.assert_not_called()


@pytest.mark.asyncio
async def test_create_order_telegram_channel_without_identity_raises() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(id=7))
    service = OrderService(session)
    service.order_crud.get_by_idempotency_key = AsyncMock(return_value=None)

    identity_svc = IdentityService(session)
    identity_svc.get_telegram_id_for_user = AsyncMock(return_value=None)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.services.orders.order_service.IdentityService",
            lambda _session: identity_svc,
        )
        with pytest.raises(TelegramRequiredError):
            await service.create_order(
                user_id=7,
                idempotency_key=None,
                delivery_payload={
                    "last_name": "Ivanov",
                    "first_name": "Ivan",
                    "street": "Test",
                    "house": "1",
                    "city": "Moscow",
                    "postal_code": "101000",
                    "phone": "+79991234567",
                },
                notification_channels=["telegram"],
            )
