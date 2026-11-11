from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import OrderStatus
from src.services.admin_notification_service import AdminNotificationService
from src.services.customer_notification_service import CustomerNotificationService
from src.services.payment_service import (
    PAYMENT_ACCEPTED_STATUS,
    DuplicatePaymentNotify,
    PaymentService,
    merchant_order_id_for,
    new_provider_get_x_req_id,
    parse_local_order_id_from_merchant,
    x_req_id_for_order,
    x_req_id_for_qr,
)
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import (
    is_provider_status_transition_allowed,
    normalize_order_payment_from_attempt,
)
from tests.unit.test_payment_service import (
    GET_ORDER_CONTRACT,
    GET_ORDER_QRCDATA_NESTED,
    GET_ORDER_WITHOUT_PAYLOAD,
    POST_QRCDATA_ORDER_CONTRACT,
)


def _order(**kwargs):
    order = MagicMock()
    order.id = kwargs.get("id", 1)
    order.user_id = kwargs.get("user_id", 10)
    order.status = kwargs.get("status", OrderStatus.PROCESSING)
    order.total_amount = kwargs.get("total_amount", Decimal("100.00"))
    order.availability_confirmation_status = kwargs.get(
        "availability_confirmation_status", "not_required"
    )
    order.payment_paid_at = kwargs.get("payment_paid_at", None)
    order.payment_due_at = kwargs.get("payment_due_at", None)
    order.payment_provider = kwargs.get("payment_provider", "sbp")
    order.payment_order_id = kwargs.get("payment_order_id", None)
    order.payment_status = kwargs.get("payment_status", None)
    order.payment_meta_json = kwargs.get("payment_meta_json", {})
    order.cancellation_reason = kwargs.get("cancellation_reason", None)
    order.promo_code_applied = None
    order.last_name = None
    order.first_name = None
    order.street = None
    order.house = None
    order.apartment = None
    order.city = None
    order.postal_code = None
    order.phone = None
    order.notification_channels = ["telegram"]
    order.notification_email = None
    order.supplier_order_id = None
    order.supplier_tracking_id = None
    order.failed_from_status = None
    order.created_at = kwargs.get("created_at", None)
    order.updated_at = kwargs.get("updated_at", None)
    return order


def _attempt(**kwargs):
    attempt = MagicMock()
    attempt.id = kwargs.get("id", 1)
    attempt.order_id = kwargs.get("order_id", 1)
    attempt.attempt_number = kwargs.get("attempt_number", 1)
    attempt.provider = "sbp"
    attempt.merchant_order_id = kwargs.get(
        "merchant_order_id", merchant_order_id_for(1, 1)
    )
    attempt.payment_amount_minor = kwargs.get("payment_amount_minor", 10000)
    attempt.payment_currency = "RUB"
    attempt.init_state = kwargs.get("init_state", "ready")
    attempt.provider_order_id = kwargs.get("provider_order_id", "prov-1")
    attempt.provider_status = kwargs.get("provider_status", "QRCDATA_CREATED")
    attempt.x_req_id_order = kwargs.get("x_req_id_order", x_req_id_for_order(1, 1))
    attempt.x_req_id_qr = kwargs.get("x_req_id_qr", x_req_id_for_qr(1, 1))
    now = utc_now_naive()
    attempt.qr_created_at = kwargs.get("qr_created_at", now)
    attempt.qr_expires_at = kwargs.get("qr_expires_at", now + timedelta(minutes=15))
    attempt.paid_at = kwargs.get("paid_at", None)
    attempt.last_callback_at = kwargs.get("last_callback_at", None)
    attempt.created_at = kwargs.get("created_at", now)
    return attempt


@pytest.fixture
def payment_service() -> PaymentService:
    session = AsyncMock()
    session.add = MagicMock()
    sbp = AsyncMock()
    service = PaymentService(session, sbp_client=sbp)
    service.order_crud = AsyncMock()
    service.order_crud.count_payment_attempts = AsyncMock(return_value=0)
    service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    return service


def _mock_locked_attempt(payment_service: PaymentService, attempt) -> None:
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=attempt
    )


def test_merchant_order_id_formats() -> None:
    assert merchant_order_id_for(42, 1) == "shopstore-42/1"
    assert merchant_order_id_for(42, 2) == "shopstore-42/2"


def test_parse_local_order_id_from_merchant_dual_format() -> None:
    assert parse_local_order_id_from_merchant("shopstore-7") == 7
    assert parse_local_order_id_from_merchant("shopstore-7/1") == 7
    assert parse_local_order_id_from_merchant("shopstore-7/2") == 7
    assert parse_local_order_id_from_merchant("other-7") is None


def test_x_req_ids_per_attempt() -> None:
    assert x_req_id_for_order(5, 2) == "shopstore-order-5-2"
    assert x_req_id_for_qr(5, 2) == "shopstore-qrc-5-2"


@pytest.mark.asyncio
async def test_apply_provider_status_creates_event_once(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt()
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        side_effect=[1, None]
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        side_effect=[1, None]
    )
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service._apply_provider_status_to_attempt(
        attempt.id, PAYMENT_ACCEPTED_STATUS, None
    )
    await payment_service._apply_provider_status_to_attempt(
        attempt.id, PAYMENT_ACCEPTED_STATUS, None
    )

    payment_service.order_crud.create_order_event.assert_called_once()


@pytest.mark.asyncio
async def test_apply_provider_status_ignores_stale_created_after_declined(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(provider_status="DECLINED")
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service._apply_provider_status_to_attempt(
        attempt.id, "QRCDATA_CREATED", None
    )

    assert attempt.provider_status == "DECLINED"
    payment_service.order_crud.sync_order_payment_aggregate.assert_not_called()


@pytest.mark.asyncio
async def test_apply_provider_status_ignores_stale_declined_after_paid(
    payment_service: PaymentService,
) -> None:
    order = _order(
        payment_paid_at=utc_now_naive(),
        payment_status=PAYMENT_ACCEPTED_STATUS,
    )
    attempt = _attempt(
        provider_status=PAYMENT_ACCEPTED_STATUS,
        paid_at=utc_now_naive(),
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service._apply_provider_status_to_attempt(
        attempt.id, "DECLINED", None
    )

    assert attempt.provider_status == PAYMENT_ACCEPTED_STATUS
    payment_service.order_crud.sync_order_payment_aggregate.assert_not_called()


@pytest.mark.asyncio
async def test_apply_provider_status_updates_declined_when_order_paid(
    payment_service: PaymentService,
) -> None:
    order = _order(
        payment_paid_at=utc_now_naive(),
        payment_status=PAYMENT_ACCEPTED_STATUS,
    )
    attempt = _attempt(id=2, attempt_number=2, provider_status="IN_PROCESS")
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service._apply_provider_status_to_attempt(
        attempt.id, "DECLINED", None
    )

    assert attempt.provider_status == "DECLINED"
    payment_service.order_crud.sync_order_payment_aggregate.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
async def test_refresh_payment_attempt_admin_declined_to_accepted_only_target(
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    order = _order(id=7)
    declined = _attempt(
        id=1,
        order_id=7,
        attempt_number=1,
        provider_order_id="prov-declined-1",
        provider_status="DECLINED",
    )
    other = _attempt(
        id=2,
        order_id=7,
        attempt_number=2,
        provider_order_id="prov-active-2",
        provider_status="QRCDATA_CREATED",
    )
    attempts = {1: declined, 2: other}

    async def get_attempt(attempt_id: int):
        return attempts.get(attempt_id)

    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        side_effect=get_attempt
    )
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        side_effect=get_attempt
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=other
    )
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=declined.id
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        return_value=order.id
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()
    payment_service.session.flush = AsyncMock()
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    async def get_order_side_effect(provider_order_id: str, x_req_id=None):
        assert provider_order_id == declined.provider_order_id
        return {"id": provider_order_id, "status": PAYMENT_ACCEPTED_STATUS}

    payment_service.sbp.get_order = AsyncMock(side_effect=get_order_side_effect)

    other_status_before = other.provider_status
    result = await payment_service.refresh_payment_attempt_admin(declined.id)

    payment_service.sbp.get_order.assert_called_once()
    assert payment_service.sbp.get_order.call_args.args[0] == "prov-declined-1"
    assert declined.provider_status == PAYMENT_ACCEPTED_STATUS
    assert declined.paid_at is not None
    assert other.provider_status == other_status_before
    assert result.id == declined.id
    mark_paid = payment_service.order_crud.mark_payment_attempt_paid_if_unpaid
    mark_paid.assert_called_once_with(
        declined.id,
        paid_at=declined.paid_at,
        provider_status=PAYMENT_ACCEPTED_STATUS,
        last_callback_at=None,
    )
    payment_service.order_crud.create_order_event.assert_called_once()


@pytest.mark.asyncio
async def test_duplicate_accepted_creates_duplicate_event(
    payment_service: PaymentService,
) -> None:
    order = _order(payment_paid_at=utc_now_naive())
    attempt = _attempt(id=2, attempt_number=2)
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=2
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        return_value=None
    )
    payment_service.order_crud.has_paid_payment_attempt_excluding = AsyncMock(
        return_value=True
    )
    payment_service.order_crud.has_order_event_type = AsyncMock(return_value=False)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()

    notify = await payment_service._mark_attempt_accepted(attempt, order, None)

    payment_service.order_crud.create_order_event.assert_called_once()
    assert (
        payment_service.order_crud.create_order_event.call_args.kwargs["event_type"]
        == "payment_duplicate_accepted"
    )
    assert isinstance(notify, DuplicatePaymentNotify)
    assert notify.order_id == order.id
    assert notify.attempt_id == attempt.id


@pytest.mark.asyncio
async def test_schedule_duplicate_notify_sends_admin_payment_duplicate(
    payment_service: PaymentService,
) -> None:
    notify = DuplicatePaymentNotify(order_id=11, attempt_id=4)
    with patch("src.services.payment_service.AdminNotificationService") as admin_cls:
        admin = admin_cls.return_value
        admin.send_payment_duplicate = AsyncMock()

        await payment_service._schedule_payment_notifications(notify)

    admin.send_payment_duplicate.assert_awaited_once_with(11, 4)


@pytest.mark.asyncio
async def test_concurrent_ips_accepted_creates_single_duplicate_event(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt_a = _attempt(id=1, attempt_number=1)
    attempt_b = _attempt(id=2, attempt_number=2)
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        side_effect=[1, 2]
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        side_effect=[1, None]
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()
    payment_service.order_crud.has_paid_payment_attempt_excluding = AsyncMock(
        return_value=True
    )
    payment_service.order_crud.has_order_event_type = AsyncMock(return_value=False)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)

    await payment_service._mark_attempt_accepted(attempt_a, order, None)
    await payment_service._mark_attempt_accepted(attempt_b, order, None)

    duplicate_calls = [
        c
        for c in payment_service.order_crud.create_order_event.call_args_list
        if c.kwargs.get("event_type") == "payment_duplicate_accepted"
    ]
    assert len(duplicate_calls) == 1


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_payment_returns_live_qr_from_provider(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    order = _order()
    attempt = _attempt()
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(
        return_value={"status": "QRCDATA_CREATED", "payload": "https://qr.test/pay"}
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_qr_payload == "https://qr.test/pay"
    payment_service.sbp.create_order.assert_not_called()
    assert payment_service.sbp.get_order.call_count == 2
    get_ids = [call.args[1] for call in payment_service.sbp.get_order.call_args_list]
    assert len(set(get_ids)) == 2
    assert all(req_id.startswith("shopstore-get-") for req_id in get_ids)
    assert payment_service.session.commit.await_count >= 2


@pytest.mark.asyncio
async def test_init_releases_order_lock_before_provider_get(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt()
    commit_calls = 0
    get_order_called = False

    async def commit_side_effect():
        nonlocal commit_calls
        commit_calls += 1

    async def get_order_side_effect(*_args, **_kwargs):
        nonlocal get_order_called
        get_order_called = commit_calls > 0
        return {"status": "QRCDATA_CREATED", "payload": "https://qr.test/pay"}

    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(side_effect=get_order_side_effect)
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock(side_effect=commit_side_effect)

    with (
        patch("src.services.payment_service.settings") as mock_settings,
        patch(
            "src.services.payment_service.try_acquire_redis_lock",
            new_callable=AsyncMock,
            return_value="lock-token",
        ),
        patch(
            "src.services.payment_service.release_redis_lock",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.SBP_ENABLED = True
        mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
        mock_settings.SBP_TEST_MODE = True
        await payment_service.init_payment(1, 10)

    assert get_order_called


@pytest.mark.parametrize(
    ("provider_order", "expected"),
    [
        (GET_ORDER_CONTRACT["order"], "https://qr.example.invalid/pay"),
        (GET_ORDER_QRCDATA_NESTED["order"], "https://qr.example.invalid/nested"),
        (GET_ORDER_WITHOUT_PAYLOAD["order"], None),
        (POST_QRCDATA_ORDER_CONTRACT["order"], "https://qr.example.invalid/post"),
    ],
)
def test_extract_qr_payload_get_order_shapes(
    payment_service: PaymentService, provider_order, expected
) -> None:
    assert payment_service._extract_qr_payload(provider_order) == expected


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_resume_after_5_min_get_returns_qr(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    now = utc_now_naive()
    order = _order()
    attempt = _attempt(
        qr_created_at=now - timedelta(minutes=5),
        qr_expires_at=now + timedelta(minutes=10),
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(
        return_value=GET_ORDER_QRCDATA_NESTED["order"]
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_qr_payload == "https://qr.example.invalid/nested"
    payment_service.sbp.create_qr.assert_not_called()
    payment_service.sbp.create_order.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_fetch_live_qr_falls_back_to_post_same_x_req_id(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    now = utc_now_naive()
    order = _order()
    attempt = _attempt(
        qr_created_at=now - timedelta(minutes=5),
        qr_expires_at=now + timedelta(minutes=10),
        x_req_id_qr="shopstore-qrc-1-1",
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(
        return_value=GET_ORDER_WITHOUT_PAYLOAD["order"]
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value=POST_QRCDATA_ORDER_CONTRACT["order"]
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_qr_payload == "https://qr.example.invalid/post"
    payment_service.sbp.create_qr.assert_called_once_with(
        "prov-1",
        "shopstore-qrc-1-1",
    )
    payment_service.sbp.create_order.assert_not_called()
    payment_service.order_crud.create_payment_attempt.assert_not_called()


@pytest.mark.asyncio
async def test_refetch_qr_does_not_extend_expiry(
    payment_service: PaymentService,
) -> None:
    now = utc_now_naive()
    created_at = now - timedelta(minutes=5)
    expires_at = now + timedelta(minutes=10)
    attempt = _attempt(
        qr_created_at=created_at,
        qr_expires_at=expires_at,
        x_req_id_qr="shopstore-qrc-1-1",
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value=POST_QRCDATA_ORDER_CONTRACT["order"]
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )

    payload = await payment_service._refetch_qr_payload_via_post(attempt)

    assert payload == "https://qr.example.invalid/post"
    assert attempt.qr_created_at == created_at
    assert attempt.qr_expires_at == expires_at


@pytest.mark.asyncio
async def test_refetch_qr_discards_payload_when_attempt_declined(
    payment_service: PaymentService,
) -> None:
    now = utc_now_naive()
    attempt = _attempt(
        qr_created_at=now - timedelta(minutes=5),
        qr_expires_at=now + timedelta(minutes=10),
        x_req_id_qr="shopstore-qrc-1-1",
    )
    declined = _attempt(
        provider_status="DECLINED",
        qr_created_at=attempt.qr_created_at,
        qr_expires_at=attempt.qr_expires_at,
        x_req_id_qr="shopstore-qrc-1-1",
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value={
            **POST_QRCDATA_ORDER_CONTRACT["order"],
            "status": "DECLINED",
        }
    )

    async def apply_status(attempt_id, status, callback_at=None):
        declined.provider_status = status

    payment_service._apply_provider_status_to_attempt = AsyncMock(
        side_effect=apply_status
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=declined
    )

    payload = await payment_service._refetch_qr_payload_via_post(attempt)

    assert payload is None


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_fallback_post_declined_does_not_return_qr_payload(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    now = utc_now_naive()
    order = _order()
    attempt = _attempt(
        qr_created_at=now - timedelta(minutes=5),
        qr_expires_at=now + timedelta(minutes=10),
        x_req_id_qr="shopstore-qrc-1-1",
    )
    declined = _attempt(
        provider_status="DECLINED",
        qr_created_at=attempt.qr_created_at,
        qr_expires_at=attempt.qr_expires_at,
        x_req_id_qr="shopstore-qrc-1-1",
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(
        return_value=GET_ORDER_WITHOUT_PAYLOAD["order"]
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value={
            **POST_QRCDATA_ORDER_CONTRACT["order"],
            "status": "DECLINED",
        }
    )

    async def apply_status(attempt_id, status, callback_at=None):
        declined.provider_status = status

    payment_service._apply_provider_status_to_attempt = AsyncMock(
        side_effect=apply_status
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        side_effect=lambda _id: declined
    )
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_qr_payload is None
    assert result.payment_state == "failed"
    payment_service.sbp.create_qr.assert_called_once()
    payment_service.order_crud.create_payment_attempt.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_after_declined_expired_creates_new_attempt(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    mock_settings.SBP_CALLBACK_URL = "https://cb.test"
    mock_settings.SBP_MIN_PAYMENT_AMOUNT_MINOR = 100
    mock_settings.SBP_MAX_PAYMENT_AMOUNT_MINOR = 10_000_000
    now = utc_now_naive()
    order = _order()
    declined = _attempt(
        provider_status="DECLINED",
        qr_created_at=now - timedelta(minutes=20),
        qr_expires_at=now - timedelta(minutes=5),
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=declined
    )
    payment_service.order_crud.get_next_payment_attempt_number = AsyncMock(
        return_value=2
    )
    payment_service.order_crud.create_payment_attempt = AsyncMock(
        side_effect=lambda **kwargs: _attempt(
            id=2,
            attempt_number=kwargs["attempt_number"],
            merchant_order_id=kwargs["merchant_order_id"],
            x_req_id_order=kwargs["x_req_id_order"],
            x_req_id_qr=kwargs["x_req_id_qr"],
            provider_order_id=None,
            init_state="creating",
            provider_status="CREATED",
            qr_created_at=None,
            qr_expires_at=None,
        )
    )
    ready = _attempt(
        id=2,
        attempt_number=2,
        merchant_order_id=merchant_order_id_for(1, 2),
        x_req_id_order=x_req_id_for_order(1, 2),
        x_req_id_qr=x_req_id_for_qr(1, 2),
        provider_order_id="prov-attempt-2",
        provider_status="QRCDATA_CREATED",
    )
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=ready
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=ready)
    payment_service.sbp.create_order = AsyncMock(
        return_value={"id": "prov-attempt-2", "status": "CREATED"}
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value={"status": "QRCDATA_CREATED", "payload": "https://qr/attempt-2"}
    )
    payment_service.sbp.get_order = AsyncMock(return_value={"status": "DECLINED"})
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    payment_service.order_crud.create_payment_attempt.assert_called_once()
    assert (
        payment_service.order_crud.create_payment_attempt.call_args.kwargs[
            "attempt_number"
        ]
        == 2
    )
    assert result.payment_qr_payload == "https://qr/attempt-2"
    assert payment_service.sbp.create_order.call_args.kwargs["x_req_id"] == (
        x_req_id_for_order(1, 2)
    )
    assert payment_service.sbp.create_qr.call_args.args[1] == x_req_id_for_qr(1, 2)


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_alive_qr_without_payload_raises_without_new_attempt(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    now = utc_now_naive()
    order = _order()
    attempt = _attempt(
        qr_created_at=now - timedelta(minutes=5),
        qr_expires_at=now + timedelta(minutes=10),
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.sbp.get_order = AsyncMock(
        return_value=GET_ORDER_WITHOUT_PAYLOAD["order"]
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value=GET_ORDER_WITHOUT_PAYLOAD["order"]
    )
    _mock_locked_attempt(payment_service, attempt)
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()

    with pytest.raises(ValueError, match="Не удалось получить QR-код"):
        await payment_service.init_payment(1, 10)

    payment_service.order_crud.create_payment_attempt.assert_not_called()
    payment_service.sbp.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_callback_binds_provider_order_before_http_response(
    payment_service: PaymentService,
) -> None:
    attempt = _attempt(
        provider_order_id=None,
        init_state="creating",
        provider_status="CREATED",
    )
    order = _order()
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=None
    )
    payment_service.order_crud.get_payment_attempt_by_merchant_order_id = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.try_bind_attempt_provider_order_id = AsyncMock(
        return_value=True
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    _mock_locked_attempt(payment_service, attempt)
    payment_service.session.commit = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service.handle_sbp_callback(
        {
            "order": {
                "id": "prov-callback-1",
                "status": "CREATED",
                "merchantOrderId": attempt.merchant_order_id,
                "paymentAmount": attempt.payment_amount_minor,
                "paymentCurrency": "RUB",
            }
        }
    )

    payment_service.order_crud.try_bind_attempt_provider_order_id.assert_called_once()
    payment_service.session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_callback_recovery_via_merchant_order_id_after_lost_create_order(
    payment_service: PaymentService,
) -> None:
    attempt = _attempt(
        provider_order_id=None,
        init_state="creating",
        provider_status="CREATED",
    )
    order = _order()
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=None
    )
    payment_service.order_crud.get_payment_attempt_by_merchant_order_id = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.try_bind_attempt_provider_order_id = AsyncMock(
        return_value=True
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    _mock_locked_attempt(payment_service, attempt)
    payment_service.session.commit = AsyncMock()
    payment_service.session.flush = AsyncMock()

    await payment_service.handle_sbp_callback(
        {
            "order": {
                "id": "prov-lost-http",
                "status": "QRCDATA_CREATED",
                "merchantOrderId": attempt.merchant_order_id,
                "paymentAmount": attempt.payment_amount_minor,
                "paymentCurrency": "RUB",
            }
        }
    )

    assert attempt.provider_status == "QRCDATA_CREATED"
    payment_service.session.commit.assert_called_once()


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_uses_distinct_x_req_ids_for_post_and_get(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    mock_settings.SBP_CALLBACK_URL = "https://cb.test"
    mock_settings.SBP_MIN_PAYMENT_AMOUNT_MINOR = 100
    mock_settings.SBP_MAX_PAYMENT_AMOUNT_MINOR = 10_000_000
    order = _order()
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    payment_service.order_crud.create_payment_attempt = AsyncMock(
        side_effect=lambda **kwargs: _attempt(
            id=5,
            attempt_number=kwargs["attempt_number"],
            merchant_order_id=kwargs["merchant_order_id"],
            x_req_id_order=kwargs["x_req_id_order"],
            x_req_id_qr=kwargs["x_req_id_qr"],
            provider_order_id=None,
            init_state="creating",
            provider_status="CREATED",
            qr_created_at=None,
            qr_expires_at=None,
        )
    )
    ready = _attempt(
        id=5,
        attempt_number=1,
        provider_order_id="prov-new",
        provider_status="QRCDATA_CREATED",
    )

    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=ready
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=ready)
    payment_service.sbp.create_order = AsyncMock(
        return_value={"id": "prov-new", "status": "CREATED"}
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value={"status": "QRCDATA_CREATED", "payload": "https://qr/new"}
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    await payment_service.init_payment(1, 10)

    create_order_x = payment_service.sbp.create_order.call_args.kwargs["x_req_id"]
    create_qr_x = payment_service.sbp.create_qr.call_args.args[1]
    assert create_order_x == x_req_id_for_order(1, 1)
    assert create_qr_x == x_req_id_for_qr(1, 1)
    assert create_order_x != create_qr_x
    payment_service.sbp.get_order.assert_not_called()


def test_provider_status_transitions() -> None:
    assert is_provider_status_transition_allowed("CREATED", "QRCDATA_CREATED")
    assert is_provider_status_transition_allowed("CREATED", "DECLINED")
    assert is_provider_status_transition_allowed("CREATED", PAYMENT_ACCEPTED_STATUS)
    assert is_provider_status_transition_allowed("CREATED", "IN_PROCESS")
    assert is_provider_status_transition_allowed("QRCDATA_CREATED", "IN_PROCESS")
    assert is_provider_status_transition_allowed("IN_PROCESS", "QRCDATA_IN_PROGRESS")
    assert is_provider_status_transition_allowed("QRCDATA_CREATED", "DECLINED")
    assert is_provider_status_transition_allowed("DECLINED", PAYMENT_ACCEPTED_STATUS)
    assert not is_provider_status_transition_allowed(
        PAYMENT_ACCEPTED_STATUS, "DECLINED"
    )
    assert not is_provider_status_transition_allowed("DECLINED", "QRCDATA_CREATED")
    assert not is_provider_status_transition_allowed("DECLINED", "CREATED")


def test_expired_qr_not_normalized_as_waiting() -> None:
    now = utc_now_naive()
    attempt = _attempt(
        provider_status="IN_PROCESS",
        qr_expires_at=now - timedelta(minutes=1),
    )
    result = normalize_order_payment_from_attempt(
        payment_paid_at=None,
        latest_attempt=attempt,
        payment_provider="sbp",
    )
    assert result.payment_state == "initializing"


def test_new_provider_get_x_req_id_is_unique() -> None:
    first = new_provider_get_x_req_id()
    second = new_provider_get_x_req_id()
    assert first != second
    assert first.startswith("shopstore-get-")


@pytest.mark.asyncio
async def test_create_order_response_does_not_overwrite_ips_accepted(
    payment_service: PaymentService,
) -> None:
    paid_at = utc_now_naive()
    locked = _attempt(
        provider_status=PAYMENT_ACCEPTED_STATUS,
        paid_at=paid_at,
    )
    order = _order()
    _mock_locked_attempt(payment_service, locked)
    payment_service.sbp.create_order = AsyncMock(
        return_value={"id": locked.provider_order_id, "status": "CREATED"}
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=locked
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service._complete_provider_order_for_attempt(order, locked)

    assert locked.provider_status == PAYMENT_ACCEPTED_STATUS
    assert result.payment_state == "paid"
    payment_service.sbp.create_qr.assert_not_called()


def test_payment_init_schema_serializes_qr_expires_at_as_utc_z() -> None:
    from src.schemas.order import PaymentInitSchema

    payload = PaymentInitSchema(
        order_id=1,
        provider="sbp",
        payment_attempt_id=1,
        payment_state="waiting",
        qr_expires_at=utc_now_naive(),
    ).model_dump(mode="json")
    assert str(payload["qr_expires_at"]).endswith("Z")


@pytest.mark.asyncio
async def test_sync_order_payment_aggregate_updates_unpaid_latest() -> None:
    from src.models.order import Order
    from src.repositories.order_repo import CrudOrder

    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    order = _order()
    order.payment_provider = None
    order.payment_order_id = None
    order.payment_status = None
    attempt = _attempt(provider_status="IN_PROCESS")
    crud = CrudOrder(session=session, model=Order)

    await crud.sync_order_payment_aggregate(order, attempt, is_latest_attempt=True)

    assert order.payment_provider == "sbp"
    assert order.payment_order_id == attempt.provider_order_id
    assert order.payment_status == "IN_PROCESS"


def test_order_schema_has_no_payment_qr_payload_field() -> None:
    from src.schemas.order import OrderSchema

    assert "payment_qr_payload" not in OrderSchema.model_fields


@pytest.mark.asyncio
async def test_list_admin_orders_loads_latest_attempts_batch() -> None:
    from src.services.orders.order_service import OrderService

    session = AsyncMock()
    service = OrderService(session)
    service.order_crud = AsyncMock()
    order = _order(id=7)
    attempt = _attempt(order_id=7, provider_status="DECLINED")
    service.order_crud.count_all = AsyncMock(return_value=1)
    service.order_crud.list_all = AsyncMock(return_value=[order])
    service.order_crud.get_latest_payment_attempts_for_orders = AsyncMock(
        return_value={7: attempt}
    )
    service._build_order_items = AsyncMock(return_value=[])
    service.session.get = AsyncMock(return_value=MagicMock())
    service._build_order_schema_with_user = AsyncMock(
        return_value=MagicMock(payment_state="failed")
    )

    await service.list_admin_orders()

    service.order_crud.get_latest_payment_attempts_for_orders.assert_called_once_with(
        [7]
    )
    assert (
        service._build_order_schema_with_user.call_args.kwargs["latest_attempt"]
        is attempt
    )


@pytest.mark.asyncio
async def test_callback_matches_attempt_amount_not_order_total(
    payment_service: PaymentService,
) -> None:
    attempt = _attempt(payment_amount_minor=5000)
    assert payment_service._callback_payload_matches_attempt(
        attempt,
        {
            "merchantOrderId": attempt.merchant_order_id,
            "paymentAmount": 5000,
            "paymentCurrency": "RUB",
        },
    )
    assert not payment_service._callback_payload_matches_attempt(
        attempt,
        {
            "merchantOrderId": attempt.merchant_order_id,
            "paymentAmount": 9999,
            "paymentCurrency": "RUB",
        },
    )


@pytest.mark.asyncio
async def test_init_bootstrap_first_attempt_blocked_at_limit(
    payment_service: PaymentService,
) -> None:
    order = _order()
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(return_value=None)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=5)
    payment_service.session.commit = AsyncMock()
    payment_service._create_payment_attempt_row = AsyncMock()

    bootstrap = await payment_service._init_bootstrap_under_order_lock(1, 10)

    assert bootstrap.kind == "exhausted"
    payment_service._create_payment_attempt_row.assert_not_called()


@pytest.mark.asyncio
async def test_resume_qr_does_not_create_new_attempt(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(provider_status="QRCDATA_CREATED")
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()
    payment_service._create_payment_attempt_row = AsyncMock()

    bootstrap = await payment_service._init_bootstrap_under_order_lock(1, 10)

    assert bootstrap.kind == "continue"
    payment_service._create_payment_attempt_row.assert_not_called()


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_fifth_incomplete_attempt_resumes_without_sixth(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    mock_settings.SBP_CALLBACK_URL = "https://cb.test"
    mock_settings.SBP_MIN_PAYMENT_AMOUNT_MINOR = 100
    mock_settings.SBP_MAX_PAYMENT_AMOUNT_MINOR = 10_000_000
    order = _order()
    incomplete = _attempt(
        id=5,
        attempt_number=5,
        merchant_order_id=merchant_order_id_for(1, 5),
        x_req_id_order=x_req_id_for_order(1, 5),
        x_req_id_qr=x_req_id_for_qr(1, 5),
        provider_order_id=None,
        init_state="creating",
        provider_status=None,
        qr_created_at=None,
        qr_expires_at=None,
    )
    ready = _attempt(
        id=5,
        attempt_number=5,
        merchant_order_id=merchant_order_id_for(1, 5),
        x_req_id_order=x_req_id_for_order(1, 5),
        x_req_id_qr=x_req_id_for_qr(1, 5),
        provider_order_id="prov-attempt-5",
        provider_status="QRCDATA_CREATED",
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=5)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=incomplete
    )
    payment_service.order_crud.create_payment_attempt = AsyncMock()
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=ready
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(return_value=ready)
    payment_service.sbp.create_order = AsyncMock(
        return_value={"id": "prov-attempt-5", "status": "CREATED"}
    )
    payment_service.sbp.create_qr = AsyncMock(
        return_value={"status": "QRCDATA_CREATED", "payload": "https://qr/attempt-5"}
    )
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.session.commit = AsyncMock()
    payment_service.session.refresh = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_state != "exhausted"
    assert result.payment_attempts_exhausted is False
    payment_service.order_crud.create_payment_attempt.assert_not_called()
    assert payment_service.sbp.create_order.call_args.kwargs["x_req_id"] == (
        x_req_id_for_order(1, 5)
    )
    assert result.payment_qr_payload == "https://qr/attempt-5"


@pytest.mark.asyncio
async def test_init_bootstrap_paid_race_before_ensure_payment_allowed(
    payment_service: PaymentService,
) -> None:
    paid_at = utc_now_naive()
    order_paid = _order(
        payment_paid_at=paid_at,
        payment_due_at=paid_at - timedelta(hours=2),
    )
    attempt = _attempt()
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order_paid)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()

    bootstrap = await payment_service._init_bootstrap_under_order_lock(1, 10)

    assert bootstrap.kind == "paid"
    assert bootstrap.attempt_id == attempt.id


@pytest.mark.asyncio
@patch("src.services.payment_service.settings")
@patch(
    "src.services.payment_service.try_acquire_redis_lock",
    new_callable=AsyncMock,
    return_value="lock-token",
)
@patch("src.services.payment_service.release_redis_lock", new_callable=AsyncMock)
async def test_init_payment_paid_race_before_order_lock(
    _release,
    _lock,
    mock_settings,
    payment_service: PaymentService,
) -> None:
    mock_settings.SBP_ENABLED = True
    mock_settings.ORDER_MAX_PAYMENT_ATTEMPTS = 5
    mock_settings.SBP_TEST_MODE = True
    paid_at = utc_now_naive()
    order_unpaid = _order(payment_due_at=paid_at - timedelta(hours=2))
    order_paid = _order(
        payment_paid_at=paid_at,
        payment_due_at=paid_at - timedelta(hours=2),
    )
    attempt = _attempt()
    payment_service._get_user_order = AsyncMock(return_value=order_unpaid)
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order_paid)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=1)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.get_payment_attempt_by_id = AsyncMock(
        return_value=attempt
    )
    payment_service.session.commit = AsyncMock()

    result = await payment_service.init_payment(1, 10)

    assert result.payment_state == "paid"
    assert result.payment_attempts_exhausted is False
    payment_service.sbp.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_mark_attempt_accepted_returns_payment_accepted_notify(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt()
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=attempt.id
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        return_value=order.id
    )
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()

    from src.services.payment_service import PaymentAcceptedNotify

    notify = await payment_service._mark_attempt_accepted(
        attempt, order, utc_now_naive()
    )
    assert isinstance(notify, PaymentAcceptedNotify)
    assert notify.order_id == order.id
    assert notify.attempt_id == attempt.id


@pytest.mark.asyncio
async def test_mark_attempt_accepted_duplicate_callback_no_notify(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt()
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=None
    )

    notify = await payment_service._mark_attempt_accepted(
        attempt, order, utc_now_naive()
    )
    assert notify is None
    payment_service.order_crud.create_order_event.assert_not_called()


@pytest.mark.asyncio
async def test_callback_payment_accepted_sends_admin_telegram_once(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(provider_order_id="prov-pay-1")
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        side_effect=[attempt.id, None]
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        side_effect=[order.id, None]
    )
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()
    payment_service.session.commit = AsyncMock()
    payment_service._schedule_payment_notifications = AsyncMock()

    payload = {
        "order": {
            "id": "prov-pay-1",
            "status": PAYMENT_ACCEPTED_STATUS,
            "merchantOrderId": attempt.merchant_order_id,
            "paymentAmount": attempt.payment_amount_minor,
            "paymentCurrency": "RUB",
        }
    }
    await payment_service.handle_sbp_callback(payload)
    await payment_service.handle_sbp_callback(payload)

    payment_service._schedule_payment_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_payment_accepted_commits_when_outbox_scheduled(
    payment_service: PaymentService,
) -> None:
    order = _order()
    attempt = _attempt(provider_order_id="prov-pay-2")
    payment_service.order_crud.get_payment_attempt_by_provider_order_id = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.get_payment_attempt_by_id_for_update = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=attempt.id
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        return_value=order.id
    )
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.create_order_event = AsyncMock()

    async def commit_side_effect():
        order.payment_paid_at = utc_now_naive()

    payment_service.session.commit = AsyncMock(side_effect=commit_side_effect)

    with (
        patch.object(
            AdminNotificationService,
            "send_order_payment_accepted",
            new_callable=AsyncMock,
        ),
        patch.object(
            CustomerNotificationService,
            "notify_payment_received",
            new_callable=AsyncMock,
        ),
    ):
        await payment_service.handle_sbp_callback(
            {
                "order": {
                    "id": "prov-pay-2",
                    "status": PAYMENT_ACCEPTED_STATUS,
                    "merchantOrderId": attempt.merchant_order_id,
                    "paymentAmount": attempt.payment_amount_minor,
                    "paymentCurrency": "RUB",
                }
            }
        )

    payment_service.session.commit.assert_awaited()
    assert order.payment_paid_at is not None
