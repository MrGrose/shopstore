USER_ROLE_LABELS: dict[str, str] = {
    "buyer": "Покупатель",
    "admin": "Админ",
}

ORDER_STATUS_LABELS: dict[str, str] = {
    "created": "Заказ создан",
    "processing": "В обработке",
    "assembling": "Ожидает отправки",
    "delivery": "В доставке",
    "completed": "Выполнен",
    "cancelled": "Отменен",
    "failed": "Ошибка",
}

ORDER_EVENT_LABELS: dict[str, str] = {
    "order_created": "Заказ создан",
    "status_changed": "Статус изменен",
    "assembly_started": "Передан в сборку",
    "delivery_started": "Передан в доставку",
    "delivered_to_customer": "Доставлен клиенту",
    "order_cancelled": "Заказ отменен",
    "order_failed": "Ошибка заказа",
    "delivery_address_edited": "Адрес доставки изменен",
    "order_items_edited": "Позиции заказа изменены",
    "customer_notified": "Клиент уведомлен",
    "availability_confirmation_requested": "Требуется подтверждение наличия",
    "availability_stock_check_saved": "Проверка наличия сохранена",
    "supplier_availability_checked": "Автопроверка у поставщика",
    "availability_confirmed": "Наличие подтверждено",
    "availability_rejected": "Товар недоступен",
    "payment_accepted": "Оплата подтверждена (СБП)",
    "payment_duplicate_accepted": "Повторная успешная оплата",
    "order_auto_cancelled_payment_timeout": "Автоотмена: срок оплаты истёк",
    "order_cancelled_by_customer": "Клиент отменил заказ",
    "late_payment_after_auto_cancel": "Оплата после автоотмены",
    "admin_comment": "Комментарий",
}

CANCELLATION_REASON_LABELS: dict[str, str] = {
    "payment_timeout": "Срок оплаты истёк",
    "customer_request": "Отменён клиентом",
}

AVAILABILITY_CONFIRMATION_LABELS: dict[str, str] = {
    "not_required": "Не требуется",
    "pending": "Проверяем наличие",
    "confirmed": "Наличие подтверждено",
    "unavailable": "Товар недоступен",
}

ADMIN_ORDER_QUEUE_LABELS: dict[str, str] = {
    "availability": "Проверить наличие",
    "assembling": "Передать в сборку",
    "tracking": "Ждём трек",
}

ADMIN_ORDER_QUEUE_ICONS: dict[str, str] = {
    "availability": "alert",
    "assembling": "box",
    "tracking": "truck",
}

ADMIN_ORDER_QUEUE_TONES: dict[str, str] = {
    "availability": "warning",
    "assembling": "accent",
    "tracking": "neutral",
}

ADMIN_ORDER_QUEUE_KEYS: tuple[str, ...] = ("availability", "assembling", "tracking")

ALL_ORDER_STATUSES: tuple[str, ...] = tuple(ORDER_STATUS_LABELS.keys())
