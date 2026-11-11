import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from src.content.telegram_html import build_ops_alert_message, build_ops_section_message
from src.core.config import settings
from src.schemas.money import format_grouped_amount
from src.utils.datetime_fmt import format_iso_datetime_msk_compact
from src.utils.labels import display_product_title, translate_option_value
from src.utils.phone import format_ru_phone_display


# Финальная сборка ops-сообщения
def _finalize_ops_alert(lines: list[str], for_telegram: bool) -> str:
    if not for_telegram:
        return "\n".join(lines)
    if not lines:
        return ""
    header = lines[0]
    body_lines = lines[1:]
    while body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]
    return build_ops_alert_message(header, body_lines)


# URL для заказа в админке
def admin_order_url(order_id: int) -> str | None:
    base = (settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/internal/admin/orders?id={order_id}"


# URL карточки заказа для кнопки трекинга в Telegram (тот же ?id=, без мёртвого focus=).
def admin_order_tracking_url(order_id: int) -> str | None:
    return admin_order_url(order_id)


# Форматирование заголовка товара с опциями
def format_low_stock_item_title(raw_item: Mapping[str, object]) -> str:
    row = dict(raw_item)
    if row.get("variant_label") and not row.get("option1"):
        row["option1"] = row["variant_label"]
    if row.get("product_title"):
        return _ops_item_display_title(row)
    title = row.get("product_title") or f"Товар #{row.get('product_id', '-')}"
    return str(title)


# EUR для уведомлений TG: 257,10 €.
def _format_ops_eur_text(raw: object) -> str:
    if raw is None:
        return "—"
    if not isinstance(raw, (Decimal, int, float, str)):
        return "—"
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    if value <= 0:
        return "—"
    return f"{format_grouped_amount(value)} €"


# Курс EUR для уведомлений TG: 97,20.
def _format_ops_eur_rate_text(raw: object) -> str:
    if raw is None:
        return "—"
    if not isinstance(raw, (Decimal, int, float, str)):
        return "—"
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    if value <= 0:
        return "—"
    return format_grouped_amount(value)


# RUB для уведомлений TG: 24 990 ₽.
def _format_ops_rub_text(raw: object) -> str:
    if raw is None:
        return "—"
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    quantized = value.quantize(Decimal("0.01"))
    places = 0 if quantized == quantized.to_integral_value() else 2
    return f"{format_grouped_amount(quantized, places=places)} ₽"


# RUB-сумма без знака валюты (для строки «- 1 x 12 990»).
def _format_ops_rub_amount_only(raw: object) -> str:
    if raw is None:
        return "—"
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    quantized = value.quantize(Decimal("0.01"))
    places = 0 if quantized == quantized.to_integral_value() else 2
    return format_grouped_amount(quantized, places=places)


# Вариант товара для уведомлений TG (L, M, …).
def _ops_variant_label(item: Mapping[str, object]) -> str:
    variant_label = item.get("variant_label")
    if variant_label and str(variant_label).strip():
        return str(variant_label).strip()
    chunks: list[str] = []
    for key in ("option1", "option2", "option3"):
        raw = item.get(key)
        if raw is None or not str(raw).strip():
            continue
        chunks.append(translate_option_value(str(raw)))
    return ", ".join(chunks)


def _ops_option_value(item: Mapping[str, object], key: str) -> str | None:
    raw = item.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


# Заголовок позиции для уведомлений TG.
def _ops_item_display_title(item: Mapping[str, object]) -> str:
    title = display_product_title(
        str(item.get("product_title") or f"Товар #{item.get('product_id', '-')}"),
        option1=_ops_option_value(item, "option1"),
        option2=_ops_option_value(item, "option2"),
        option3=_ops_option_value(item, "option3"),
    )
    variant = _ops_variant_label(item)
    if variant:
        return f"{title}, {variant}"
    return title


# Адрес доставки для уведомлений TG.
def _format_ops_delivery_address(delivery: Mapping[str, object]) -> str:
    city = str(delivery.get("city") or "").strip()
    street = str(delivery.get("street") or "").strip()
    house = str(delivery.get("house") or "").strip()
    apartment = str(delivery.get("apartment") or "").strip()
    line = city
    if street:
        line = f"{city}, {street}" if city else street
    if house:
        line = f"{line} {house}".strip()
    if apartment:
        line = f"{line}, кв. {apartment}"
    return line or "—"


# Строки доставки для Новый заказ
def _ops_order_created_delivery_lines(
    delivery: Mapping[str, object],
    customer: Mapping[str, object],
) -> list[str]:
    lines = [_format_ops_delivery_address(delivery)]
    delivery_phone = _format_ops_phone(delivery.get("phone") or customer.get("phone"))
    if delivery_phone != "—":
        lines.append(delivery_phone)
    postal_code = delivery.get("postal_code")
    if postal_code:
        lines.append(f"Индекс: {postal_code}")
    return lines


# Телефон для ops TG.
def _format_ops_phone(raw: object) -> str:
    if raw is None:
        return "—"
    text = str(raw).strip()
    if not text or text == "—":
        return "—"
    try:
        return format_ru_phone_display(text)
    except ValueError:
        return text


# Строка закупочной цены EUR для TG-уведомления админам.
def _format_supplier_eur_text(raw: object) -> str:
    if raw is None:
        return "—"
    if not isinstance(raw, (Decimal, int, float, str)):
        return "—"
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    if value <= 0:
        return "—"
    return format_grouped_amount(value)


# Строки товаров для ops «Новый заказ» (1. Название …).
def _ops_order_created_product_lines(items: list[object]) -> list[str]:
    lines: list[str] = []
    index = 0
    for item in items:
        if not isinstance(item, Mapping):
            continue
        index += 1
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        supplier_eur = _format_ops_eur_text(item.get("supplier_price_eur"))
        qty_text = quantity if quantity is not None else "—"
        lines.append(f"{index}. {_ops_item_display_title(item)}")
        lines.append(f"- {qty_text} x {_format_ops_rub_amount_only(unit_price)}")
        lines.append(f"- закуп {supplier_eur}")
    return lines


def _ops_order_created_total_lines(
    order_meta: Mapping[str, object],
    promo_code_applied: str | None,
) -> list[str]:
    lines: list[str] = []
    if promo_code_applied:
        lines.append(f"Промокод: {promo_code_applied}")
    lines.append(
        f"Курс EUR: {_format_ops_eur_rate_text(order_meta.get('eur_rate_snapshot'))}"
    )
    lines.append(f"Сумма: {_format_ops_rub_text(order_meta.get('total_amount'))}")
    return lines


# Форматирование сообщения о создании заказа
def format_order_created_message(
    payload: Mapping[str, object],
    user_email: str | None,
    promo_code_applied: str | None = None,
    for_telegram: bool = False,
) -> str:
    raw_order = payload.get("order")
    order_meta: Mapping[str, object]
    if isinstance(raw_order, Mapping):
        order_meta = raw_order
    else:
        order_meta = {}

    raw_delivery = payload.get("customer_delivery")
    delivery: Mapping[str, object]
    if isinstance(raw_delivery, Mapping):
        delivery = raw_delivery
    else:
        delivery = {}

    raw_customer = payload.get("customer_data")
    customer: Mapping[str, object]
    if isinstance(raw_customer, Mapping):
        customer = raw_customer
    else:
        customer = {}

    raw_items = payload.get("items")
    items: list[object]
    if isinstance(raw_items, list):
        items = raw_items
    else:
        items = []

    order_id = order_meta.get("id", "-")
    first_name = delivery.get("first_name") or ""
    last_name = delivery.get("last_name") or ""
    customer_name = f"{first_name} {last_name}".strip() or "—"
    email_text = customer.get("email") or user_email or "—"
    phone = _format_ops_phone(delivery.get("phone") or customer.get("phone"))
    tg_username = customer.get("telegram_username")
    tg_part = f" · @{tg_username}" if tg_username else ""
    customer_lines = [str(customer_name), f"{email_text} · {phone}{tg_part}"]
    delivery_lines = _ops_order_created_delivery_lines(delivery, customer)
    product_lines = _ops_order_created_product_lines(items)
    total_lines = _ops_order_created_total_lines(order_meta, promo_code_applied)
    sections = [
        ("👤 Клиент", customer_lines),
        ("📍 Доставка", delivery_lines),
        ("🛒 Товары", product_lines),
        ("💰 Итого", total_lines),
    ]
    if not for_telegram:
        lines = [f"🆕 Новый заказ #{order_id}"]
        for title, section_lines in sections:
            lines.extend(["", title])
            lines.extend(section_lines)
        return "\n".join(lines)

    return build_ops_section_message(
        f"🆕 Новый заказ #{order_id}",
        sections,
    )


# Форматирование сообщения о проверке наличия товаров
def format_availability_review_message(
    order_id: int,
    low_stock_items: Sequence[object],
    for_telegram: bool = False,
) -> str:
    lines = [
        f"Заказ #{order_id} · Проверка наличия",
        "",
    ]
    for raw_item in low_stock_items:
        if not isinstance(raw_item, Mapping):
            continue
        title = format_low_stock_item_title(raw_item)
        available = raw_item.get("available")
        quantity = raw_item.get("quantity")
        available_text = f"{available} шт." if available is not None else "—"
        quantity_text = f"{quantity} шт." if quantity is not None else "—"
        lines.extend(
            [
                f"❗️ {title}",
                f"   Остаток: {available_text} | Заказано: {quantity_text}",
                "",
            ]
        )
    if lines and lines[-1] == "":
        lines.pop()
    lines.extend(["", "Клиент ожидает подтверждения наличия."])
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Форматирование сообщения о поздней оплате после автоотмены
def format_late_payment_message(
    order_id: int,
    order_total: Decimal | None,
    attempt_number: int | None,
    provider_order_id: str | None,
    admin_url: str | None,
    for_telegram: bool = False,
) -> str:
    del admin_url
    lines = [f"Заказ #{order_id} · Поздняя оплата", ""]
    if order_total is not None and attempt_number is not None:
        lines.append(f"Сумма: {order_total} ₽ · попытка #{attempt_number}")
    elif order_total is not None:
        lines.append(f"Сумма: {order_total} ₽")
    elif attempt_number is not None:
        lines.append(f"Попытка #{attempt_number}")
    if provider_order_id:
        lines.append(f"SBP ID: {provider_order_id}")
    lines.append("Заказ уже был отменён — нужна ручная проверка.")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Форматирование сообщения о повторной успешной оплате.
def format_duplicate_payment_message(
    order_id: int,
    order_total: Decimal | None,
    attempt_number: int | None,
    admin_url: str | None,
    for_telegram: bool = False,
) -> str:
    del admin_url
    lines = [f"Заказ #{order_id} · 🚨 Повторная оплата", ""]
    if order_total is not None and attempt_number is not None:
        lines.append(f"Сумма: {order_total} ₽ · попытка #{attempt_number}")
    elif order_total is not None:
        lines.append(f"Сумма: {order_total} ₽")
    elif attempt_number is not None:
        lines.append(f"Попытка #{attempt_number}")
    lines.append("Нужна немедленная проверка и возврат/зачёт.")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Форматирование сообщения о принятой оплате
def format_payment_accepted_message(
    order_id: int,
    order_total: Decimal | None,
    admin_url: str | None,
    customer_name: str | None = None,
    payment_method_label: str | None = None,
    for_telegram: bool = False,
) -> str:
    del admin_url
    lines = ["🟢 Клиент оплатил заказ", "", f"Заказ #{order_id}"]
    if customer_name and customer_name.strip():
        lines.append(f"Клиент: {customer_name.strip()}")
    if order_total is not None:
        lines.append(f"Сумма: {_format_ops_rub_text(order_total)}")
    if payment_method_label and payment_method_label.strip():
        lines.append(f"Оплата: {payment_method_label.strip()}")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Форматирование сообщения о начале доставки заказа
def format_order_delivery_started_message(
    order_id: int,
    admin_url: str | None,
    for_telegram: bool = False,
) -> str:
    del admin_url
    lines = [
        f"Заказ #{order_id} · Передан в доставку",
        "",
        "Трек-номер появится в админке после передачи перевозчику.",
    ]
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Форматирование сообщения о технической проблеме с заказом
def format_order_technical_problem_message(
    order_id: int,
    admin_url: str | None,
    for_telegram: bool = False,
) -> str:
    del admin_url
    lines = [
        f"Заказ #{order_id} · Ошибка",
        "",
        "Проверьте заказ в админке и свяжитесь с клиентом при необходимости.",
    ]
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


def delivered_alert_snapshot_hash(
    parcellab_confirmed: bool,
    parcellab_at: str | None,
    dhl_confirmed: bool,
    dhl_at: str | None,
) -> str:
    payload = json.dumps(
        {
            "parcellab_confirmed": parcellab_confirmed,
            "parcellab_at": parcellab_at,
            "dhl_confirmed": dhl_confirmed,
            "dhl_at": dhl_at,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Hash PLACED delivered-сообщения: TP и CJ, не shipment_id.
def placed_delivered_alert_snapshot_hash(tp: str | None, cj: str | None) -> str:
    payload = json.dumps(
        {"cj": cj or "", "tp": tp or ""},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Строка о доставке от источника.
def _delivered_source_line(name: str, confirmed: bool, at: str | None) -> str:
    if confirmed:
        at_display = format_iso_datetime_msk_compact(at) or "-"
        return f"{name}: доставлен, {at_display}"
    return f"{name}: ещё не подтвердил доставку"


# Legacy order-level A для заказов без Shipment.
def format_admin_delivered_alert_message(
    order_id: int,
    supplier_order_id: str | None,
    tracking_id: str | None,
    parcellab_confirmed: bool,
    parcellab_at: str | None,
    dhl_confirmed: bool,
    dhl_at: str | None,
    checked_at: datetime,
    for_telegram: bool = False,
) -> str:
    header = f"Заказ #{order_id} · Возможно доставлен"
    checked_display = format_iso_datetime_msk_compact(checked_at) or "-"
    lines = [
        header,
        "",
        _delivered_source_line("ParcelLab", parcellab_confirmed, parcellab_at),
        _delivered_source_line("DHL", dhl_confirmed, dhl_at),
        "",
    ]
    if supplier_order_id:
        lines.append(f"Номер Supplier-Demo: {supplier_order_id}")
    if tracking_id:
        lines.append(f"Трек: {tracking_id}")
    lines.append(f"Последняя проверка: {checked_display}")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Текст PLACED delivered alert: заказ, TP и CJ этой посылки.
def format_placed_delivered_alert_message(
    order_id: int,
    tp: str | None,
    cj: str | None,
    checked_at: datetime,
    for_telegram: bool = False,
) -> str:
    checked_display = format_iso_datetime_msk_compact(checked_at) or "-"
    lines = [
        f"Заказ #{order_id} · Возможно доставлен",
        "",
    ]
    if tp:
        lines.append(f"Номер Supplier-Demo: {tp}")
    if cj:
        lines.append(f"Трек: {cj}")
    lines.append("Доставлен")
    lines.append(f"Последняя проверка: {checked_display}")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)


# Hash C: список TP/CJ посылок, без identity A.
def order_completed_alert_snapshot_hash(
    parcels: list[tuple[str | None, str | None]],
) -> str:
    payload = json.dumps(
        [{"cj": cj or "", "tp": tp or ""} for tp, cj in parcels],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Текст C: заказ завершён, TP/CJ из списка Shipment.
def format_order_completed_alert_message(
    order_id: int,
    parcels: list[tuple[str | None, str | None]],
    checked_at: datetime,
    for_telegram: bool = False,
) -> str:
    checked_display = format_iso_datetime_msk_compact(checked_at) or "-"
    lines = [f"Заказ #{order_id} · Завершён администратором", ""]
    if parcels:
        lines.append("Посылки:")
        for index, (tp, cj) in enumerate(parcels, start=1):
            parts = [part for part in (tp, cj) if part]
            lines.append(f"{index}. {' · '.join(parts)}" if parts else f"{index}.")
        lines.append("")
    lines.append(f"Последняя проверка: {checked_display}")
    return _finalize_ops_alert(lines, for_telegram=for_telegram)
