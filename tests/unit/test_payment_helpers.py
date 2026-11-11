from decimal import Decimal

from src.services.payment_service import (
    merchant_order_id_for,
    order_amount_minor,
    parse_local_order_id_from_merchant,
    x_req_id_for_order,
    x_req_id_for_qr,
)


def test_merchant_order_id_for() -> None:
    assert merchant_order_id_for(42, 1) == "shopstore-42/1"
    assert merchant_order_id_for(42, 2) == "shopstore-42/2"


def test_parse_local_order_id_from_merchant() -> None:
    assert parse_local_order_id_from_merchant("shopstore-7") == 7
    assert parse_local_order_id_from_merchant("shopstore-7/1") == 7
    assert parse_local_order_id_from_merchant("shopstore-7/2") == 7
    assert parse_local_order_id_from_merchant("other-7") is None


def test_order_amount_minor() -> None:
    assert order_amount_minor(Decimal("10.50")) == 1050
    assert order_amount_minor(Decimal("100")) == 10000


def test_x_req_ids_per_attempt() -> None:
    assert x_req_id_for_order(5, 1) == "shopstore-order-5-1"
    assert x_req_id_for_qr(5, 2) == "shopstore-qrc-5-2"
