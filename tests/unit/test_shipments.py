from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.order import SupplierOrderStatus
from src.services.orders.pochta_tracking import build_pochta_public_tracking_url
from src.services.orders.shipments import (
    SHIPMENT_TELEGRAM_IDLE_MARK,
    SHIPMENT_TELEGRAM_SENT_MARK,
    ShipmentError,
    ShipmentService,
    admin_list_tp_ids,
    admin_shipment_completion_summary,
    admin_shipment_summary,
    all_shipments_completed,
    all_shipments_delivered,
    apply_customer_notify_state,
    apply_shipment_status,
    build_admin_list_tp_by_order_id,
    build_admin_shipment_cards,
    build_admin_supplier_parcels,
    build_dhl_public_tracking_url,
    build_order_shipment_schemas,
    customer_notify_label_for_outbox,
    customer_tracking_links_for_cj,
    ensure_admin_shipment_completable,
    ensure_shipment_identity_in_message,
    is_legacy_tracking_mirror,
    legacy_supplier_tracking_number,
    mark_shipment_completed,
    render_shipment_customer_message,
    shipment_can_notify_customer,
    shipment_status_from_stage,
    validate_placed_source,
)


# SO другого заказа нельзя привязать к Shipment.
def test_validate_placed_source_rejects_foreign_order() -> None:
    header = SimpleNamespace(order_id=2, status=SupplierOrderStatus.PLACED)
    with pytest.raises(ShipmentError, match="другому заказу"):
        validate_placed_source(1, header)


# Draft и cancelled не дают Shipment.
@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_validate_placed_source_rejects_non_placed(status: str) -> None:
    header = SimpleNamespace(order_id=1, status=status)
    with pytest.raises(ShipmentError, match="оформленного"):
        validate_placed_source(1, header)


# Placed SO того же заказа проходит.
def test_validate_placed_source_accepts_placed() -> None:
    header = SimpleNamespace(order_id=5, status=SupplierOrderStatus.PLACED)
    validate_placed_source(5, header)


# CJ копируется только если TP на Order совпал с SO.external_id.
def test_legacy_tracking_number_only_for_mirror_tp() -> None:
    order = SimpleNamespace(supplier_order_id="TP-100", supplier_tracking_id="CJ-1")
    mirror = SimpleNamespace(external_id="TP-100")
    other = SimpleNamespace(external_id="TP-200")
    assert legacy_supplier_tracking_number(order, mirror) == "CJ-1"
    assert legacy_supplier_tracking_number(order, other) is None
    order.supplier_tracking_id = "  "
    assert legacy_supplier_tracking_number(order, mirror) is None


# ParcelLab/DHL stages схлопываются в preparing/in_transit/delivered.
def test_shipment_status_from_stage_mapping() -> None:
    assert shipment_status_from_stage("delivered") == "delivered"
    assert shipment_status_from_stage("deliverydelivered") == "delivered"
    assert shipment_status_from_stage("in_transit") == "in_transit"
    assert shipment_status_from_stage("dispatched") == "in_transit"
    assert shipment_status_from_stage("last_mile") == "in_transit"
    assert shipment_status_from_stage("pick_up_scheduled") == "preparing"
    assert shipment_status_from_stage("purchased") == "preparing"
    assert shipment_status_from_stage("exception") is None
    assert shipment_status_from_stage("unknown") is None
    assert shipment_status_from_stage("returned") is None


# Delivered не откатывается; unknown не затирает последний status.
def test_apply_shipment_status_monotonic_and_unknown() -> None:
    now = datetime(2026, 8, 19, 12, 0, 0)
    row = SimpleNamespace(status="preparing", status_updated_at=None, delivered_at=None)
    assert apply_shipment_status(row, "in_transit", now) is True
    assert row.status == "in_transit"
    assert row.status_updated_at == now
    assert apply_shipment_status(row, "preparing", now) is False
    assert row.status == "in_transit"
    assert apply_shipment_status(row, None, now) is False
    later = datetime(2026, 8, 19, 13, 0, 0)
    assert apply_shipment_status(row, "delivered", later) is True
    assert row.status == "delivered"
    assert row.delivered_at == later
    assert apply_shipment_status(row, "in_transit", later) is False
    assert row.status == "delivered"


# Второй SO с другим TP не зеркало Order tracking.
def test_is_legacy_tracking_mirror_only_matching_tp() -> None:
    order = SimpleNamespace(supplier_order_id="TP-100")
    assert is_legacy_tracking_mirror(order, SimpleNamespace(external_id="TP-100"))
    assert not is_legacy_tracking_mirror(order, SimpleNamespace(external_id="TP-200"))


# Admin cards: TP from SO.external_id, CJ/status from Shipment, not Order.
def test_build_admin_shipment_cards_uses_so_tp_and_shipment_cj() -> None:
    so1 = SimpleNamespace(id=10, seq=1, external_id="TP-111")
    so2 = SimpleNamespace(id=11, seq=2, external_id="TP-222")
    row1 = SimpleNamespace(
        supplier_order_id=10,
        status="preparing",
        supplier_tracking_number="CJ-111",
        supplier_carrier="DHL",
        supplier_tracking_url="https://example.test/CJ-111",
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    row2 = SimpleNamespace(
        supplier_order_id=11,
        status="in_transit",
        supplier_tracking_number=None,
        supplier_carrier=None,
        supplier_tracking_url=None,
        customer_carrier="Почта России",
        customer_tracking_number="CJ-222",
        customer_tracking_url="https://pochta.test/CJ-222",
    )
    cards = build_admin_shipment_cards([row1, row2], [so1, so2])
    assert [card.seq for card in cards] == [1, 2]
    assert cards[0].tp_id == "TP-111"
    assert cards[0].supplier_tracking_number == "CJ-111"
    assert cards[0].status_label == "Готовится"
    assert cards[0].supplier_carrier == "DHL"
    assert cards[0].dhl_tracking_url == build_dhl_public_tracking_url("CJ-111")
    assert cards[0].pochta_tracking_url == build_pochta_public_tracking_url("CJ-111")
    assert cards[1].dhl_tracking_url == build_dhl_public_tracking_url("CJ-222")
    assert cards[1].pochta_tracking_url == build_pochta_public_tracking_url("CJ-222")
    assert cards[1].tp_id == "TP-222"
    assert cards[1].supplier_tracking_number is None
    assert cards[1].status_label == "В пути"
    assert admin_shipment_summary(cards) == "0 / 2 доставлены"


def test_admin_shipment_card_tracking_links_prefer_supplier_cj() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    row = SimpleNamespace(
        supplier_order_id=1,
        status="in_transit",
        supplier_tracking_number="CJ111",
        supplier_carrier="DHL",
        supplier_tracking_url=None,
        customer_carrier="Почта России",
        customer_tracking_number="CJ222",
        customer_tracking_url=None,
    )
    card = build_admin_shipment_cards([row], [so])[0]
    assert card.dhl_tracking_url == build_dhl_public_tracking_url("CJ111")
    assert card.pochta_tracking_url == build_pochta_public_tracking_url("CJ111")


def test_admin_shipment_card_tracking_links_fallback_to_customer_number() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    row = SimpleNamespace(
        supplier_order_id=1,
        status="in_transit",
        supplier_tracking_number=None,
        supplier_carrier=None,
        supplier_tracking_url=None,
        customer_carrier="Почта России",
        customer_tracking_number="CJ222",
        customer_tracking_url="https://pochta.test/CJ-222",
    )
    card = build_admin_shipment_cards([row], [so])[0]
    assert card.dhl_tracking_url == build_dhl_public_tracking_url("CJ222")
    assert card.pochta_tracking_url == build_pochta_public_tracking_url("CJ222")


def test_admin_shipment_card_tracking_links_empty_without_numbers() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    row = SimpleNamespace(
        supplier_order_id=1,
        status="preparing",
        supplier_tracking_number=None,
        supplier_carrier=None,
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    card = build_admin_shipment_cards([row], [so])[0]
    assert card.dhl_tracking_url is None
    assert card.pochta_tracking_url is None


def test_admin_shipment_cards_ignore_order_legacy_fields() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-SO")
    row = SimpleNamespace(
        supplier_order_id=1,
        status="delivered",
        supplier_tracking_number="CJ-SO",
        supplier_carrier="DHL",
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    cards = build_admin_shipment_cards([row], [so])
    assert cards[0].tp_id != "TP-ORDER"
    assert cards[0].supplier_tracking_number != "CJ-ORDER"
    assert admin_shipment_summary(cards) == "Все посылки доставлены"


# Public DHL URL is customer-safe and encodes the CJ.
def test_build_dhl_public_tracking_url() -> None:
    url = build_dhl_public_tracking_url("CJ688018359DE")
    assert url.startswith(
        "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html"
    )
    assert url.endswith("piececode=CJ688018359DE")


# Exact customer-safe pair from one Shipment CJ.
def test_customer_tracking_links_exact_urls_for_cj() -> None:
    cj = "CJ688018359DE"
    links = customer_tracking_links_for_cj(cj)
    assert [row.carrier for row in links] == ["DHL", "Pochta"]
    assert links[0].url == (
        "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html"
        f"?piececode={cj}"
    )
    assert links[1].url == f"https://www.pochta.ru/tracking?barcode={cj}"


# Links появляются только при CJ; без CJ список пустой.
def test_customer_tracking_links_for_cj_empty_without_number() -> None:
    assert customer_tracking_links_for_cj(None) == []
    assert customer_tracking_links_for_cj("  ") == []


# Два Shipment с разными CJ не смешивают URL.
def test_build_order_shipment_schemas_links_and_items_stay_per_shipment() -> None:
    row_a = SimpleNamespace(
        id=1,
        supplier_order_id=10,
        status="preparing",
        status_updated_at=None,
        delivered_at=None,
        supplier_carrier="DHL",
        supplier_tracking_number="CJ-1",
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    row_b = SimpleNamespace(
        id=2,
        supplier_order_id=11,
        status="in_transit",
        status_updated_at=None,
        delivered_at=None,
        supplier_carrier="DHL",
        supplier_tracking_number="CJ-2",
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    row_empty = SimpleNamespace(
        id=3,
        supplier_order_id=12,
        status="preparing",
        status_updated_at=None,
        delivered_at=None,
        supplier_carrier=None,
        supplier_tracking_number=None,
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
    )
    item_a = SimpleNamespace(
        id=101,
        product_title="Racket A",
        product_title_captured=None,
        product_image_url=None,
        variant_option1=None,
        variant_option1_captured=None,
        variant_option2=None,
        variant_option2_captured=None,
        variant_option3=None,
        variant_option3_captured=None,
    )
    item_b = SimpleNamespace(
        id=102,
        product_title="Bag B",
        product_title_captured=None,
        product_image_url=None,
        variant_option1=None,
        variant_option1_captured=None,
        variant_option2=None,
        variant_option2_captured=None,
        variant_option3=None,
        variant_option3_captured=None,
    )
    line_a = SimpleNamespace(order_item_id=101, quantity=1)
    line_b = SimpleNamespace(order_item_id=102, quantity=2)
    schemas = build_order_shipment_schemas(
        [row_a, row_b, row_empty],
        {10: [line_a], 11: [line_b], 12: []},
        [item_a, item_b],
    )
    assert [row.seq for row in schemas] == [1, 2, 3]
    first, second, third = schemas
    assert [link.carrier for link in first.customer_tracking.links] == ["DHL", "Pochta"]
    assert first.customer_tracking.links[0].url == build_dhl_public_tracking_url("CJ-1")
    assert first.customer_tracking.links[1].url == build_pochta_public_tracking_url(
        "CJ-1"
    )
    assert "CJ-2" not in first.customer_tracking.links[0].url
    assert "CJ-2" not in first.customer_tracking.links[1].url
    assert second.customer_tracking.links[0].url == build_dhl_public_tracking_url(
        "CJ-2"
    )
    assert second.customer_tracking.links[1].url == build_pochta_public_tracking_url(
        "CJ-2"
    )
    assert "CJ-1" not in second.customer_tracking.links[0].url
    assert third.customer_tracking.links == []
    assert first.supplier_tracking.links == []
    assert [item.product_title for item in first.items] == ["Racket A"]
    assert [item.product_title for item in second.items] == ["Bag B"]
    assert first.items[0].quantity == 1
    assert second.items[0].quantity == 2
    assert third.items == []


# Один placed SO → один TP; draft/cancelled не попадают в список.
def test_admin_list_tp_ids_one_placed_ignores_draft_and_cancelled() -> None:
    headers = [
        SimpleNamespace(status=SupplierOrderStatus.PLACED, external_id="TP-2844177"),
        SimpleNamespace(status=SupplierOrderStatus.DRAFT, external_id=None),
        SimpleNamespace(
            status=SupplierOrderStatus.CANCELLED, external_id="TP-CANCELLED"
        ),
    ]
    assert admin_list_tp_ids(headers, "TP-LEGACY") == ["TP-2844177"]


# Четыре placed SO → все TP по seq, legacy mirror не подменяет список.
def test_admin_list_tp_ids_four_placed_ignores_legacy_mirror() -> None:
    headers = [
        SimpleNamespace(status=SupplierOrderStatus.PLACED, external_id="TP-2844177"),
        SimpleNamespace(status=SupplierOrderStatus.PLACED, external_id="TP-2864053"),
        SimpleNamespace(status=SupplierOrderStatus.PLACED, external_id="TP-2864070"),
        SimpleNamespace(status=SupplierOrderStatus.PLACED, external_id="TP-2877832"),
    ]
    assert admin_list_tp_ids(headers, "TP-2844177") == [
        "TP-2844177",
        "TP-2864053",
        "TP-2864070",
        "TP-2877832",
    ]


# Нет SO → колонка берёт Order.supplier_order_id.
def test_admin_list_tp_ids_legacy_without_so() -> None:
    assert admin_list_tp_ids([], "TP-LEGACY") == ["TP-LEGACY"]
    assert admin_list_tp_ids([], "  ") == []


# Batch-map покрывает каждый заказ страницы, в том числе без SO.
def test_build_admin_list_tp_by_order_id_covers_page_orders() -> None:
    headers = [
        SimpleNamespace(
            order_id=10,
            status=SupplierOrderStatus.PLACED,
            external_id="TP-A",
        ),
        SimpleNamespace(
            order_id=10,
            status=SupplierOrderStatus.DRAFT,
            external_id=None,
        ),
        SimpleNamespace(
            order_id=11,
            status=SupplierOrderStatus.PLACED,
            external_id="TP-B1",
        ),
        SimpleNamespace(
            order_id=11,
            status=SupplierOrderStatus.PLACED,
            external_id="TP-B2",
        ),
    ]
    orders = [
        SimpleNamespace(id=10, supplier_order_id="TP-A"),
        SimpleNamespace(id=11, supplier_order_id="TP-B1"),
        SimpleNamespace(id=12, supplier_order_id="TP-LEGACY"),
    ]
    mapping = build_admin_list_tp_by_order_id(headers, orders)
    assert mapping[10] == ["TP-A"]
    assert mapping[11] == ["TP-B1", "TP-B2"]
    assert mapping[12] == ["TP-LEGACY"]


# Одна посылка: TP с SO, CJ с Shipment.
def test_build_admin_supplier_parcels_one_pair() -> None:
    so = SimpleNamespace(
        id=1,
        seq=1,
        status=SupplierOrderStatus.PLACED,
        external_id="TP-1",
    )
    row = SimpleNamespace(supplier_order_id=1, supplier_tracking_number="CJ-1")
    parcels = build_admin_supplier_parcels([so], [row], "TP-LEGACY", "CJ-LEGACY")
    assert len(parcels) == 1
    assert parcels[0].tp_id == "TP-1"
    assert parcels[0].supplier_tracking_number == "CJ-1"
    assert parcels[0].awaiting_tracking is False


# Четыре пары, CJ не смешиваются, порядок seq.
def test_build_admin_supplier_parcels_four_pairs_keep_cj() -> None:
    headers = [
        SimpleNamespace(
            id=10, seq=1, status=SupplierOrderStatus.PLACED, external_id="TP-2844177"
        ),
        SimpleNamespace(
            id=11, seq=2, status=SupplierOrderStatus.PLACED, external_id="TP-2864053"
        ),
        SimpleNamespace(
            id=12, seq=3, status=SupplierOrderStatus.PLACED, external_id="TP-2864070"
        ),
        SimpleNamespace(
            id=13, seq=4, status=SupplierOrderStatus.PLACED, external_id="TP-2877832"
        ),
        SimpleNamespace(
            id=14, seq=5, status=SupplierOrderStatus.CANCELLED, external_id="TP-SKIP"
        ),
    ]
    rows = [
        SimpleNamespace(supplier_order_id=10, supplier_tracking_number="CJ688018359DE"),
        SimpleNamespace(supplier_order_id=11, supplier_tracking_number="CJ688082618DE"),
        SimpleNamespace(supplier_order_id=12, supplier_tracking_number="CJ688083128DE"),
        SimpleNamespace(supplier_order_id=13, supplier_tracking_number="CJ688146874DE"),
    ]
    parcels = build_admin_supplier_parcels(headers, rows, "TP-2844177", "CJ688018359DE")
    assert [(p.seq, p.tp_id, p.supplier_tracking_number) for p in parcels] == [
        (1, "TP-2844177", "CJ688018359DE"),
        (2, "TP-2864053", "CJ688082618DE"),
        (3, "TP-2864070", "CJ688083128DE"),
        (4, "TP-2877832", "CJ688146874DE"),
    ]


# Shipment без CJ: TP остаётся, номер не берётся с Order.
def test_build_admin_supplier_parcels_missing_cj() -> None:
    so = SimpleNamespace(
        id=1,
        seq=1,
        status=SupplierOrderStatus.PLACED,
        external_id="TP-1",
    )
    row = SimpleNamespace(supplier_order_id=1, supplier_tracking_number=None)
    parcels = build_admin_supplier_parcels([so], [row], "TP-1", "CJ-LEGACY")
    assert parcels[0].tp_id == "TP-1"
    assert parcels[0].supplier_tracking_number is None
    assert parcels[0].awaiting_tracking is True


# Нет SO/Shipment → старые поля заказа.
def test_build_admin_supplier_parcels_legacy_without_so() -> None:
    parcels = build_admin_supplier_parcels([], [], "TP-LEGACY", "CJ-LEGACY")
    assert len(parcels) == 1
    assert parcels[0].tp_id == "TP-LEGACY"
    assert parcels[0].supplier_tracking_number == "CJ-LEGACY"
    assert parcels[0].awaiting_tracking is False


# Пустой заказ не считается all delivered — auto-complete не должен срабатывать.
def test_all_shipments_delivered_empty_is_false() -> None:
    assert all_shipments_delivered([]) is False


# Mixed statuses: ещё не все доставлены.
def test_all_shipments_delivered_mixed_is_false() -> None:
    rows = [
        SimpleNamespace(status="delivered"),
        SimpleNamespace(status="in_transit"),
    ]
    assert all_shipments_delivered(rows) is False


# Все посылки в terminal delivered.
def test_all_shipments_delivered_all_true() -> None:
    rows = [
        SimpleNamespace(status="delivered"),
        SimpleNamespace(status="delivered"),
    ]
    assert all_shipments_delivered(rows) is True


# Карточка: delivered_at и индикатор A без message_id.
def test_admin_shipment_card_telegram_and_delivered_at() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    row = SimpleNamespace(
        supplier_order_id=1,
        status="delivered",
        supplier_tracking_number="CJ-1",
        supplier_carrier="DHL",
        supplier_tracking_url=None,
        customer_carrier=None,
        customer_tracking_number=None,
        customer_tracking_url=None,
        delivered_at=datetime(2026, 9, 10, 13, 44, 28),
        status_updated_at=datetime(2026, 9, 10, 13, 44, 28),
        delivered_alert={"message_id": 11, "pending_retry": False},
    )
    card = build_admin_shipment_cards([row], [so])[0]
    assert card.telegram_label == SHIPMENT_TELEGRAM_SENT_MARK
    assert card.delivered_at_display
    assert card.last_check_display


# True если есть хотя бы одна посылка и все с admin completed_at.
def test_all_shipments_completed_empty_is_false() -> None:
    assert all_shipments_completed([]) is False


def test_all_shipments_completed_mixed_is_false() -> None:
    now = datetime(2026, 9, 11, 8, 0, 0)
    rows = [
        SimpleNamespace(completed_at=now),
        SimpleNamespace(completed_at=None),
    ]
    assert all_shipments_completed(rows) is False


def test_all_shipments_completed_all_true() -> None:
    now = datetime(2026, 9, 11, 8, 0, 0)
    rows = [
        SimpleNamespace(completed_at=now),
        SimpleNamespace(completed_at=now),
    ]
    assert all_shipments_completed(rows) is True


# Tracking delivered не равен admin completed.
def test_delivered_is_not_completed() -> None:
    row = SimpleNamespace(status="delivered", completed_at=None)
    assert all_shipments_delivered([row]) is True
    assert all_shipments_completed([row]) is False


def test_mark_shipment_completed_sets_timestamp_only() -> None:
    now = datetime(2026, 9, 11, 8, 0, 0)
    alert = {"message_id": 7}
    row = SimpleNamespace(
        status="delivered",
        delivered_alert=alert,
        completed_at=None,
    )
    assert mark_shipment_completed(row, now) is True
    assert row.completed_at == now
    assert row.status == "delivered"
    assert row.delivered_alert is alert


def test_mark_shipment_completed_repeat_is_noop() -> None:
    first = datetime(2026, 9, 11, 8, 0, 0)
    later = datetime(2026, 9, 11, 9, 0, 0)
    row = SimpleNamespace(
        status="delivered",
        delivered_alert={"pending_retry": True},
        completed_at=None,
    )
    assert mark_shipment_completed(row, first) is True
    assert mark_shipment_completed(row, later) is False
    assert row.completed_at == first
    assert row.delivered_alert == {"pending_retry": True}


def test_complete_one_of_two_does_not_complete_other() -> None:
    now = datetime(2026, 9, 11, 8, 0, 0)
    first = SimpleNamespace(completed_at=None, status="delivered")
    second = SimpleNamespace(completed_at=None, status="delivered")
    assert mark_shipment_completed(first, now) is True
    assert first.completed_at == now
    assert second.completed_at is None
    assert all_shipments_completed([first, second]) is False
    assert mark_shipment_completed(second, now) is True
    assert all_shipments_completed([first, second]) is True


def _shipment_service_with_row(row: object) -> ShipmentService:
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    service = ShipmentService(session)
    service.order_crud.get_shipment_by_id_for_update = AsyncMock(return_value=row)
    return service


def _locked_shipment(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 10,
        "order_id": 188,
        "status": "delivered",
        "delivered_at": datetime(2026, 9, 10, 13, 44, 28),
        "delivered_alert": {"message_id": 7},
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_complete_shipment_sets_completed_at() -> None:
    now = datetime(2026, 9, 11, 8, 0, 0)
    row = _locked_shipment()
    service = _shipment_service_with_row(row)
    with patch("src.services.orders.shipments.utc_now_naive", return_value=now):
        result = await service.complete_shipment(10, 188)
    assert result is row
    assert row.completed_at == now
    assert row.status == "delivered"
    service.order_crud.get_shipment_by_id_for_update.assert_awaited_once_with(10)
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_shipment_repeat_keeps_first_timestamp() -> None:
    first = datetime(2026, 9, 11, 8, 0, 0)
    later = datetime(2026, 9, 11, 9, 0, 0)
    row = _locked_shipment()
    service = _shipment_service_with_row(row)
    with patch("src.services.orders.shipments.utc_now_naive", return_value=first):
        await service.complete_shipment(10, 188)
    with patch("src.services.orders.shipments.utc_now_naive", return_value=later):
        await service.complete_shipment(10, 188)
    assert row.completed_at == first
    assert row.status == "delivered"
    assert row.delivered_alert == {"message_id": 7}
    assert service.order_crud.get_shipment_by_id_for_update.await_count == 2
    assert service.session.commit.await_count == 2


@pytest.mark.asyncio
async def test_complete_shipment_missing_raises() -> None:
    service = _shipment_service_with_row(None)
    with pytest.raises(ShipmentError, match="не найдена"):
        await service.complete_shipment(99, 188)
    service.order_crud.get_shipment_by_id_for_update.assert_awaited_once_with(99)
    service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_shipment_rejects_wrong_order_under_lock() -> None:
    row = _locked_shipment(order_id=186)
    service = _shipment_service_with_row(row)
    with pytest.raises(ShipmentError, match="не найдена"):
        await service.complete_shipment(10, 188)
    service.order_crud.get_shipment_by_id_for_update.assert_awaited_once_with(10)
    assert row.completed_at is None
    service.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_shipment_rejects_undelivered_under_lock() -> None:
    row = _locked_shipment(status="in_transit", delivered_at=None)
    service = _shipment_service_with_row(row)
    with pytest.raises(ShipmentError, match="доставленную"):
        await service.complete_shipment(10, 188)
    service.order_crud.get_shipment_by_id_for_update.assert_awaited_once_with(10)
    assert row.completed_at is None
    assert row.status == "in_transit"
    service.session.commit.assert_not_awaited()


def _admin_card_row(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 10,
        "order_id": 188,
        "supplier_order_id": 1,
        "status": "delivered",
        "supplier_tracking_number": "CJ-1",
        "supplier_carrier": "DHL",
        "supplier_tracking_url": None,
        "customer_carrier": None,
        "customer_tracking_number": None,
        "customer_tracking_url": None,
        "delivered_at": datetime(2026, 9, 10, 13, 44, 28),
        "status_updated_at": datetime(2026, 9, 10, 13, 44, 28),
        "delivered_alert": {"message_id": 11, "pending_retry": False},
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_admin_card_completed_state_hides_complete_action() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    completed_at = datetime(2026, 9, 11, 8, 0, 0)
    card = build_admin_shipment_cards(
        [_admin_card_row(id=10, completed_at=completed_at)],
        [so],
    )[0]
    assert card.id == 10
    assert card.status == "delivered"
    assert card.is_completed is True
    assert card.can_complete is False
    assert card.completion_label == "Завершена"
    assert card.completed_at_display
    assert card.telegram_label == SHIPMENT_TELEGRAM_SENT_MARK


def test_admin_card_delivered_not_completed_shows_complete_action() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    card = build_admin_shipment_cards([_admin_card_row(id=11)], [so])[0]
    assert card.status == "delivered"
    assert card.is_completed is False
    assert card.can_complete is True
    assert card.completion_label == "Не завершена"
    assert card.completed_at_display is None


def test_admin_card_in_transit_cannot_complete() -> None:
    so = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    card = build_admin_shipment_cards(
        [_admin_card_row(id=12, status="in_transit", delivered_at=None)],
        [so],
    )[0]
    assert card.can_complete is False
    assert card.is_completed is False


def test_admin_completion_summary_and_neighbor_isolation() -> None:
    so1 = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    so2 = SimpleNamespace(id=2, seq=2, external_id="TP-2")
    cards = build_admin_shipment_cards(
        [
            _admin_card_row(
                id=10,
                supplier_order_id=1,
                completed_at=datetime(2026, 9, 11, 8, 0, 0),
            ),
            _admin_card_row(
                id=11,
                supplier_order_id=2,
                supplier_tracking_number="CJ-2",
                completed_at=None,
            ),
        ],
        [so1, so2],
    )
    assert cards[0].is_completed is True
    assert cards[0].can_complete is False
    assert cards[1].is_completed is False
    assert cards[1].can_complete is True
    assert admin_shipment_completion_summary(cards) == "1 из 2 посылок завершены"
    assert admin_shipment_summary(cards) == "Все посылки доставлены"


def test_ensure_admin_shipment_completable_rejects_wrong_order() -> None:
    view = SimpleNamespace(order_id=188, status="delivered", completed_at=None)
    with pytest.raises(ShipmentError, match="не найдена"):
        ensure_admin_shipment_completable(view, 186)


def test_ensure_admin_shipment_completable_rejects_undelivered() -> None:
    view = SimpleNamespace(order_id=188, status="in_transit", completed_at=None)
    with pytest.raises(ShipmentError, match="доставленную"):
        ensure_admin_shipment_completable(view, 188)


def test_ensure_admin_shipment_completable_allows_repeat() -> None:
    view = SimpleNamespace(
        order_id=188,
        status="delivered",
        completed_at=datetime(2026, 9, 11, 8, 0, 0),
    )
    ensure_admin_shipment_completable(view, 188)


def test_shipment_can_notify_delivered_or_completed() -> None:
    assert shipment_can_notify_customer(
        SimpleNamespace(status="delivered", completed_at=None)
    )
    assert shipment_can_notify_customer(
        SimpleNamespace(
            status="in_transit", completed_at=datetime(2026, 9, 11, 8, 0, 0)
        )
    )
    assert not shipment_can_notify_customer(
        SimpleNamespace(status="in_transit", completed_at=None)
    )


def test_render_shipment_customer_message_placeholders() -> None:
    text = render_shipment_customer_message(
        "Заказ #{order_id} · Посылка №{seq}\n{cj}",
        188,
        2,
        "CJ-2",
    )
    assert "188" in text
    assert "№2" in text
    assert "CJ-2" in text


def test_ensure_identity_appended_when_no_placeholders() -> None:
    rendered = ensure_shipment_identity_in_message(
        "Заказ доставлен",
        "Заказ доставлен",
        2,
        "CJ-2",
    )
    assert "Посылка №2" in rendered
    assert "CJ-2" in rendered


def test_customer_notify_label_and_card_state() -> None:
    so1 = SimpleNamespace(id=1, seq=1, external_id="TP-1")
    so2 = SimpleNamespace(id=2, seq=2, external_id="TP-2")
    cards = build_admin_shipment_cards(
        [
            _admin_card_row(
                id=10, supplier_order_id=1, status="in_transit", delivered_at=None
            ),
            _admin_card_row(
                id=11, supplier_order_id=2, supplier_tracking_number="CJ-2"
            ),
        ],
        [so1, so2],
    )
    assert cards[0].can_notify is False
    assert cards[1].can_notify is True
    assert cards[1].customer_notify_label == SHIPMENT_TELEGRAM_IDLE_MARK
    assert cards[1].customer_notify_draft == (
        "По заказу 📦 #188 · Посылка №2 доставлена."
    )
    labeled = apply_customer_notify_state(
        cards,
        188,
        {"customer:order_status:order:188:shipment:11:event:delivered": "sent"},
    )
    assert labeled[0].customer_notify_label == SHIPMENT_TELEGRAM_IDLE_MARK
    assert labeled[1].customer_notify_label == SHIPMENT_TELEGRAM_SENT_MARK
    labeled_tg = apply_customer_notify_state(
        cards,
        188,
        {
            "customer:order_status:order:188:shipment:11:event:delivered:telegram": (
                "sent"
            )
        },
    )
    assert labeled_tg[1].customer_notify_label == SHIPMENT_TELEGRAM_SENT_MARK
    labeled_event = apply_customer_notify_state(
        cards,
        188,
        {},
        [
            {
                "event_type": "customer_notified",
                "payload_json": {
                    "idempotency_key": (
                        "customer:order_status:order:188:"
                        "shipment:11:event:delivered:telegram"
                    )
                },
            }
        ],
    )
    assert labeled_event[1].customer_notify_label == SHIPMENT_TELEGRAM_SENT_MARK
    assert customer_notify_label_for_outbox("failed") == "⚠ Ошибка"
