from types import SimpleNamespace

from src.services.notifications.customer_notification_keys import (
    payment_received_key,
    shipment_delivered_notify_key,
)
from src.web.admin_order_events import build_order_journey
from tests.fixtures.order_40_journey import (
    ORDER_40_CUSTOMER_NOTIFIED_EVENTS,
    ORDER_40_ORDER,
)
from tests.fixtures.supplier_tracking_demo import build_full_dhl_tracking_json


def _order(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 1,
        "status": "created",
        "availability_confirmation_status": "confirmed",
        "payment_state": "paid",
        "supplier_order_id": None,
        "supplier_tracking_id": None,
        "supplier_tracking_json": None,
        "notification_channels": ["telegram"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_order_journey_points_to_assembly_after_payment() -> None:
    journey = build_order_journey(_order(), [])

    states = [stage["state"] for stage in journey["stages"]]
    assert states == ["done", "done", "done", "current", "pending"]


def test_order_journey_shows_email_badge_after_email_customer_notified() -> None:
    order = _order(
        notification_channels=["email"],
        status="assembling",
        supplier_order_id="SUP-99",
        payment_state="paid",
    )
    journey = build_order_journey(
        order,
        [
            {
                "event_type": "customer_notified",
                "payload_json": {
                    "message": "Заказ #1 передан в сборку.",
                    "template": "order_status",
                    "idempotency_key": "customer:assembly.notify:order:1:email",
                    "channel": "email",
                },
            },
            {"event_type": "assembly_started"},
            {"event_type": "payment_accepted"},
            {"event_type": "order_created"},
        ],
    )

    assembly = journey["stages"][3]
    assert {"channel": "EM", "state": "sent"} in assembly["notify_badges"]
    assert {"channel": "ЛК", "state": "sent"} in assembly["notify_badges"]


def test_order_journey_email_only_created_has_no_email_badge() -> None:
    journey = build_order_journey(
        _order(notification_channels=["email"], payment_state="not_started"),
        [{"event_type": "order_created"}],
    )

    created = journey["stages"][0]
    assert created["notify_badges"] == [{"channel": "ЛК", "state": "sent"}]


def test_order_journey_dual_channel_payment_tg_waiting_when_only_email_sent() -> None:
    journey = build_order_journey(
        _order(
            notification_channels=["telegram", "email"],
            payment_state="paid",
        ),
        [
            {
                "event_type": "customer_notified",
                "payload_json": {
                    "message": "Оплата получена",
                    "template": "payment.received",
                    "idempotency_key": "customer:payment.received:order:1:email",
                    "channel": "email",
                },
            },
            {"event_type": "payment_accepted"},
            {"event_type": "order_created"},
        ],
    )

    payment = journey["stages"][2]
    assert {"channel": "TG", "state": "waiting"} in payment["notify_badges"]
    assert {"channel": "EM", "state": "sent"} in payment["notify_badges"]


def test_order_journey_shows_email_badge_from_email_outbox() -> None:
    order = _order(notification_channels=["email"], payment_state="paid")
    journey = build_order_journey(
        order,
        [],
        outbox_by_key={
            f"{payment_received_key(order.id)}:email": "sent",
        },
    )

    payment = journey["stages"][2]
    assert {"channel": "EM", "state": "sent"} in payment["notify_badges"]


def test_order_journey_marks_delivery_from_supplier_tracking() -> None:
    journey = build_order_journey(
        _order(
            status="delivery",
            supplier_order_id="SUP-42",
            supplier_tracking_id="TRACK-7",
        ),
        [
            {
                "event_type": "customer_notified",
                "created_at_display": "06.07.2026 17:10",
            }
        ],
    )

    stages = journey["stages"]
    assert stages[3]["state"] == "done"
    assert stages[4]["state"] == "current"
    assert stages[4]["facts"] == ["TRACK-7"]
    assert stages[4]["subtitle"] == "в пути · DHL"
    assert journey["customer_notification_count"] == 1
    assert journey["carrier_timeline"] == []


def test_order_journey_keeps_carrier_timeline_for_shipment_card() -> None:
    journey = build_order_journey(
        _order(
            status="delivery",
            supplier_order_id="TP-2684032",
            supplier_tracking_id="CJ687378245DE",
        ),
        [],
        tracking_json=build_full_dhl_tracking_json(),
    )

    delivery = journey["stages"][4]
    assert delivery["subtitle"] == "в пути · DHL"
    assert delivery["facts"] == ["CJ687378245DE"]
    assert len(journey["carrier_timeline"]) == 6
    assert journey["carrier_timeline"][0]["title"] == "Передан местной службе доставки"
    assert journey["carrier_timeline"][-1]["title"] == "Поставщик готовит отправление"


def test_order_journey_marks_terminal_failure() -> None:
    journey = build_order_journey(
        _order(
            status="cancelled",
            availability_confirmation_status="pending",
            payment_state="not_started",
        ),
        [],
    )

    assert journey["stages"][1]["state"] == "error"


def test_order_journey_shows_processing_until_availability_is_resolved() -> None:
    journey = build_order_journey(
        _order(
            status="processing",
            availability_confirmation_status="pending",
            payment_state="not_started",
        ),
        [],
    )

    first, availability = journey["stages"][:2]
    assert first["title"] == "Клиент"
    assert first["subtitle"] == "оформил"
    assert first["state"] == "done"
    assert first["facts"] == []
    assert first["notifications"][0] == "Клиент: TG — · ЛК ✓"
    assert availability["title"] == "Наличие"
    assert availability["subtitle"] == "ожидает проверки"
    assert availability["state"] == "current"
    assert availability["facts"] == ["Ожидает решения админа"]
    assert {"channel": "ЛК", "state": "sent"} in availability["notify_badges"]


def test_order_journey_shows_created_when_availability_is_not_required() -> None:
    journey = build_order_journey(
        _order(
            status="created",
            availability_confirmation_status="not_required",
            payment_state="not_started",
        ),
        [],
    )

    first, availability, payment = journey["stages"][:3]
    assert first["title"] == "Клиент"
    assert first["subtitle"] == "оформил"
    assert availability["title"] == "Наличие"
    assert availability["subtitle"] == "не требуется"
    assert availability["facts"] == ["Проверка не требуется"]
    assert payment["state"] == "current"


def test_order_journey_shows_availability_confirmed_by_admin() -> None:
    journey = build_order_journey(
        _order(
            status="created",
            availability_confirmation_status="confirmed",
            payment_state="not_started",
        ),
        [
            {
                "event_type": "availability_confirmed",
                "created_by": "Roman · @admin_user",
                "created_at_display": "06.07.2026 18:49",
            }
        ],
    )

    availability = journey["stages"][1]
    assert availability["facts"] == [
        "Roman · @admin_user",
    ]
    assert availability["date"] == "06.07.2026 18:49"


def test_order_journey_shows_availability_confirmed_by_stock_check() -> None:
    journey = build_order_journey(
        _order(
            status="created",
            availability_confirmation_status="confirmed",
            payment_state="not_started",
        ),
        [
            {
                "event_type": "availability_stock_check_saved",
                "created_by": "Anna · @stock_admin",
                "created_at_display": "06.07.2026 19:05",
            }
        ],
    )

    availability = journey["stages"][1]
    assert availability["facts"] == ["Anna · @stock_admin"]
    assert availability["date"] == "06.07.2026 19:05"


def test_order_journey_shows_notification_lines_on_completed_steps() -> None:
    journey = build_order_journey(
        _order(
            status="assembling",
            availability_confirmation_status="confirmed",
            payment_state="paid",
            supplier_order_id="SUP-1",
        ),
        [
            {
                "event_type": "customer_notified",
                "message": "Заказ #1 изменён.",
                "payload_json": {
                    "message": "Заказ #1 изменён.",
                    "template": "composition.changed",
                },
                "created_at_display": "06.07.2026 17:11",
            },
            {
                "event_type": "order_items_edited",
                "created_at_display": "06.07.2026 17:11",
            },
            {
                "event_type": "payment_accepted",
                "created_at_display": "06.07.2026 17:10",
            },
            {
                "event_type": "customer_notified",
                "payload_json": {
                    "message": "Оплата получена",
                    "template": "payment.received",
                    "idempotency_key": "customer:payment.received:order:1",
                },
            },
            {
                "event_type": "customer_notified",
                "message": "Заказ #1: наличие подтверждено. Можно оплатить.",
                "payload_json": {
                    "message": "Заказ #1: наличие подтверждено. Можно оплатить.",
                    "template": "order_status",
                    "idempotency_key": "customer:availability.notify:order:1",
                },
                "created_at_display": "06.07.2026 16:58",
            },
            {
                "event_type": "availability_confirmed",
                "created_at_display": "06.07.2026 16:58",
            },
            {
                "event_type": "availability_confirmation_requested",
                "created_at_display": "06.07.2026 16:56",
            },
            {"event_type": "order_created", "created_at_display": "06.07.2026 16:55"},
        ],
    )

    created, availability, payment = journey["stages"][:3]
    assert created["notifications"] == [
        "Клиент: TG — · ЛК ✓",
        "Админ: TG ✓",
    ]
    assert availability["notifications"] == [
        "Клиент: TG ✓ · ЛК ✓",
        "Админ: TG ✓",
    ]
    assert payment["notifications"] == [
        "Клиент: TG ✓ · ЛК ✓",
        "Админ: TG ✓",
        "Состав изменён: TG ✓",
    ]


def test_order_journey_shows_pending_notification_labels_on_current_step() -> None:
    journey = build_order_journey(
        _order(
            status="created",
            availability_confirmation_status="confirmed",
            payment_state="paid",
            supplier_order_id=None,
        ),
        [
            {"event_type": "order_created"},
            {"event_type": "availability_confirmed"},
            {"event_type": "payment_accepted"},
        ],
    )

    assembly = journey["stages"][3]
    assert assembly["state"] == "current"
    assert assembly["notifications"][0] == "Клиент: TG — · ЛК —"


def test_order_journey_shows_client_tg_on_assembly_after_notify() -> None:
    journey = build_order_journey(
        _order(
            status="assembling",
            availability_confirmation_status="confirmed",
            payment_state="paid",
            supplier_order_id="SUP-99",
        ),
        [
            {
                "event_type": "customer_notified",
                "message": "Заказ #1 передан в сборку.",
                "payload_json": {
                    "message": "Заказ #1 передан в сборку.",
                    "template": "order_status",
                    "idempotency_key": "customer:assembly.notify:order:1",
                },
            },
            {
                "event_type": "assembly_started",
                "created_at_display": "06.07.2026 19:30",
            },
            {"event_type": "payment_accepted"},
            {"event_type": "availability_confirmed"},
            {"event_type": "order_created"},
        ],
    )

    assembly = journey["stages"][3]
    assert assembly["state"] == "done"
    assert assembly["notifications"] == [
        "Клиент: TG ✓ · ЛК ✓",
        "Админ: TG —",
    ]


def test_order_journey_notify_badges_for_client_channels() -> None:
    journey = build_order_journey(
        _order(
            status="delivery",
            availability_confirmation_status="not_required",
            payment_state="paid",
            supplier_order_id="SUP-1",
            supplier_tracking_id="CJ123",
        ),
        [
            {"event_type": "delivery_started"},
            {"event_type": "assembly_started"},
            {"event_type": "payment_accepted"},
            {"event_type": "order_created"},
        ],
    )

    created, availability, payment, assembly, delivery = journey["stages"]
    assert created["notify_badges"] == [{"channel": "ЛК", "state": "sent"}]
    assert availability["notify_badges"] == []
    assert payment["notify_badges"] == [
        {"channel": "TG", "state": "waiting"},
        {"channel": "ЛК", "state": "sent"},
    ]
    assert assembly["notify_badges"] == [{"channel": "ЛК", "state": "sent"}]
    assert delivery["notify_badges"] == [{"channel": "ЛК", "state": "sent"}]
    assert journey["progress_percent"] == 100
    assert journey["current_index"] == 4


def test_order_journey_includes_manual_timeline() -> None:
    tracking_json = build_full_dhl_tracking_json()
    journey = build_order_journey(
        _order(status="delivery", supplier_tracking_id="CJ123"),
        [],
        tracking_json=tracking_json,
    )

    # store_timeline возвращается (даже если пустой)
    assert journey["store_timeline"] is not None
    # fixture использует source="store", а не "manual", поэтому timeline пустой
    assert len(journey["store_timeline"]) == 0


def test_order_journey_includes_store_timeline_when_manual_events_exist() -> None:
    tracking_json = {
        "store_events": [
            {
                "key": "store-manual-1",
                "at": "2026-07-08T10:00:00Z",
                "stage": "in_transit",
                "title": "В пути",
                "source": "manual",
            }
        ]
    }
    journey = build_order_journey(
        _order(status="delivery", supplier_tracking_id="CJ123"),
        [],
        tracking_json=tracking_json,
    )

    assert journey["store_timeline"] is not None
    assert len(journey["store_timeline"]) == 1
    assert journey["store_timeline"][0]["title"] == "В пути"
    assert journey["store_timeline"][0]["source"] == "manual"


def test_order_journey_order_40_dual_channel_legacy_customer_channel() -> None:
    journey = build_order_journey(
        _order(**ORDER_40_ORDER),
        ORDER_40_CUSTOMER_NOTIFIED_EVENTS,
    )

    payment = journey["stages"][2]
    assembly = journey["stages"][3]
    assert {"channel": "TG", "state": "sent"} in payment["notify_badges"]
    assert {"channel": "EM", "state": "sent"} in payment["notify_badges"]
    assert {"channel": "TG", "state": "sent"} in assembly["notify_badges"]
    assert {"channel": "EM", "state": "sent"} in assembly["notify_badges"]


# Placed SupplierOrder stub для нового flow.
def _placed_so(external_id: str) -> SimpleNamespace:
    return SimpleNamespace(status="placed", external_id=external_id)


# Shipment stub с optional CJ.
def _shipment(tracking: str | None) -> SimpleNamespace:
    return SimpleNamespace(supplier_tracking_number=tracking)


# Case A: 3 placed SO + 3 CJ, без legacy mirror.
def test_order_journey_new_flow_multi_shipment_delivery() -> None:
    journey = build_order_journey(
        _order(status="delivery", supplier_order_id=None, supplier_tracking_id=None),
        [],
        supplier_orders=[_placed_so("TP-1"), _placed_so("TP-2"), _placed_so("TP-3")],
        shipments=[
            _shipment("CJ-1"),
            _shipment("CJ-2"),
            _shipment("CJ-3"),
        ],
    )

    assembly = journey["stages"][3]
    delivery = journey["stages"][4]
    assembly_text = " ".join([assembly["subtitle"], *assembly["facts"]])
    delivery_text = " ".join([delivery["subtitle"], *delivery["facts"]])
    assert assembly["subtitle"] == "завершена"
    assert "3 из 3 посылок оформлены" in assembly["facts"]
    assert "не начата" not in assembly_text
    assert "Нужен номер поставщика" not in assembly_text
    assert delivery["state"] == "current"
    assert "ожидается" not in delivery_text
    assert "3 посылки переданы в доставку" in delivery["facts"]
    assert delivery["facts"] != ["CJ-1"]


# Case B: Shipment есть, CJ ещё нет.
def test_order_journey_new_flow_shipments_without_cj() -> None:
    journey = build_order_journey(
        _order(status="delivery", supplier_order_id=None, supplier_tracking_id=None),
        [],
        supplier_orders=[_placed_so("TP-1"), _placed_so("TP-2"), _placed_so("TP-3")],
        shipments=[_shipment(None), _shipment(None), _shipment(None)],
    )

    assembly = journey["stages"][3]
    delivery = journey["stages"][4]
    delivery_text = " ".join([delivery["subtitle"], *delivery["facts"]])
    assert assembly["subtitle"] == "завершена"
    assert "3 из 3 посылок оформлены" in assembly["facts"]
    assert "ожидается" not in delivery_text
    assert delivery["subtitle"] == "ожидаем трек-номера"
    assert "Ожидаем трек-номера для посылок" in delivery["facts"]


# Case C: legacy Order.supplier_* без SO/Shipment.
def test_order_journey_legacy_without_supplier_orders() -> None:
    journey = build_order_journey(
        _order(
            status="delivery",
            supplier_order_id="SUP-42",
            supplier_tracking_id="TRACK-7",
        ),
        [],
        supplier_orders=[],
        shipments=[],
    )

    assembly = journey["stages"][3]
    delivery = journey["stages"][4]
    assert assembly["subtitle"] == "TP оформлен"
    assert assembly["facts"] == ["SUP-42"]
    assert delivery["subtitle"] == "в пути · DHL"
    assert delivery["facts"] == ["TRACK-7"]


# Case D: часть посылок с CJ, часть без.
def test_order_journey_new_flow_partial_cj() -> None:
    journey = build_order_journey(
        _order(status="delivery", supplier_order_id=None, supplier_tracking_id=None),
        [],
        supplier_orders=[_placed_so("TP-1"), _placed_so("TP-2"), _placed_so("TP-3")],
        shipments=[_shipment("CJ-1"), _shipment("CJ-2"), _shipment(None)],
    )

    assembly = journey["stages"][3]
    delivery = journey["stages"][4]
    delivery_text = " ".join([delivery["subtitle"], *delivery["facts"]])
    assert assembly["subtitle"] == "завершена"
    assert "ожидается" not in delivery_text
    assert "2 из 3 посылок с трек-номером" in delivery["facts"]
    assert "Ожидаем трек-номера для остальных посылок" in delivery["facts"]
    assert delivery["facts"] != ["CJ-1"]
    assert "CJ-1" not in delivery["facts"]


# Mixed statuses must not collapse to «все в пути».
def test_order_journey_mixed_delivered_and_in_transit() -> None:
    journey = build_order_journey(
        _order(status="delivery", supplier_order_id=None, supplier_tracking_id=None),
        [],
        supplier_orders=[_placed_so("TP-1"), _placed_so("TP-2")],
        shipments=[
            SimpleNamespace(supplier_tracking_number="CJ-1", status="in_transit"),
            SimpleNamespace(supplier_tracking_number="CJ-2", status="delivered"),
        ],
    )
    delivery = journey["stages"][4]
    assert delivery["subtitle"] == "частично"
    assert "1 из 2 посылок доставлены" in delivery["facts"]
    assert "1 ещё в пути" in delivery["facts"]
    assert "Завершено администратором: 0 из 2" in delivery["facts"]


# Tracking delivered и admin completed — разные факты.
def test_order_journey_splits_delivered_and_admin_completed() -> None:
    journey = build_order_journey(
        _order(status="delivery", supplier_order_id=None, supplier_tracking_id=None),
        [],
        supplier_orders=[_placed_so("TP-1"), _placed_so("TP-2")],
        shipments=[
            SimpleNamespace(
                supplier_tracking_number="CJ-1",
                status="delivered",
                completed_at=None,
            ),
            SimpleNamespace(
                supplier_tracking_number="CJ-2",
                status="delivered",
                completed_at="2026-09-11T08:00:00",
            ),
        ],
    )
    delivery = journey["stages"][4]
    assert "Все 2 посылки доставлены" in delivery["facts"]
    assert "Завершено администратором: 1 из 2" in delivery["facts"]


def _b_event(order_id: int, shipment_id: int) -> dict[str, object]:
    return {
        "event_type": "customer_notified",
        "payload_json": {
            "template": "notify_order_status",
            "channel": "telegram",
            "idempotency_key": shipment_delivered_notify_key(order_id, shipment_id),
        },
    }


def test_order_journey_delivery_sees_shipment_b_key() -> None:
    journey = build_order_journey(
        _order(id=188, status="delivery"),
        [_b_event(188, 11)],
        shipments=[SimpleNamespace(id=11)],
    )
    delivery = journey["stages"][4]
    assert {"channel": "TG", "state": "sent"} in delivery["notify_badges"]


def test_order_journey_delivery_sees_multiple_shipment_b_keys() -> None:
    journey = build_order_journey(
        _order(id=188, status="delivery"),
        [_b_event(188, 11), _b_event(188, 12)],
        shipments=[SimpleNamespace(id=11), SimpleNamespace(id=12)],
    )
    delivery = journey["stages"][4]
    assert {"channel": "TG", "state": "sent"} in delivery["notify_badges"]


def test_order_journey_without_shipments_keeps_order_level_keys() -> None:
    key = payment_received_key(188)
    journey = build_order_journey(
        _order(id=188, status="delivery", payment_state="paid"),
        [
            {
                "event_type": "customer_notified",
                "payload_json": {
                    "template": "notify_order_status",
                    "channel": "telegram",
                    "idempotency_key": key,
                },
            }
        ],
        shipments=[],
    )
    payment = journey["stages"][2]
    delivery = journey["stages"][4]
    assert {"channel": "TG", "state": "sent"} in payment["notify_badges"]
    assert all(badge.get("channel") != "TG" for badge in delivery["notify_badges"])
