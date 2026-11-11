from datetime import datetime

from src.schemas.order import OrderEventSchema
from src.web.admin_order_events import format_order_event_rows


def _customer_notified_event(payload: dict[str, object]) -> OrderEventSchema:
    return OrderEventSchema(
        id=1,
        order_id=10,
        event_type="customer_notified",
        event_message="Ручное сообщение клиенту",
        created_by="admin",
        payload_json=payload,
        created_at=datetime(2026, 7, 22, 12, 0, 0),
    )


def test_format_order_event_rows_manual_notify_shows_channel_and_message() -> None:
    rows = format_order_event_rows(
        [
            _customer_notified_event(
                {
                    "manual": True,
                    "channel": "telegram",
                    "message": "Проверьте размер",
                    "template": "customer.manual",
                }
            )
        ],
        {},
        {},
    )

    assert rows[0]["message"] == "Ручное сообщение клиенту"
    assert rows[0]["changes"] == [
        {"label": "Канал", "before": "—", "after": "Telegram"},
        {"label": "Сообщение", "before": "—", "after": "Проверьте размер"},
    ]


def test_format_order_event_rows_manual_notify_email_channel() -> None:
    rows = format_order_event_rows(
        [
            _customer_notified_event(
                {
                    "manual": True,
                    "channel": "email",
                    "message": "Письмо клиенту",
                    "template": "customer.manual",
                }
            )
        ],
        {},
        {},
    )

    assert rows[0]["changes"][0] == {
        "label": "Канал",
        "before": "—",
        "after": "Email",
    }
