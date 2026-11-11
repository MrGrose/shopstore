import base64
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from redis.exceptions import RedisError

from src.api.routers.payment_sbp import verify_sbp_callback_signature
from src.integrations.sbp import SBPClient
from src.integrations.sbp.redis_lock import (
    REDIS_LOCK_BYPASS,
    release_redis_lock,
    try_acquire_redis_lock,
)
from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.payment_service import INIT_STATE_CREATING, PaymentService
from src.utils.datetime_fmt import utc_now_naive

# Обезличенные контракты SBP (внешний envelope → order внутри get_order()).
GET_ORDER_CONTRACT = {
    "success": True,
    "order": {
        "id": "prov-contract-1",
        "status": "QRCDATA_CREATED",
        "merchantOrderId": "shopstore-99/1",
        "paymentAmount": 10000,
        "paymentCurrency": "RUB",
        "qrcId": "qrc-abc",
        "payload": "https://qr.example.invalid/pay",
    },
}

# GET /order/{id}: payload только в qrcData (типичный resume после POST qrcData).
GET_ORDER_QRCDATA_NESTED = {
    "success": True,
    "order": {
        "id": "prov-nested-1",
        "status": "QRCDATA_CREATED",
        "merchantOrderId": "shopstore-42/1",
        "paymentAmount": 10000,
        "paymentCurrency": "RUB",
        "qrcData": {
            "qrcId": "qrc-nested",
            "payload": "https://qr.example.invalid/nested",
        },
    },
}

# GET /order/{id}: без payload (статус есть, QR ещё жив — нужен POST qrcData fallback).
GET_ORDER_WITHOUT_PAYLOAD = {
    "success": True,
    "order": {
        "id": "prov-empty-1",
        "status": "QRCDATA_CREATED",
        "merchantOrderId": "shopstore-7/1",
        "paymentAmount": 10000,
        "paymentCurrency": "RUB",
        "qrcId": "qrc-empty",
    },
}

# POST /order/qrcData/{id}: order с payload на верхнем уровне.
POST_QRCDATA_ORDER_CONTRACT = {
    "success": True,
    "order": {
        "id": "prov-qr-1",
        "status": "QRCDATA_CREATED",
        "merchantOrderId": "shopstore-7/1",
        "qrcId": "qrc-post",
        "payload": "https://qr.example.invalid/post",
    },
}


@pytest.mark.asyncio
async def test_get_order_contract_shape() -> None:
    client = SBPClient(login="u", password="p")
    client._get_access_token = AsyncMock(  # type: ignore[method-assign]
        return_value="jwt",
    )

    async def fake_api_request(
        method, path, json_body=None, x_req_id=None, retry_auth=True
    ):
        assert method == "GET"
        assert path == "/order/prov-contract-1"
        return GET_ORDER_CONTRACT

    client._api_request = fake_api_request  # type: ignore[method-assign]
    order = await client.get_order("prov-contract-1", "req-1")
    assert order["status"] == "QRCDATA_CREATED"
    assert order["payload"] == "https://qr.example.invalid/pay"
    assert order["merchantOrderId"] == "shopstore-99/1"


def _order(**kwargs):
    order = MagicMock()
    order.id = kwargs.get("id", 1)
    order.user_id = kwargs.get("user_id", 10)
    order.status = kwargs.get("status", OrderStatus.PROCESSING)
    order.total_amount = kwargs.get("total_amount", Decimal("100.00"))
    order.availability_confirmation_status = kwargs.get(
        "availability_confirmation_status",
        AvailabilityConfirmationStatus.NOT_REQUIRED,
    )
    order.payment_paid_at = kwargs.get("payment_paid_at", None)
    order.payment_due_at = kwargs.get("payment_due_at", None)
    return order


@pytest.fixture
def payment_service() -> PaymentService:
    session = AsyncMock()
    sbp = AsyncMock()
    service = PaymentService(session, sbp_client=sbp)
    service.order_crud = AsyncMock()
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    return service


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
async def test_init_payment_pending_availability_blocked(
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    order = _order(
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    with pytest.raises(ValueError, match="Оплата недоступна"):
        await payment_service.init_payment(1, 10)


@pytest.mark.asyncio
async def test_handle_sbp_callback_unknown_provider_id_no_changes(
    payment_service: PaymentService,
) -> None:
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=None
    )
    payment_service.order_crud.get_payment_attempt_by_merchant_order_id = AsyncMock(
        return_value=None
    )
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    payment_service.session.commit = AsyncMock()

    await payment_service.handle_sbp_callback({"order": {"id": "provider-unknown"}})

    payment_service.session.commit.assert_not_called()


def test_callback_signature_valid_and_invalid() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    body = b'{"order":{"id":"1"}}'
    signature = base64.b64encode(
        private_key.sign(body, padding.PKCS1v15(), hashes.SHA1())
    ).decode()
    assert verify_sbp_callback_signature(body, signature, public_pem)
    assert not verify_sbp_callback_signature(body, "bad", public_pem)


@pytest.mark.asyncio
async def test_init_window_expired_raises_reconciliation(
    payment_service: PaymentService,
) -> None:
    attempt = MagicMock()
    attempt.init_state = INIT_STATE_CREATING
    attempt.created_at = utc_now_naive() - timedelta(hours=2)
    with pytest.raises(Exception, match="зависла"):
        payment_service._ensure_init_window_for_attempt(attempt)


@pytest.mark.asyncio
@patch("src.integrations.sbp.redis_lock.async_redis")
async def test_redis_lock_unavailable_returns_bypass(mock_async_redis) -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=RedisError("down"))
    mock_async_redis.return_value = redis

    token = await try_acquire_redis_lock("sbp:test", 30)
    assert token == REDIS_LOCK_BYPASS
    await release_redis_lock("sbp:test", REDIS_LOCK_BYPASS)
