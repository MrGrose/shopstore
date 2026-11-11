from decimal import Decimal
from types import SimpleNamespace

from src.content.client_texts import (
    CUSTOMER_ASSEMBLY_PARCEL_DRAFT,
    CUSTOMER_ASSEMBLY_SINGLE_DRAFT,
)
from src.models.notification_outbox import NotificationOutboxStatus
from src.models.order import SupplierOrderStatus
from src.services.notifications.customer_notification_keys import (
    assembly_parcel_notify_key,
)
from src.services.orders.shipments import SHIPMENT_TELEGRAM_SENT_MARK
from src.services.orders.supplier_orders import (
    SupplierOrderView,
    apply_assembly_notify_state,
    assembly_parcel_count,
    render_assembly_parcel_message,
)


def _view(
    so_id: int,
    seq: int,
    status: str = SupplierOrderStatus.PLACED,
    has_lines: bool = True,
) -> SupplierOrderView:
    lines = [SimpleNamespace(quantity=1)] if has_lines else []
    return SupplierOrderView(
        id=so_id,
        seq=seq,
        status=status,
        status_label=status,
        external_id="TP-1",
        goods_eur=Decimal("10.00"),
        supplier_shipping_eur=Decimal("0.00"),
        lines=lines,  # type: ignore[arg-type]
        is_draft=status == SupplierOrderStatus.DRAFT,
        line_qty_by_item_id={},
        line_controls=(),
        place_copy_text=None,
        goods_cap_eur=Decimal("270.01"),
        goods_remaining_eur=Decimal("260.01"),
        goods_fill_percent=4,
    )


def test_render_single_parcel_uses_short_copy() -> None:
    text = render_assembly_parcel_message(None, 232, 1, 1)
    assert text == CUSTOMER_ASSEMBLY_SINGLE_DRAFT


def test_render_multi_parcel_includes_order_and_seq() -> None:
    text = render_assembly_parcel_message(None, 232, 2, 3)
    assert text == CUSTOMER_ASSEMBLY_PARCEL_DRAFT.format(order_id=232, seq=2)
    assert "По заказу #232" in text
    assert "Посылка №2" in text


def test_render_respects_custom_placeholders() -> None:
    text = render_assembly_parcel_message(
        "Посылка {seq} заказа {order_id}",
        10,
        3,
        3,
    )
    assert text == "Посылка 3 заказа 10"


def test_assembly_parcel_count_skips_cancelled_and_empty_draft() -> None:
    views = [
        _view(1, 1, SupplierOrderStatus.PLACED),
        _view(2, 2, SupplierOrderStatus.DRAFT, has_lines=True),
        _view(3, 3, SupplierOrderStatus.DRAFT, has_lines=False),
        _view(4, 4, SupplierOrderStatus.CANCELLED, has_lines=True),
    ]
    assert assembly_parcel_count(views) == 2


def test_apply_assembly_notify_state_marks_sent_and_catchup() -> None:
    views = [_view(11, 1), _view(12, 2)]
    key = assembly_parcel_notify_key(232, 11)
    updated = apply_assembly_notify_state(
        views,
        232,
        {f"{key}:telegram": NotificationOutboxStatus.SENT},
    )
    assert updated[0].customer_notify_label == SHIPMENT_TELEGRAM_SENT_MARK
    assert updated[0].can_notify is False
    assert updated[1].can_notify is True
    assert "Посылка №2" in updated[1].customer_notify_draft
