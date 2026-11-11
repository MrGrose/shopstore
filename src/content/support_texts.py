from html import escape

from src.content.telegram_html import build_ops_alert_message
from src.core.config import settings

SUPPORT_TOPIC_LABELS: dict[str, str] = {
    "order_question": "Вопрос по заказу",
    "delivery_question": "Вопрос по доставке",
    "product_problem": "Проблема с товаром",
    "referrer_change": "Смена реферера",
    "general": "Общий вопрос",
}


# Человекочитаемая подпись темы обращения.
def support_topic_label(topic: str) -> str:
    return SUPPORT_TOPIC_LABELS.get(topic, topic)


# URL для обращения в админке
def admin_support_ticket_url(ticket_id: int) -> str | None:
    base = (settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/internal/admin/support?id={ticket_id}"


# Форматирование сообщения о новом обращении
def format_support_group_ticket_message(
    ticket_id: int,
    topic: str,
    customer_label: str,
    order_id: int | None,
    body: str,
    is_new_ticket: bool,
    for_telegram: bool = False,
) -> str:
    topic_label = support_topic_label(topic)
    header = (
        f"🆕 Новое обращение · #{ticket_id}"
        if is_new_ticket
        else f"💬 Сообщение клиента · #{ticket_id}"
    )
    lines = [
        f"Тема: {topic_label}",
        f"Клиент: {customer_label}",
    ]
    if order_id is not None:
        lines.append(f"Заказ: #{order_id}")
    lines.extend(["", body.strip()])
    if not for_telegram:
        return "\n".join([header, ""] + lines)
    return build_ops_alert_message(header, lines)


# Форматирование сообщения о ответе на обращение
def format_support_staff_reply_to_customer(ticket_id: int, body: str) -> str:
    del ticket_id
    body_html = escape(body.strip())
    return f"<b>Поддержка Shopstore</b>\n\n<blockquote>{body_html}</blockquote>"


# Шаблоны ответов на обращения
SUPPORT_STAFF_REPLY_TEMPLATES: list[dict[str, object]] = [
    {
        "id": "received",
        "label": "Получили обращение",
        "body": (
            "Здравствуйте!\n\n"
            "Спасибо за обращение.\n\n"
            "Мы уже получили ваше сообщение и приступили к работе.\n\n"
            "Обычно отвечаем в течение рабочего дня."
        ),
    },
    {
        "id": "checking_order",
        "label": "Уточняем статус заказа",
        "topics": ("order_question",),
        "body": (
            "Здравствуйте!\n\n"
            "Мы уже запросили информацию у поставщика.\n\n"
            "Как только получим ответ — сразу сообщим вам здесь."
        ),
    },
    {
        "id": "delivery_update",
        "label": "Информация по доставке",
        "topics": ("delivery_question",),
        "body": (
            "Здравствуйте!\n\n"
            "Проверили информацию по доставке. "
            "Если заказ уже передан службе доставки, "
            "статус обновится в личном кабинете."
        ),
    },
    {
        "id": "need_details",
        "label": "Нужны уточнения",
        "body": (
            "Здравствуйте!\n\n"
            "Чтобы помочь быстрее, уточните, пожалуйста, номер заказа "
            "и опишите ситуацию подробнее."
        ),
    },
    {
        "id": "product_photos",
        "label": "Проблема с товаром — описание",
        "topics": ("product_problem",),
        "body": (
            "Здравствуйте!\n\n"
            "Чтобы разобраться быстрее, опишите, пожалуйста, проблему подробнее: "
            "что именно не так."
        ),
    },
    {
        "id": "referrer_change",
        "label": "Смена реферера — уточнение",
        "topics": ("referrer_change",),
        "body": (
            "Здравствуйте!\n\n"
            "Смена реферера возможна только через поддержку.\n\n"
            "Пришлите, пожалуйста, ссылку или код приглашения нового реферера "
            "и кратко опишите ситуацию — мы проверим и ответим здесь."
        ),
    },
    {
        "id": "resolved",
        "label": "Вопрос решён",
        "body": (
            "Здравствуйте!\n\n"
            "Ваш вопрос решён. Если понадобится помощь — создайте новое обращение "
            "в личном кабинете."
        ),
    },
]


# Список шаблонов ответов на обращения
def list_support_reply_templates(topic: str | None = None) -> list[dict[str, str]]:
    indexed = list(enumerate(SUPPORT_STAFF_REPLY_TEMPLATES))

    def sort_key(item: tuple[int, dict[str, object]]) -> tuple[int, int]:
        idx, row = item
        topics_raw = row.get("topics")
        topics = topics_raw if isinstance(topics_raw, tuple) else ()
        if not topics:
            return (0, idx)
        if topic and topic in topics:
            return (0, idx)
        return (1, idx)

    indexed.sort(key=sort_key)
    return [
        {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "body": str(row["body"]),
        }
        for _, row in indexed
    ]
