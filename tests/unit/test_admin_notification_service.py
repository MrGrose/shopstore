from decimal import Decimal

from src.content.admin_texts import (
    format_duplicate_payment_message,
    format_order_created_message,
    format_payment_accepted_message,
)
from src.services.admin_notification_service import AdminNotificationService


def test_format_payment_accepted_message_exact_text() -> None:
    text = format_payment_accepted_message(
        order_id=42,
        order_total=Decimal("3000.00"),
        admin_url="https://shop.test/internal/admin/orders?id=42",
        customer_name="Ivan Ivanov",
        payment_method_label="СБП",
    )
    assert text.splitlines() == [
        "🟢 Клиент оплатил заказ",
        "",
        "Заказ #42",
        "Клиент: Ivan Ivanov",
        "Сумма: 3\xa0000 ₽",
        "Оплата: СБП",
    ]


def test_format_payment_accepted_message_without_optional_fields() -> None:
    text = format_payment_accepted_message(
        order_id=42,
        order_total=Decimal("1500"),
        admin_url=None,
    )

    assert text.splitlines() == [
        "🟢 Клиент оплатил заказ",
        "",
        "Заказ #42",
        "Сумма: 1\xa0500 ₽",
    ]


def test_format_order_created_message_includes_supplier_eur() -> None:
    text = format_order_created_message(
        payload={
            "order": {
                "id": 42,
                "total_amount": Decimal("13800"),
                "eur_rate_snapshot": Decimal("98.50"),
                "created_at": "2026-07-04T18:30:00",
            },
            "customer_delivery": {
                "last_name": "Ivanov",
                "first_name": "Ivan",
                "phone": "+79991234567",
                "city": "Moscow",
            },
            "customer_data": {"telegram_id": 123},
            "items": [
                {
                    "product_id": 1,
                    "product_title": "Nike Air Zoom",
                    "variant_sku": "NIKE-123",
                    "option1": "42",
                    "quantity": 1,
                    "unit_price": Decimal("12500"),
                    "supplier_price_eur": Decimal("89.99"),
                },
            ],
        },
        user_email="test@example.com",
        promo_code_applied="SUMMER",
    )
    assert "👤 Клиент" in text
    assert "📍 Доставка" in text
    delivery_block = text.split("📍 Доставка", 1)[1].split("🛒 Товары", 1)[0]
    assert "+7 999 123-45-67" in delivery_block
    assert "🛒 Товары" in text
    assert "💰 Итого" in text
    assert "закуп 89,99 €" in text
    assert "1. Nike Air Zoom, 42" in text
    assert "- 1 x 12 500" in text.replace("\u00a0", " ")
    assert "Промокод: SUMMER" in text
    assert "Курс EUR: 98,50" in text
    assert "Сумма: 13 800 ₽" in text.replace("\u00a0", " ")
    assert "04.07.2026" not in text


def test_late_payment_uses_same_helper_as_admin_service() -> None:
    assert (
        AdminNotificationService.send_late_payment_after_auto_cancel.__name__
        == "send_late_payment_after_auto_cancel"
    )


def test_format_duplicate_payment_message_exact_text() -> None:
    text = format_duplicate_payment_message(
        order_id=42,
        order_total=Decimal("3000.00"),
        attempt_number=2,
        admin_url="https://shop.test/internal/admin/orders?id=42",
    )
    assert text.splitlines() == [
        "Заказ #42 · 🚨 Повторная оплата",
        "",
        "Сумма: 3000.00 ₽ · попытка #2",
        "Нужна немедленная проверка и возврат/зачёт.",
    ]


def test_send_payment_duplicate_method_exists() -> None:
    assert (
        AdminNotificationService.send_payment_duplicate.__name__
        == "send_payment_duplicate"
    )
