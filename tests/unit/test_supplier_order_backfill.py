from decimal import Decimal

from src.services.orders.supplier_orders import (
    goods_eur_from_lines,
    normalize_legacy_supplier_order_id,
)


# Пустой и пробельный TP ID не зеркалируются.
def test_normalize_legacy_supplier_order_id_skips_blank() -> None:
    assert normalize_legacy_supplier_order_id(None) is None
    assert normalize_legacy_supplier_order_id("") is None
    assert normalize_legacy_supplier_order_id("   ") is None
    assert normalize_legacy_supplier_order_id(" TP-1 ") == "TP-1"


# goods_eur — сумма qty × unit с округлением до цента.
def test_goods_eur_from_lines_quantizes_cents() -> None:
    total = goods_eur_from_lines(
        [
            (2, Decimal("10.005")),
            (1, Decimal("5.00")),
        ]
    )
    assert total == Decimal("25.02")
