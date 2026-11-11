from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.orders.order_service import OrderService
from src.utils.datetime_fmt import utc_now_naive


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (0, False),
        (1, True),
        (2, False),
        (5, False),
    ],
)
def test_is_borderline_available(available: int, expected: bool) -> None:
    assert OrderService.is_borderline_available(available) is expected


def test_resolve_availability_status_pending() -> None:
    status = OrderService.resolve_availability_status([{"product_id": 1}])
    assert status == AvailabilityConfirmationStatus.PENDING


def test_resolve_availability_status_not_required() -> None:
    status = OrderService.resolve_availability_status([])
    assert status == AvailabilityConfirmationStatus.NOT_REQUIRED


def test_compute_payment_allowed_pending_and_unavailable() -> None:
    pending = SimpleNamespace(
        status=OrderStatus.PROCESSING,
        payment_paid_at=None,
        availability_confirmation_status=AvailabilityConfirmationStatus.PENDING,
    )
    unavailable = SimpleNamespace(
        status=OrderStatus.PROCESSING,
        payment_paid_at=None,
        availability_confirmation_status=AvailabilityConfirmationStatus.UNAVAILABLE,
    )
    confirmed = SimpleNamespace(
        status=OrderStatus.CREATED,
        payment_paid_at=None,
        payment_due_at=utc_now_naive() + timedelta(hours=24),
        availability_confirmation_status=AvailabilityConfirmationStatus.CONFIRMED,
    )
    assert OrderService.compute_payment_allowed(pending) is False
    assert OrderService.compute_payment_allowed(unavailable) is False
    assert OrderService.compute_payment_allowed(confirmed) is True


def test_availability_message_for_status() -> None:
    assert (
        OrderService.availability_message_for_status(
            AvailabilityConfirmationStatus.PENDING
        )
        == OrderService.AVAILABILITY_PENDING_MESSAGE
    )
    assert (
        OrderService.availability_message_for_status(
            AvailabilityConfirmationStatus.UNAVAILABLE
        )
        == "Часть товаров недоступна."
    )
    assert (
        OrderService.availability_message_for_status(
            AvailabilityConfirmationStatus.CONFIRMED
        )
        is None
    )


def test_storefront_visibility_uses_is_active_not_catalog_in_stock() -> None:
    product = SimpleNamespace(is_active=True, catalog_in_stock=False)
    flags = OrderService._storefront_visibility_for_item(product, None, None)
    assert flags["is_on_storefront"] is True
    assert flags["is_removed_from_storefront"] is False


def test_storefront_visibility_variant_must_be_available() -> None:
    product = SimpleNamespace(is_active=True, catalog_in_stock=True)
    variant = SimpleNamespace(available=False)
    flags = OrderService._storefront_visibility_for_item(product, variant, 1)
    assert flags["is_on_storefront"] is False
