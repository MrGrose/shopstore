from src.content.admin_texts import admin_order_tracking_url, admin_order_url
from src.content.support_texts import admin_support_ticket_url


# Inline-кнопки «открыть заказ» для ops-уведомлений.
def build_admin_order_keyboard(
    order_id: int,
    include_tracking: bool = False,
) -> dict[str, object] | None:
    order_url = admin_order_url(order_id)
    if not order_url:
        return None
    row: list[dict[str, str]] = [{"text": "📦 Открыть заказ", "url": order_url}]
    if include_tracking:
        tracking_url = admin_order_tracking_url(order_id) or order_url
        row.append({"text": "🚚 Проверить трекинг", "url": tracking_url})
    return {"inline_keyboard": [row]}


# reply_markup для admin_orders по template.
def admin_orders_reply_markup(
    template: str,
    order_id: int,
) -> dict[str, object] | None:
    if template == "delivery.started":
        return build_admin_order_keyboard(order_id, include_tracking=True)
    return build_admin_order_keyboard(order_id)


# Inline-кнопки для admin delivered alert.
def build_admin_delivered_alert_keyboard(
    order_id: int,
) -> dict[str, object] | None:
    order_url = admin_order_url(order_id)
    if not order_url:
        return None
    tracking_url = admin_order_tracking_url(order_id) or order_url
    return {
        "inline_keyboard": [
            [
                {"text": "📦 Заказ", "url": order_url},
                {"text": "🚚 Трек", "url": tracking_url},
            ]
        ]
    }


# Кнопки PLACED delivered alert: заказ и публичный трек этого CJ.
def build_placed_delivered_alert_keyboard(
    order_id: int,
    cj: str | None,
) -> dict[str, object] | None:
    order_url = admin_order_url(order_id)
    if not order_url:
        return None
    row: list[dict[str, str]] = [{"text": "📦 Заказ", "url": order_url}]
    tracking = str(cj or "").strip()
    if tracking:
        # Inline import: cycle shipments → … → admin_keyboards → shipments.
        from src.services.orders.shipments import build_dhl_public_tracking_url

        row.append({"text": "🚚 Трек", "url": build_dhl_public_tracking_url(tracking)})
    return {"inline_keyboard": [row]}


# Inline-кнопка «открыть в админке» для ops-чата поддержки.
def build_admin_support_ticket_keyboard(
    ticket_id: int,
) -> dict[str, object] | None:
    ticket_url = admin_support_ticket_url(ticket_id)
    if not ticket_url:
        return None
    return {
        "inline_keyboard": [
            [{"text": "💬 Открыть в админке", "url": ticket_url}],
        ]
    }
