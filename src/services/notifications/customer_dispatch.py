from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
)

_ORDER_NOTIFICATION_CHANNELS = frozenset({"telegram", "email"})


# Возвращает сохранённые каналы заказа или legacy fallback на Telegram.
def resolve_order_notification_channels(order: object | None) -> list[str]:
    if order is None:
        return ["telegram"]
    raw = getattr(order, "notification_channels", None) or []
    channels = [str(item).strip().lower() for item in raw if str(item).strip()]
    if not channels:
        return ["telegram"]
    return channels


# Перенаправляет CUSTOMER dispatch на один принудительный канал.
def apply_forced_channel(
    dispatch: NotificationDispatch,
    forced_channel: str,
) -> NotificationDispatch:
    if forced_channel not in _ORDER_NOTIFICATION_CHANNELS:
        return dispatch
    return NotificationDispatch(
        channel=(
            NotificationChannel.EMAIL
            if forced_channel == "email"
            else NotificationChannel.CUSTOMER
        ),
        template=dispatch.template,
        payload=dispatch.payload,
        created_by=dispatch.created_by,
        idempotency_key=dispatch.idempotency_key,
        skip_if_order_event=dispatch.skip_if_order_event,
        record_order_event=dispatch.record_order_event,
    )


# Разворачивает CUSTOMER dispatch по выбранным каналам заказа.
def expand_customer_dispatch(
    dispatch: NotificationDispatch,
    channels: list[str],
) -> list[NotificationDispatch]:
    expanded: list[NotificationDispatch] = []
    for channel in channels:
        if channel not in _ORDER_NOTIFICATION_CHANNELS:
            continue
        idempotency_key = dispatch.idempotency_key
        if idempotency_key:
            idempotency_key = f"{idempotency_key}:{channel}"
        expanded.append(
            NotificationDispatch(
                channel=(
                    NotificationChannel.EMAIL
                    if channel == "email"
                    else NotificationChannel.CUSTOMER
                ),
                template=dispatch.template,
                payload=dispatch.payload,
                created_by=dispatch.created_by,
                idempotency_key=idempotency_key,
                skip_if_order_event=dispatch.skip_if_order_event,
                record_order_event=dispatch.record_order_event,
            )
        )
    return expanded
