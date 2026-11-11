from datetime import timedelta
from pathlib import Path

import pytest

from scripts.mark_order_paid import mark_order_paid, require_prod_confirmation
from src.core.config import settings
from src.models.order import Order
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import SupplierOrderService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import PAYMENT_ACCEPTED_STATUS
from tests.integration.helpers.order_admin import create_telegram_user
from tests.integration.test_unpaid_order_expiration_job import _create_unpaid_order

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _prepare_unpaid_order(suffix: int) -> Order:
    async with async_session_maker() as session:
        user = await create_telegram_user(session, suffix)
        order = await _create_unpaid_order(
            session,
            user.id,
            suffix,
            payment_due_at=utc_now_naive() + timedelta(hours=5),
        )
        await session.commit()
        await session.refresh(order)
        return order


async def _order_events(order_id: int) -> list[str]:
    async with async_session_maker() as session:
        rows = await OrderService(session).order_crud.get_order_events(order_id)
        return [str(row.event_type) for row in rows]


@pytest.mark.asyncio
async def test_mark_order_paid_enables_packing_recommendation(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    order = await _prepare_unpaid_order(merge_unique_suffix + 80_000)

    await mark_order_paid(order.id)

    async with async_session_maker() as session:
        fresh = await session.get(Order, order.id)
        assert fresh is not None
        assert fresh.payment_paid_at is not None
        assert fresh.payment_status == PAYMENT_ACCEPTED_STATUS
        assert fresh.paid_supplier_order_count is not None
        preview = await SupplierOrderService(session).packing_recommendation(order.id)

    events = await _order_events(order.id)
    assert "supplier_order_recommendation_applied" not in events
    assert preview.can_apply is True


@pytest.mark.asyncio
async def test_mark_order_paid_repeat_is_noop(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    order = await _prepare_unpaid_order(merge_unique_suffix + 81_000)

    await mark_order_paid(order.id)
    await mark_order_paid(order.id)

    async with async_session_maker() as session:
        fresh = await session.get(Order, order.id)
        assert fresh is not None
        assert fresh.payment_paid_at is not None
        attempts = await CrudOrder(session=session, model=Order).count_payment_attempts(
            order.id
        )
    assert attempts == 1
    assert "supplier_order_recommendation_applied" not in await _order_events(order.id)


@pytest.mark.asyncio
async def test_mark_order_paid_prod_requires_confirm(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    order = await _prepare_unpaid_order(merge_unique_suffix + 82_000)

    with pytest.raises(SystemExit, match="CONFIRM"):
        await mark_order_paid(order.id)

    async with async_session_maker() as session:
        fresh = await session.get(Order, order.id)
        assert fresh is not None
        assert fresh.payment_paid_at is None


@pytest.mark.asyncio
async def test_mark_order_paid_prod_wrong_confirm_leaves_db(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    order = await _prepare_unpaid_order(merge_unique_suffix + 83_000)

    with pytest.raises(SystemExit, match="CONFIRM"):
        await mark_order_paid(order.id, confirm_order_id=order.id + 1)

    async with async_session_maker() as session:
        fresh = await session.get(Order, order.id)
        assert fresh is not None
        assert fresh.payment_paid_at is None


@pytest.mark.asyncio
async def test_mark_order_paid_prod_confirm_allows_payment(
    merge_unique_suffix: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "outbox")
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    order = await _prepare_unpaid_order(merge_unique_suffix + 84_000)

    await mark_order_paid(order.id, confirm_order_id=order.id)

    async with async_session_maker() as session:
        fresh = await session.get(Order, order.id)
        assert fresh is not None
        assert fresh.payment_paid_at is not None
        preview = await SupplierOrderService(session).packing_recommendation(order.id)
    assert preview.can_apply is True


def test_require_prod_confirmation_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    require_prod_confirmation(355, None)


def test_require_prod_confirmation_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    with pytest.raises(SystemExit, match="CONFIRM"):
        require_prod_confirmation(355, None)
    with pytest.raises(SystemExit, match="CONFIRM"):
        require_prod_confirmation(355, 123)
    require_prod_confirmation(355, 355)


def test_script_does_not_apply_recommendation() -> None:
    script = (REPO_ROOT / "scripts" / "mark_order_paid.py").read_text(encoding="utf-8")
    assert "apply_packing_recommendation" not in script
    assert "handle_sbp_callback" not in script
    assert "freeze_paid_supplier_order_count" in script
