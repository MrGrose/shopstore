from collections.abc import Mapping, Sequence
from decimal import Decimal
from html import escape
from typing import Literal

from src.core.config import settings
from src.schemas.money import format_finance_rub
from src.utils.urls import mini_app_account_tab_url

CUSTOMER_ORDER_TG_PARSE_MODE = "HTML"
CustomerMessageFormat = Literal["html", "plain"]

# Plain-фрагменты footer клиентского TG-уведомления.
CUSTOMER_FOOTER_PLAIN: dict[str, str] = {
    "orders_track": "Следить за заказом можно {links}.",
    "orders_details": "Подробная информация доступна {links}.",
    "orders_updated": "Обновлённый заказ уже доступен {links}.",
    "orders_actual": "Актуальная информация доступна {links}.",
    "pay": "Можно переходить к оплате {links}.",
    "pay_ready": "Оплатить заказ можно {links}.",
    "support": "Связаться с поддержкой можно {links}.",
    "support_brand": "Поддержка Shopstore — {links}.",
    "auto": "О любых изменениях сообщим вам.",
    "info_lk": "Дополнительная информация появится {links}.",
}

# HTML и plain-фрагменты footer клиентского TG-уведомления.
CUSTOMER_FOOTER_HTML: dict[str, str | None] = {
    "orders_track": "Следить за заказом можно {links}.",
    "orders_details": "Подробная информация доступна {links}.",
    "orders_updated": "Обновлённый заказ уже доступен {links}.",
    "orders_actual": "Актуальная информация доступна {links}.",
    "pay": "Можно переходить к оплате {links}.",
    "pay_ready": "Оплатить заказ можно {links}.",
    "support": "Связаться с поддержкой можно {links}.",
    "support_brand": "Поддержка Shopstore — {links}.",
    "auto": "О любых изменениях сообщим вам.",
    "info_lk": "Дополнительная информация появится {links}.",
    "none": None,
}

# Табы для footer клиентского TG-уведомления.
CUSTOMER_FOOTER_TAB: dict[str, str] = {
    "orders_track": "orders",
    "orders_details": "orders",
    "orders_updated": "orders",
    "orders_actual": "orders",
    "pay": "orders",
    "pay_ready": "orders",
    "support": "support",
    "support_brand": "support",
}

# Метки для статуса заказа.
CUSTOMER_ORDER_STATUS_LABELS: dict[str, str] = {
    "created": "Ожидает оплаты",
    "processing": "Проверяем наличие",
    "assembling": "Готовится к отправке",
    "delivery": "В пути",
    "shipment_delivered": "Посылка доставлена",
    "completed": "Доставлен",
    "cancelled": "Отменён",
    "failed": "Ошибка",
}

# Метки для клиентского TG-уведомления.
CUSTOMER_COPY_LABELS: dict[str, str] = {
    "payment.received": "Оплата получена",
    "payment.awaiting": "Ожидаем оплату",
    "payment.failed": "Оплата не прошла",
    "payment.late.received": "Оплата после отмены",
    "availability.removed": "Часть снята",
    "availability.ok": "Наличие OK",
    "availability.confirmed": "Наличие подтверждено",
    "availability.unavailable": "Наличие не подтверждено",
    "composition.changed": "Состав изменён",
    "status.default": "Обновление",
}

# CTA для клиентского TG-уведомления.
CUSTOMER_MESSAGE_CTA: dict[str, str] = {
    "status.created": "💳 Оплатить заказ",
    "status.delivery": "📦 Открыть заказ",
    "status.shipment_delivered": "📦 Открыть заказ",
    "payment.awaiting": "💳 Оплатить заказ",
    "payment.failed": "💳 Повторить оплату",
    "availability.removed": "💳 Оплатить заказ",
    "availability.ok": "💳 Оплатить заказ",
    "availability.confirmed": "💳 Оплатить заказ",
}

# Шаблоны для CTA напрямую без footer.
_CUSTOMER_CTA_DIRECT_TEMPLATES = frozenset(
    {
        "payment.received",
        "payment.late.received",
        "payment.awaiting",
        "payment.failed",
        "availability.confirmed",
        "availability.unavailable",
        "composition.changed",
    }
)

# Черновик B в админке. Шапка TG — «Заказ #N · Посылка доставлена». Без трека.
CUSTOMER_SHIPMENT_DELIVERED_DRAFT = (
    "По заказу 📦 #{order_id} · Посылка №{seq} доставлена."
)

# Черновик packing: одна посылка. Шапка TG — «Заказ #N · Готовится к отправке».
CUSTOMER_ASSEMBLY_SINGLE_DRAFT = "📦 Заказ оформлен у поставщика."

# Черновик packing: несколько посылок.
CUSTOMER_ASSEMBLY_PARCEL_DRAFT = (
    "📦 По заказу #{order_id} · Посылка №{seq} оформлена у поставщика."
)


# Тексты клиентских TG-сообщений: тело, footer (см. CUSTOMER_FOOTER_HTML).
CUSTOMER_ORDER_COPY: dict[str, tuple[str, str]] = {
    "status.created": (
        "Спасибо! Мы получили ваш заказ.\n\nТеперь его можно оплатить.",
        "pay",
    ),
    "status.processing": (
        "👷‍♂️ Мы начали обработку вашего заказа.\n\n"
        "Сейчас проверяем наличие товаров и уточняем детали у поставщика.",
        "auto",
    ),
    "status.assembling": (
        "📦 Заказ оформлен у поставщика.",
        "orders_track",
    ),
    "status.delivery": (
        "🚚 Ваш заказ в пути.\n\n"
        "Трек-номер появится в личном кабинете сразу после передачи перевозчиком.",
        "orders_track",
    ),
    "status.shipment_delivered": (
        "Посылка доставлена.",
        "orders_track",
    ),
    "status.completed": (
        "Заказ успешно выполнен.\n\n"
        "Спасибо, что выбрали Shopstore!\n\n"
        "Будем рады видеть вас снова ❤️",
        "none",
    ),
    "status.cancelled": (
        "Заказ отменён.\n\n"
        "Если вы уже оплатили заказ или у вас остались вопросы — напишите нам.",
        "support",
    ),
    "status.failed": (
        "Возникла проблема при обработке заказа.\n\n"
        "🤔 Мы уже разбираемся с ситуацией. "
        "Если потребуется ваше участие — обязательно свяжемся.",
        "info_lk",
    ),
    "status.default": (
        "🔄 По заказу есть обновление — подробности ниже.",
        "orders_track",
    ),
    "availability.removed": (
        "🔍 Мы проверили наличие товаров.\n\n"
        "К сожалению, часть товаров сейчас недоступна, "
        "поэтому мы обновили состав заказа.",
        "orders_updated",
    ),
    "availability.ok": (
        "✅ Все товары есть в наличии.",
        "pay",
    ),
    "availability.confirmed": (
        "🟢 Все товары подтверждены поставщиком.\n\nЗаказ готов к оплате.",
        "pay_ready",
    ),
    "availability.unavailable": (
        "К сожалению, подтвердить наличие всех товаров не удалось.\n\n"
        "Если нужна помощь — напишите нам.",
        "support_brand",
    ),
    "composition.changed": (
        "🔄 Состав заказа обновлён.",
        "orders_actual",
    ),
    "payment.received": (
        "💳 Оплата получена.\n\n"
        "Оформляем заказ у поставщика — сообщим, когда отправим.",
        "orders_track",
    ),
    "payment.late.received": (
        "Мы получили оплату по заказу #{order_id}, "
        "но к этому моменту заказ уже был отменён.\n\n"
        "Мы проверим оплату и свяжемся с вами "
        "для уточнения дальнейших действий.",
        "support",
    ),
    "payment.awaiting": (
        "⏳ Ожидаем оплату.\n\nОплатите заказ в личном кабинете.",
        "pay",
    ),
    "payment.failed": (
        "❌ Не удалось обработать платёж.\n\n"
        "Попробуйте оплатить заказ ещё раз. Если проблема повторится — напишите нам.",
        "pay",
    ),
}


# URL вкладки ЛК на сайте и в Mini App.
def _customer_account_urls(tab: str) -> tuple[str | None, str | None]:
    site = (settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    site_url = f"{site}/account?tab={tab}" if site else None
    mini_app = (settings.TG_MINI_APP_URL or "").strip()
    app_url = mini_app_account_tab_url(mini_app, tab) if mini_app else None
    return site_url, app_url


# HTML и plain-фрагмент со ссылками на сайт и Mini App.
def _customer_account_links(tab: str) -> tuple[str, str]:
    site_url, app_url = _customer_account_urls(tab)
    if site_url and app_url:
        site_href = escape(site_url, quote=True)
        app_href = escape(app_url, quote=True)
        html = (
            f'в <a href="{site_href}">личном кабинете на сайте</a> '
            f'или <a href="{app_href}">в приложении</a>'
        )
        plain = "в личном кабинете на сайте или в приложении"
        return html, plain
    if site_url:
        site_href = escape(site_url, quote=True)
        html = f'в <a href="{site_href}">личном кабинете на сайте</a>'
        plain = "в личном кабинете на сайте"
        return html, plain
    if app_url:
        app_href = escape(app_url, quote=True)
        html = f'в <a href="{app_href}">личном кабинете в приложении</a>'
        plain = "в личном кабинете в приложении"
        return html, plain
    plain = "в личном кабинете на сайте или в приложении"
    return plain, plain


# Footer TG-сообщения клиенту (HTML-ссылки на сайт и Mini App).
def _customer_footer_html(kind: str) -> str | None:
    template = CUSTOMER_FOOTER_HTML.get(kind)
    if template is None:
        return None
    if "{links}" not in template:
        return template
    tab = CUSTOMER_FOOTER_TAB.get(kind, "orders")
    links_html, links_plain = _customer_account_links(tab)
    if links_html == links_plain and "href=" not in links_html:
        plain_fmt = CUSTOMER_FOOTER_PLAIN.get(kind, "")
        return plain_fmt.format(links=links_plain) if plain_fmt else None
    return template.format(links=links_html)


# Footer email-сообщения клиенту (plain text).
def _customer_footer_plain(kind: str) -> str | None:
    template = CUSTOMER_FOOTER_PLAIN.get(kind)
    if template is None:
        if kind == "none":
            return None
        return CUSTOMER_FOOTER_HTML.get(kind)
    if "{links}" not in template:
        return template
    tab = CUSTOMER_FOOTER_TAB.get(kind, "orders")
    _, links_plain = _customer_account_links(tab)
    return template.format(links=links_plain)


# Footer клиентского сообщения в выбранном формате.
def _customer_footer(kind: str, fmt: CustomerMessageFormat) -> str | None:
    if fmt == "plain":
        return _customer_footer_plain(kind)
    return _customer_footer_html(kind)


# Форматирует динамическое значение для клиентского сообщения.
def _customer_text(value: object, fmt: CustomerMessageFormat) -> str:
    if value is None:
        return "—"
    if fmt == "plain":
        return str(value)
    return escape(str(value))


# Подпись статуса/сценария для шапки «Заказ # · …».
def _customer_message_label(copy_key: str) -> str:
    if copy_key.startswith("status."):
        status = copy_key.removeprefix("status.")
        return CUSTOMER_ORDER_STATUS_LABELS.get(
            status,
            CUSTOMER_COPY_LABELS.get(copy_key, status),
        )
    return CUSTOMER_COPY_LABELS.get(copy_key, copy_key)


# True, если для copy_key в TG показываем WebApp CTA вместо footer.
def _customer_copy_has_cta(copy_key: str) -> bool:
    return copy_key in CUSTOMER_MESSAGE_CTA


# WebApp CTA для клиентского TG-уведомления.
def build_customer_webapp_cta_keyboard(
    cta_label: str,
    tab: str,
) -> dict[str, object] | None:
    mini_app = (settings.TG_MINI_APP_URL or "").strip()
    if not mini_app or not cta_label.strip():
        return None
    url = mini_app_account_tab_url(mini_app, tab)
    return {
        "inline_keyboard": [
            [{"text": cta_label, "web_app": {"url": url}}],
        ]
    }


# CTA (label, tab) для dispatch клиентского уведомления.
def resolve_customer_notification_cta(
    template: str,
    order_status: str | None = None,
    has_removed_items: bool = False,
) -> tuple[str, str] | None:
    copy_key: str | None = None
    if template == "order_status" and order_status:
        copy_key = f"status.{order_status.strip().lower()}"
    elif template == "availability.check":
        copy_key = "availability.removed" if has_removed_items else "availability.ok"
    elif template in _CUSTOMER_CTA_DIRECT_TEMPLATES:
        copy_key = template
    if copy_key is None:
        return None
    cta_label = CUSTOMER_MESSAGE_CTA.get(copy_key)
    if not cta_label:
        return None
    _, footer_kind = CUSTOMER_ORDER_COPY.get(
        copy_key,
        CUSTOMER_ORDER_COPY["status.default"],
    )
    tab = CUSTOMER_FOOTER_TAB.get(footer_kind, "orders")
    return cta_label, tab


# Собирает клиентское сообщение по заказу в HTML или plain text.
def _format_customer_order_message(
    order_id: int,
    message_label: str,
    intro: str,
    body_lines: list[str],
    total: Decimal | None = None,
    total_label: str = "Итого",
    footer: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
    has_cta: bool = False,
) -> str:
    header = f"Заказ #{order_id} · {message_label}"
    body_parts = [intro.replace("{order_id}", str(order_id))]
    if body_lines:
        body_parts.append("")
        body_parts.extend(body_lines)
    if total is not None:
        body_parts.append("")
        if fmt == "plain":
            body_parts.append(f"{total_label}: {format_finance_rub(total)}")
        else:
            body_parts.append(
                f"<b>{total_label}:</b> "
                f"{_customer_text(format_finance_rub(total), fmt)}"
            )
    body_text = "\n".join(body_parts)

    if fmt == "plain":
        lines = [header, "", body_text]
        if footer:
            lines.extend(["", footer])
        return "\n".join(lines)

    body_html = escape(intro.replace("{order_id}", str(order_id)))
    if body_lines or total is not None:
        inner_parts = [body_html]
        if body_lines:
            inner_parts.append("")
            inner_parts.extend(body_lines)
        if total is not None:
            inner_parts.append("")
            inner_parts.append(
                f"<b>{total_label}:</b> "
                f"{_customer_text(format_finance_rub(total), fmt)}"
            )
        body_html = "\n".join(inner_parts)

    parts = [
        f"<b>{escape(header)}</b>",
        "",
        f"<blockquote>{body_html}</blockquote>",
    ]
    if footer and not (for_telegram and has_cta):
        parts.extend(["", f"<i>{footer}</i>"])
    return "\n".join(parts)


# Собирает клиентское сообщение из CUSTOMER_ORDER_COPY + footer.
def _build_customer_order_message(
    order_id: int,
    copy_key: str,
    body_lines: list[str] | None = None,
    total: Decimal | None = None,
    total_label: str = "Итого",
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    body, footer_kind = CUSTOMER_ORDER_COPY.get(
        copy_key,
        CUSTOMER_ORDER_COPY["status.default"],
    )
    has_cta = _customer_copy_has_cta(copy_key) and fmt == "html"
    return _format_customer_order_message(
        order_id,
        _customer_message_label(copy_key),
        body,
        body_lines or [],
        total=total,
        total_label=total_label,
        footer=_customer_footer(footer_kind, fmt),
        fmt=fmt,
        for_telegram=for_telegram,
        has_cta=has_cta,
    )


# True, если текст уже собран как HTML-шаблон для клиента.
def is_customer_html_message(text: str) -> bool:
    markers = ("<b>", "<i>", "<u>", "<s>", "<code>", "<pre>", "<a ", "<blockquote>")
    return any(marker in text for marker in markers)


# Строка позиции заказа для клиентского сообщения.
def _format_customer_order_item_line(
    snapshot: Mapping[str, object],
    fmt: CustomerMessageFormat = "html",
) -> str:
    title = _customer_text(snapshot.get("title") or "Товар", fmt)
    variant_label = snapshot.get("variant_label")
    qty = snapshot.get("quantity")
    qty_text = f"{qty} шт." if qty is not None else "—"
    if variant_label and str(variant_label).strip():
        return f"{title}, {_customer_text(variant_label, fmt)} — {qty_text}"
    return f"{title} — {qty_text}"


# Список позиций заказа с маркерами для клиентского сообщения.
def _format_customer_order_bullets(
    rows: Sequence[object],
    fmt: CustomerMessageFormat = "html",
) -> list[str]:
    bullets: list[str] = []
    for row in rows:
        if isinstance(row, Mapping):
            bullets.append(f"• {_format_customer_order_item_line(row, fmt)}")
    return bullets


# Добавляет секцию со списком позиций в клиентское сообщение.
def _append_customer_order_section(
    lines: list[str],
    title: str,
    bullets: list[str],
    fmt: CustomerMessageFormat = "html",
) -> None:
    if not bullets:
        return
    if lines:
        lines.append("")
    if fmt == "plain":
        lines.append(title)
    else:
        lines.append(f"<b>{title}</b>")
    lines.extend(bullets)


# Строка изменения количества для сообщения о составе заказа.
def _format_customer_composition_change_line(
    before: Mapping[str, object],
    after: Mapping[str, object],
    fmt: CustomerMessageFormat = "html",
) -> str | None:
    title = _customer_text(before.get("title") or after.get("title") or "Товар", fmt)
    if before.get("quantity") == after.get("quantity"):
        if before.get("unit_price") == after.get("unit_price"):
            return None
        before_price = _customer_text(before.get("unit_price"), fmt)
        after_price = _customer_text(after.get("unit_price"), fmt)
        return f"• {title}: цена {before_price} → {after_price} ₽"
    before_qty = _customer_text(before.get("quantity"), fmt)
    after_qty = _customer_text(after.get("quantity"), fmt)
    return f"• {title}: {before_qty} → {after_qty}"


# Форматирование сообщения о статусе заказа для клиента.
def customer_status_message(
    order_id: int,
    status: str,
    customer_name: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del customer_name
    copy_key = f"status.{status.strip().lower()}"
    if copy_key not in CUSTOMER_ORDER_COPY:
        copy_key = "status.default"
    return _build_customer_order_message(
        order_id,
        copy_key,
        fmt=fmt,
        for_telegram=for_telegram,
    )


# Готовит текст TG-уведомления клиенту: шаблон HTML или plain с escape.
def format_customer_telegram_delivery_text(
    custom_message: str | None,
    order_id: int,
    order_status: str,
    customer_name: str | None = None,
) -> str:
    if custom_message is None:
        return customer_status_message(
            order_id,
            order_status,
            customer_name,
            for_telegram=True,
        )
    stripped = custom_message.strip()
    if not stripped:
        return customer_status_message(
            order_id,
            order_status,
            customer_name,
            for_telegram=True,
        )
    if is_customer_html_message(stripped):
        return stripped
    copy_key = f"status.{order_status.strip().lower()}"
    if copy_key not in CUSTOMER_ORDER_COPY:
        copy_key = "status.default"
    default_plain = customer_status_message(
        order_id,
        order_status,
        customer_name,
        fmt="plain",
    ).strip()
    if stripped == default_plain:
        return customer_status_message(
            order_id,
            order_status,
            customer_name,
            for_telegram=True,
        )
    label = _customer_message_label(copy_key)
    header_line = f"Заказ #{order_id} · {label}"
    lines = stripped.splitlines()
    if lines and lines[0].strip() == header_line:
        stripped = "\n".join(lines[1:]).strip()
    return _format_customer_order_message(
        order_id,
        label,
        escape(stripped),
        [],
        footer=None,
        fmt="html",
        for_telegram=True,
        has_cta=False,
    )


# Ручное сообщение менеджера: TG — «Заказ #N» без этапа, email — только текст.
def format_customer_manual_message(
    order_id: int,
    message: str,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del for_telegram
    stripped = message.strip()
    header = f"Заказ #{order_id}"
    if fmt == "plain":
        return f"{header}\n\n{stripped}" if stripped else header
    return f"<b>{escape(header)}</b>\n\n<blockquote>{escape(stripped)}</blockquote>"


# TG-сообщение клиенту после проверки наличия.
def format_customer_availability_check_message(
    order_id: int,
    removed_items: Sequence[Mapping[str, object]],
    new_total: Decimal,
    customer_name: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del customer_name
    if removed_items:
        return _build_customer_order_message(
            order_id,
            "availability.removed",
            body_lines=_format_customer_order_bullets(removed_items, fmt),
            total=new_total,
            total_label="Новая сумма",
            fmt=fmt,
            for_telegram=for_telegram,
        )
    return _build_customer_order_message(
        order_id,
        "availability.ok",
        total=new_total,
        total_label="Итого к оплате",
        fmt=fmt,
        for_telegram=for_telegram,
    )


# TG-сообщение клиенту при подтверждении наличия.
def format_customer_availability_confirmed_message(
    order_id: int,
    customer_name: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del customer_name
    return _build_customer_order_message(
        order_id, "availability.confirmed", fmt=fmt, for_telegram=for_telegram
    )


# TG-сообщение клиенту при отказе по наличию.
def format_customer_availability_unavailable_message(
    order_id: int,
    customer_name: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del customer_name
    return _build_customer_order_message(
        order_id, "availability.unavailable", fmt=fmt, for_telegram=for_telegram
    )


# TG-сообщение клиенту об изменении состава заказа.
def format_customer_composition_changed_message(
    order_id: int,
    diff: Mapping[str, object],
    new_total: Decimal,
    customer_name: str | None = None,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    del customer_name
    body_lines: list[str] = []
    removed = diff.get("removed")
    if isinstance(removed, list):
        _append_customer_order_section(
            body_lines,
            "Убрали",
            _format_customer_order_bullets(removed, fmt),
            fmt=fmt,
        )
    added = diff.get("added")
    if isinstance(added, list):
        _append_customer_order_section(
            body_lines,
            "Добавили",
            _format_customer_order_bullets(added, fmt),
            fmt=fmt,
        )
    changed = diff.get("changed")
    if isinstance(changed, list):
        change_bullets: list[str] = []
        for row in changed:
            if not isinstance(row, Mapping):
                continue
            before = row.get("before")
            after = row.get("after")
            if not isinstance(before, Mapping) or not isinstance(after, Mapping):
                continue
            line = _format_customer_composition_change_line(before, after, fmt)
            if line:
                change_bullets.append(line)
        _append_customer_order_section(
            body_lines,
            "Изменили количество",
            change_bullets,
            fmt=fmt,
        )
    return _build_customer_order_message(
        order_id,
        "composition.changed",
        body_lines=body_lines,
        total=new_total,
        fmt=fmt,
        for_telegram=for_telegram,
    )


# TG-сообщение клиенту об успешной оплате.
def format_customer_payment_received_message(
    order_id: int,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    return _build_customer_order_message(
        order_id, "payment.received", fmt=fmt, for_telegram=for_telegram
    )


# TG-сообщение клиенту о поздней оплате после отмены заказа.
def format_customer_payment_late_received_message(
    order_id: int,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    return _build_customer_order_message(
        order_id, "payment.late.received", fmt=fmt, for_telegram=for_telegram
    )


# TG-сообщение клиенту об ожидании оплаты.
def format_customer_payment_awaiting_message(
    order_id: int,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    return _build_customer_order_message(
        order_id, "payment.awaiting", fmt=fmt, for_telegram=for_telegram
    )


# TG-сообщение клиенту о неуспешной оплате.
def format_customer_payment_failed_message(
    order_id: int,
    fmt: CustomerMessageFormat = "html",
    for_telegram: bool = False,
) -> str:
    return _build_customer_order_message(
        order_id, "payment.failed", fmt=fmt, for_telegram=for_telegram
    )
