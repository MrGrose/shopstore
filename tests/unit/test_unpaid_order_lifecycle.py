from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import settings
from src.models.order import (
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    CANCELLATION_REASON_PAYMENT_TIMEOUT,
    OrderStatus,
)
from src.services.orders.order_service import OrderService
from src.services.payment_service import LateNotify, PaymentService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import (
    PAYMENT_ACCEPTED_STATUS,
    attempt_init_incomplete,
    attempt_qr_alive,
    payment_attempts_exhausted,
    payment_deadline_blocks_payment,
)
from tests.unit.test_payment_attempts import _attempt, _order


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


def test_compute_payment_allowed_rejects_expired_deadline() -> None:
    order = _order()
    order.payment_due_at = utc_now_naive() - timedelta(hours=1)
    assert OrderService.compute_payment_allowed(order) is False


def test_compute_payment_allowed_allows_null_deadline_pending_path() -> None:
    order = _order(availability_confirmation_status="pending")
    order.payment_due_at = None
    assert OrderService.compute_payment_allowed(order) is False


def test_payment_deadline_from_now_uses_config() -> None:
    before = utc_now_naive()
    deadline = OrderService.payment_deadline_from_now()
    assert deadline >= before + timedelta(
        hours=settings.ORDER_PAYMENT_DEADLINE_HOURS - 1
    )


def test_pending_availability_has_no_payment_due_at_semantics() -> None:
    order = _order(availability_confirmation_status="pending")
    order.payment_due_at = None
    assert OrderService.compute_payment_allowed(order) is False


@pytest.mark.asyncio
async def test_create_order_rejects_active_unpaid_limit() -> None:
    service = OrderService(AsyncMock())
    service.order_crud = AsyncMock()
    service.order_crud.get_by_idempotency_key = AsyncMock(return_value=None)
    service.cart_crud = AsyncMock()
    service.pricing_service = AsyncMock()
    service.promo_service = AsyncMock()
    service.session = AsyncMock()
    service.session.get = AsyncMock(return_value=MagicMock())
    pricing = MagicMock()
    pricing.eur_rate = Decimal("100")
    pricing.delivery_fee_eur = Decimal("30")
    service.pricing_service.get_settings = AsyncMock(return_value=pricing)
    with patch(
        "src.services.orders.order_service.calculate_supplier_cost_eur",
        return_value=Decimal("10"),
    ):
        with patch("src.services.orders.order_service.IdentityService") as identity_cls:
            identity_cls.return_value.get_telegram_id_for_user = AsyncMock(
                return_value=1
            )
            service.cart_crud.get_user_cart = AsyncMock(return_value=[MagicMock()])
            service._load_checkout_products_context = AsyncMock(return_value=({}, {}))
            service._validate_cart_items_stock = AsyncMock()
            service._collect_low_stock_items = AsyncMock(return_value=[])
            service.order_crud.count_active_unpaid_orders = AsyncMock(
                return_value=settings.ORDER_MAX_ACTIVE_UNPAID_ORDERS_PER_USER
            )

            with pytest.raises(ValueError, match="активных неоплаченных"):
                await service.create_order(
                    user_id=1,
                    idempotency_key="k2",
                    notification_channels=["telegram"],
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cancellation_reason",
    [
        CANCELLATION_REASON_PAYMENT_TIMEOUT,
        CANCELLATION_REASON_CUSTOMER_REQUEST,
        None,
    ],
)
async def test_mark_attempt_accepted_late_notify_once(
    payment_service: PaymentService,
    cancellation_reason: str | None,
) -> None:
    order = _order(status=OrderStatus.CANCELLED)
    order.cancellation_reason = cancellation_reason
    attempt = _attempt()
    payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
        return_value=1
    )
    payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
        return_value=1
    )
    payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=order)
    payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
    payment_service.order_crud.has_order_event_type = AsyncMock(return_value=False)
    payment_service.order_crud.create_order_event = AsyncMock()

    notify = await payment_service._mark_attempt_accepted(
        attempt, order, utc_now_naive()
    )
    assert isinstance(notify, LateNotify)

    payment_service.order_crud.has_order_event_type = AsyncMock(return_value=True)
    notify_repeat = await payment_service._mark_attempt_accepted(
        attempt, order, utc_now_naive()
    )
    assert notify_repeat is None


@pytest.mark.asyncio
async def test_schedule_late_notify_uses_late_received_customer_template(
    payment_service: PaymentService,
) -> None:
    notify = LateNotify(order_id=42, attempt_id=7)
    with (
        patch(
            "src.services.payment_service.CustomerNotificationService"
        ) as customer_cls,
        patch("src.services.payment_service.AdminNotificationService") as admin_cls,
    ):
        customer = customer_cls.return_value
        customer.notify_payment_late_received = AsyncMock()
        customer.notify_payment_received = AsyncMock()
        admin = admin_cls.return_value
        admin.send_late_payment_after_auto_cancel = AsyncMock()

        await payment_service._schedule_payment_notifications(notify)

    admin.send_late_payment_after_auto_cancel.assert_awaited_once_with(42, 7)
    customer.notify_payment_late_received.assert_awaited_once_with(42, 7)
    customer.notify_payment_received.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_late_payment_telegram_only_on_late_notify(
    payment_service: PaymentService,
) -> None:
    from tests.unit.test_payment_attempts import _mock_locked_attempt

    with patch.object(
        payment_service,
        "_schedule_payment_notifications",
        new_callable=AsyncMock,
    ) as send_tg:
        order = _order()
        attempt = _attempt()
        _mock_locked_attempt(payment_service, attempt)
        payment_service.order_crud.get_by_id = AsyncMock(return_value=order)
        payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
            return_value=attempt
        )
        payment_service.order_crud.mark_payment_attempt_paid_if_unpaid = AsyncMock(
            return_value=1
        )
        payment_service.order_crud.mark_payment_accepted_if_unpaid = AsyncMock(
            return_value=1
        )
        locked = _order(status=OrderStatus.CANCELLED)
        locked.cancellation_reason = CANCELLATION_REASON_PAYMENT_TIMEOUT
        payment_service.order_crud.get_by_id_for_update = AsyncMock(return_value=locked)
        payment_service.order_crud.sync_order_payment_aggregate = AsyncMock()
        payment_service.order_crud.has_order_event_type = AsyncMock(return_value=False)
        payment_service.order_crud.create_order_event = AsyncMock()
        payment_service.session.flush = AsyncMock()
        payment_service.session.commit = AsyncMock()

        late_notify = await payment_service._apply_provider_status_to_attempt(
            attempt.id, PAYMENT_ACCEPTED_STATUS, utc_now_naive()
        )
        if late_notify is not None:
            await payment_service._schedule_payment_notifications(late_notify)
        await payment_service.session.commit()

        send_tg.assert_called_once()
        assert send_tg.call_args.args[0].order_id == locked.id


@pytest.mark.asyncio
async def test_init_payment_blocks_sixth_attempt(
    payment_service: PaymentService,
) -> None:
    order = _order()
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=5)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=_attempt(provider_status="DECLINED", qr_expires_at=None)
    )
    with patch("src.services.payment_service.settings") as cfg:
        cfg.SBP_ENABLED = True
        cfg.ORDER_MAX_PAYMENT_ATTEMPTS = 5
        cfg.SBP_TEST_MODE = True
        result = await payment_service.init_payment(1, 10)
    assert result.payment_state == "exhausted"
    assert result.payment_attempts_exhausted is True
    payment_service.sbp.create_order.assert_not_called()


def test_fifth_live_attempt_not_exhausted() -> None:
    alive = _attempt(attempt_number=5, provider_status="IN_PROCESS")
    assert attempt_qr_alive(alive) is True
    assert payment_attempts_exhausted(5, 5, alive) is False


def test_qr_created_without_expiry_not_alive() -> None:
    attempt = _attempt(provider_status="QRCDATA_CREATED", qr_expires_at=None)
    assert attempt_qr_alive(attempt) is False


def test_fifth_incomplete_attempt_not_exhausted() -> None:
    incomplete = _attempt(
        attempt_number=5,
        init_state="creating",
        provider_order_id=None,
        provider_status=None,
        qr_expires_at=None,
    )
    assert attempt_init_incomplete(incomplete) is True
    assert payment_attempts_exhausted(5, 5, incomplete) is False


def test_fifth_failed_created_not_resumable() -> None:
    stale = _attempt(
        attempt_number=5,
        init_state="failed",
        provider_order_id=None,
        provider_status="CREATED",
        qr_expires_at=None,
    )
    assert attempt_init_incomplete(stale) is False
    assert payment_attempts_exhausted(5, 5, stale) is True


def test_fifth_declined_attempt_is_exhausted() -> None:
    dead = _attempt(
        attempt_number=5,
        provider_status="DECLINED",
        qr_expires_at=None,
    )
    assert payment_attempts_exhausted(5, 5, dead) is True


def test_compute_payment_allowed_after_deadline_with_alive_qr() -> None:
    order = _order()
    order.payment_due_at = utc_now_naive() - timedelta(hours=1)
    alive = _attempt(provider_status="QRCDATA_CREATED")
    assert payment_deadline_blocks_payment(order.payment_due_at, alive) is False
    assert OrderService.compute_payment_allowed(order, latest_attempt=alive) is True


def test_paid_order_after_deadline_not_exhausted_in_schema() -> None:
    service = OrderService(AsyncMock())
    order = _order(
        payment_paid_at=utc_now_naive(),
        payment_due_at=utc_now_naive() - timedelta(hours=2),
    )
    order.items_subtotal_amount = Decimal("100")
    order.discount_items_amount = Decimal("0")
    order.delivery_fee_amount = Decimal("0")
    order.eur_rate_snapshot = Decimal("100")
    attempt = _attempt(
        attempt_number=5,
        provider_status="DECLINED",
        qr_expires_at=None,
    )
    schema = service._build_order_schema(
        order,
        [],
        latest_attempt=attempt,
        payment_attempts_used=5,
    )
    assert schema.payment_state == "paid"
    assert schema.payment_attempts_exhausted is False


@pytest.mark.asyncio
async def test_init_payment_paid_after_deadline_returns_paid(
    payment_service: PaymentService,
) -> None:
    order = _order(
        payment_paid_at=utc_now_naive(),
        payment_due_at=utc_now_naive() - timedelta(hours=2),
    )
    attempt = _attempt(attempt_number=5, provider_status="DECLINED", qr_expires_at=None)
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=attempt
    )
    with patch("src.services.payment_service.settings") as cfg:
        cfg.SBP_ENABLED = True
        cfg.ORDER_MAX_PAYMENT_ATTEMPTS = 5
        cfg.SBP_TEST_MODE = True
        result = await payment_service.init_payment(1, 10)
    assert result.payment_state == "paid"
    assert result.payment_attempts_exhausted is False
    payment_service.sbp.create_order.assert_not_called()


@pytest.mark.asyncio
async def test_init_payment_fifth_live_attempt_resumes_not_exhausted(
    payment_service: PaymentService,
) -> None:
    order = _order(payment_due_at=utc_now_naive() - timedelta(hours=1))
    alive = _attempt(attempt_number=5, provider_status="QRCDATA_CREATED")
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=5)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=alive
    )
    payment_service._qr_payload_from_attempt = MagicMock(return_value="qr-payload")
    with patch("src.services.payment_service.settings") as cfg:
        cfg.SBP_ENABLED = True
        cfg.ORDER_MAX_PAYMENT_ATTEMPTS = 5
        cfg.SBP_TEST_MODE = True
        with patch(
            "src.services.payment_service.try_acquire_redis_lock",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await payment_service.init_payment(1, 10)
    assert result.payment_state != "exhausted"
    assert result.payment_attempts_exhausted is False
    assert result.payment_qr_payload == "qr-payload"


@pytest.mark.asyncio
async def test_init_payment_fifth_failed_created_returns_exhausted(
    payment_service: PaymentService,
) -> None:
    order = _order()
    stale = _attempt(
        attempt_number=5,
        init_state="failed",
        provider_order_id=None,
        provider_status="CREATED",
        qr_expires_at=None,
    )
    payment_service._get_user_order = AsyncMock(return_value=order)
    payment_service.order_crud.count_payment_attempts = AsyncMock(return_value=5)
    payment_service.order_crud.get_latest_payment_attempt = AsyncMock(
        return_value=stale
    )
    payment_service.order_crud.create_payment_attempt = AsyncMock()
    with patch("src.services.payment_service.settings") as cfg:
        cfg.SBP_ENABLED = True
        cfg.ORDER_MAX_PAYMENT_ATTEMPTS = 5
        cfg.SBP_TEST_MODE = True
        result = await payment_service.init_payment(1, 10)
    assert result.payment_state == "exhausted"
    assert result.payment_attempts_exhausted is True
    payment_service.order_crud.create_payment_attempt.assert_not_called()
    payment_service.sbp.create_order.assert_not_called()
