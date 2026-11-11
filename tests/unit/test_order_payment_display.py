from datetime import datetime

import pytest

from src.utils.datetime_fmt import format_datetime_msk_short
from src.utils.payment import (
    PAYMENT_EXHAUSTED_LABEL,
    PAYMENT_STATE_LABELS,
    normalize_order_payment,
)


def test_payment_state_labels_customer_copy() -> None:
    assert PAYMENT_STATE_LABELS["initializing"] == "Создаём оплату"
    assert PAYMENT_STATE_LABELS["not_started"] == "Можно оплатить"
    assert PAYMENT_EXHAUSTED_LABEL == "Лимит попыток исчерпан"


def test_format_datetime_msk_short() -> None:
    value = datetime(2026, 6, 29, 12, 23, 0)
    assert format_datetime_msk_short(value) == "29.06, 15:23"


@pytest.mark.parametrize(
    ("kwargs", "expected_state", "expected_label"),
    [
        (
            {"payment_paid_at": datetime(2026, 1, 1)},
            "paid",
            "Оплачено",
        ),
        (
            {"payment_status": "IPS_ACCEPTED"},
            "paid",
            "Оплачено",
        ),
        (
            {"payment_qr_payload": "https://qr.example/pay"},
            "waiting",
            "Ожидает оплаты",
        ),
        (
            {"payment_status": "QRCDATA_CREATED"},
            "waiting",
            "Ожидает оплаты",
        ),
        (
            {"payment_status": "IN_PROCESS"},
            "waiting",
            "Ожидает оплаты",
        ),
        (
            {"payment_status": "QRCDATA_IN_PROGRESS"},
            "waiting",
            "Ожидает оплаты",
        ),
        (
            {"payment_status": "CREATED"},
            "initializing",
            "Создаём оплату",
        ),
        (
            {
                "payment_status": "DECLINED",
                "payment_qr_payload": "https://qr.example/pay",
            },
            "failed",
            "Оплата не прошла",
        ),
        (
            {"payment_status": "EXPIRED"},
            "failed",
            "Оплата не прошла",
        ),
        (
            {"payment_provider": "sbp", "payment_order_id": "abc-123"},
            "initializing",
            "Создаём оплату",
        ),
        (
            {},
            "not_started",
            "Можно оплатить",
        ),
    ],
)
def test_normalize_order_payment_states(
    kwargs: dict[str, object],
    expected_state: str,
    expected_label: str,
) -> None:
    result = normalize_order_payment(
        payment_paid_at=kwargs.get("payment_paid_at"),  # type: ignore[arg-type]
        payment_status=kwargs.get("payment_status"),  # type: ignore[arg-type]
        payment_qr_id=kwargs.get("payment_qr_id"),  # type: ignore[arg-type]
        payment_qr_payload=kwargs.get("payment_qr_payload"),  # type: ignore[arg-type]
        payment_provider=kwargs.get("payment_provider"),  # type: ignore[arg-type]
        payment_order_id=kwargs.get("payment_order_id"),  # type: ignore[arg-type]
        payment_init_state=kwargs.get("payment_init_state"),  # type: ignore[arg-type]
    )
    assert result.payment_state == expected_state
    assert result.payment_label == expected_label


def test_normalize_order_payment_sbp_method_label() -> None:
    result = normalize_order_payment(
        payment_paid_at=None,
        payment_status="CREATED",
        payment_qr_id=None,
        payment_qr_payload=None,
        payment_provider="sbp",
        payment_order_id="order-1",
    )
    assert result.payment_method_label == "СБП"


def test_completed_order_without_payment_is_not_paid() -> None:
    result = normalize_order_payment(
        payment_paid_at=None,
        payment_status=None,
        payment_qr_id=None,
        payment_qr_payload=None,
        payment_provider=None,
        payment_order_id=None,
    )
    assert result.payment_state == "not_started"
