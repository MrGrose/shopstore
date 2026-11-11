from collections.abc import Sequence

from src.schemas.order import OrderEventSchema
from src.services.orders.journey_channel_resolver import (
    JOURNEY_STAGE_KEYS,
    StageChannelSnapshot,
    build_stage_notify_badges,
    channel_label,
    client_notify_line,
    extract_customer_notifications,
    resolve_composition_tg_state,
    resolve_stage_channels,
)
from src.services.orders.supplier_tracking import (
    carrier_timeline_for_journey,
    russian_post_timeline_for_journey,
    store_timeline_for_journey,
    supplier_timeline_for_journey,
)

DELIVERY_FIELD_LABELS: dict[str, str] = {
    "last_name": "Фамилия",
    "first_name": "Имя",
    "city": "Город",
    "postal_code": "Индекс",
    "street": "Улица",
    "house": "Дом",
    "apartment": "Квартира",
}


# Проверяет наличие события одного из типов в истории.
def _has_event_type(event_rows: list[dict[str, object]], *event_types: str) -> bool:
    wanted = set(event_types)
    return any(str(row.get("event_type") or "") in wanted for row in event_rows)


# Собирает строку TG-уведомления админа.
def _admin_notify_line(sent: bool) -> str:
    return "Админ: TG ✓" if sent else "Админ: TG —"


# Собирает строки уведомлений для шага карты заказа.
def _journey_step_notifications(
    stage_key: str,
    stage_channels: object,
    event_rows: list[dict[str, object]],
    composition_tg: str,
) -> list[str]:
    if not isinstance(stage_channels, StageChannelSnapshot):
        return []
    lines = [client_notify_line(stage_channels)]

    if stage_key == "created":
        lines.append(_admin_notify_line(True))
        return lines

    if stage_key == "availability":
        admin_sent = _has_event_type(
            event_rows,
            "availability_confirmation_requested",
            "availability_confirmed",
            "availability_stock_check_saved",
            "supplier_availability_checked",
            "availability_rejected",
        )
        lines.append(_admin_notify_line(admin_sent))
        return lines

    if stage_key == "payment":
        admin_sent = _has_event_type(event_rows, "payment_accepted")
        lines.append(_admin_notify_line(admin_sent))
        if composition_tg != "na":
            lines.append(
                "Состав изменён: "
                + channel_label("TG", composition_tg)  # type: ignore[arg-type]
            )
        return lines

    if stage_key == "assembly":
        lines.append(_admin_notify_line(False))
        return lines

    admin_sent = _has_event_type(event_rows, "delivery_started")
    lines.append(_admin_notify_line(admin_sent))
    return lines


# Собирает бейджи TG/ЛК для шага карты заказа.
def _journey_client_notify_badges(
    stage_key: str,
    availability: str,
    stage_channels: object,
) -> list[dict[str, str]]:
    if stage_key == "availability" and availability == "not_required":
        return []
    if not isinstance(stage_channels, StageChannelSnapshot):
        return []
    return build_stage_notify_badges(stage_channels)


# Возвращает created_by из последнего события одного из указанных типов.
def _event_actor_label(
    event_rows: list[dict[str, object]],
    *event_types: str,
) -> str | None:
    wanted = set(event_types)
    for row in event_rows:
        if str(row.get("event_type") or "") not in wanted:
            continue
        created_by = row.get("created_by")
        if isinstance(created_by, str) and created_by.strip():
            actor = created_by.strip()
            if actor != "system":
                return actor
    return None


# Возвращает дату первого найденного события из списка типов.
def _journey_event_date(
    event_dates: dict[str, str],
    *event_types: str,
) -> str | None:
    for event_type in event_types:
        date = event_dates.get(event_type)
        if date:
            return date
    return None


# Собирает факты для шага «Наличие» в карте заказа.
def _availability_journey_facts(
    availability: str,
    event_rows: list[dict[str, object]],
) -> list[str]:
    if availability == "not_required":
        return ["Проверка не требуется"]
    if availability == "confirmed":
        actor = _event_actor_label(
            event_rows,
            "availability_confirmed",
            "availability_stock_check_saved",
        )
        if actor:
            return [actor]
        return ["Наличие подтверждено"]
    if availability == "unavailable":
        actor = _event_actor_label(
            event_rows,
            "availability_rejected",
            "availability_stock_check_saved",
        )
        if actor:
            return [actor]
        return ["Товар недоступен"]
    return ["Ожидает решения админа"]


# Есть ли у заказа новый SupplierOrder/Shipment flow.
def _has_new_shipment_flow(
    supplier_orders: Sequence[object] | None,
    shipments: Sequence[object] | None,
) -> bool:
    return bool(supplier_orders) or bool(shipments)


# Активные (не cancelled) supplier orders.
def _active_supplier_orders(supplier_orders: Sequence[object] | None) -> list[object]:
    rows: list[object] = []
    for so in supplier_orders or []:
        if str(getattr(so, "status", "") or "").lower() == "cancelled":
            continue
        rows.append(so)
    return rows


# Placed supplier orders с TP (external_id).
def _placed_supplier_orders(supplier_orders: Sequence[object] | None) -> list[object]:
    placed: list[object] = []
    for so in _active_supplier_orders(supplier_orders):
        if str(getattr(so, "status", "") or "").lower() != "placed":
            continue
        if not str(getattr(so, "external_id", "") or "").strip():
            continue
        placed.append(so)
    return placed


# Существительное «посылка» в нужном числе.
def _parcel_noun(count: int) -> str:
    n = abs(count) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return "посылок"
    if n1 == 1:
        return "посылка"
    if 2 <= n1 <= 4:
        return "посылки"
    return "посылок"


# Подпись и факты шага «Сборка» по placed SupplierOrder.
def _new_flow_assembly_copy(
    status: str, supplier_orders: Sequence[object] | None
) -> tuple[str, list[str]]:
    active_n = len(_active_supplier_orders(supplier_orders))
    placed_n = len(_placed_supplier_orders(supplier_orders))
    finished = (active_n > 0 and placed_n == active_n) or (
        status in {"delivery", "completed"} and placed_n > 0
    )
    if placed_n and finished:
        return "завершена", [f"{placed_n} из {active_n} посылок оформлены"]
    if placed_n:
        return "в работе", [f"{placed_n} из {active_n} посылок оформлены"]
    if active_n:
        return "не начата", [f"0 из {active_n} посылок оформлены"]
    return "не начата", []


# CJ-номера у существующих Shipment.
def _shipment_tracking_numbers(shipments: Sequence[object] | None) -> list[str]:
    numbers: list[str] = []
    for row in shipments or []:
        value = str(getattr(row, "supplier_tracking_number", "") or "").strip()
        if value:
            numbers.append(value)
    return numbers


# Admin completion fact; не смешивать с tracking delivered.
def _admin_completion_fact(rows: Sequence[object]) -> str | None:
    n = len(rows)
    if not n:
        return None
    done = sum(1 for row in rows if getattr(row, "completed_at", None) is not None)
    return f"Завершено администратором: {done} из {n}"


def _with_admin_completion(facts: list[str], rows: Sequence[object]) -> list[str]:
    extra = _admin_completion_fact(rows)
    if extra:
        return [*facts, extra]
    return facts


# Подпись и факты шага «Доставка» по Shipment/CJ.
def _new_flow_delivery_copy(
    delivery_done: bool,
    status: str,
    shipments: Sequence[object] | None,
) -> tuple[str, list[str]]:
    rows = list(shipments or [])
    if delivery_done:
        return "завершена", _with_admin_completion([], rows)
    cjs = _shipment_tracking_numbers(rows)
    n = len(rows)
    delivered_n = sum(
        1
        for row in rows
        if str(getattr(row, "status", "") or "").lower() == "delivered"
    )
    if n and delivered_n == n:
        noun = _parcel_noun(n)
        verb = "доставлена" if noun == "посылка" else "доставлены"
        return "доставлены", _with_admin_completion([f"Все {n} {noun} {verb}"], rows)
    if delivered_n:
        facts = [f"{delivered_n} из {n} посылок доставлены"]
        rest = n - delivered_n
        if rest:
            facts.append(f"{rest} ещё в пути")
        return "частично", _with_admin_completion(facts, rows)
    k = len(cjs)
    if k and k == n:
        noun = _parcel_noun(n)
        verb = "передана" if noun == "посылка" else "переданы"
        return "в пути", _with_admin_completion([f"{n} {noun} {verb} в доставку"], rows)
    if n and k == 0:
        return "ожидаем трек-номера", _with_admin_completion(
            ["Ожидаем трек-номера для посылок"], rows
        )
    if n and k:
        return "в пути", _with_admin_completion(
            [
                f"{k} из {n} посылок с трек-номером",
                "Ожидаем трек-номера для остальных посылок",
            ],
            rows,
        )
    if status in {"delivery", "completed"}:
        return "ожидаем трек-номера", _with_admin_completion(
            ["Ожидаем трек-номера для посылок"], rows
        )
    return "ожидается", _with_admin_completion([], rows)


# Собирает отображаемую карту заказа из фактического состояния и истории.
def build_order_journey(
    order: object,
    event_rows: list[dict[str, object]],
    tracking_json: dict[str, object] | None = None,
    outbox_by_key: dict[str, str] | None = None,
    supplier_orders: Sequence[object] | None = None,
    shipments: Sequence[object] | None = None,
) -> dict[str, object]:
    status = str(getattr(order, "status", "") or "").lower()
    availability = str(
        getattr(order, "availability_confirmation_status", "not_required")
        or "not_required"
    ).lower()
    payment_state = str(getattr(order, "payment_state", "not_started") or "")
    supplier_order_id = getattr(order, "supplier_order_id", None)
    supplier_tracking_id = getattr(order, "supplier_tracking_id", None)
    tracking_json = tracking_json if tracking_json is not None else {}
    carrier_timeline = carrier_timeline_for_journey(
        tracking_json if isinstance(tracking_json, dict) else None,
        str(supplier_tracking_id) if supplier_tracking_id else None,
    )
    supplier_timeline = supplier_timeline_for_journey(
        tracking_json if isinstance(tracking_json, dict) else None,
        str(supplier_order_id) if supplier_order_id else None,
    )
    store_timeline = store_timeline_for_journey(
        tracking_json if isinstance(tracking_json, dict) else None,
    )
    russian_post_timeline = russian_post_timeline_for_journey(
        tracking_json if isinstance(tracking_json, dict) else None,
        str(supplier_tracking_id) if supplier_tracking_id else None,
    )

    outbox = outbox_by_key or {}
    customer_notifications = extract_customer_notifications(event_rows)
    shipment_ids: list[int] = []
    seen_shipment_ids: set[int] = set()
    for row in shipments or ():
        raw_id = getattr(row, "id", None)
        if raw_id is None:
            continue
        shipment_id = int(raw_id)
        if shipment_id in seen_shipment_ids:
            continue
        seen_shipment_ids.add(shipment_id)
        shipment_ids.append(shipment_id)

    composition_tg = resolve_composition_tg_state(customer_notifications)

    availability_done = availability in {"confirmed", "not_required"}
    payment_done = payment_state in {"paid", "late_paid_after_cancel"}
    has_new_flow = _has_new_shipment_flow(supplier_orders, shipments)
    active_so_n = len(_active_supplier_orders(supplier_orders))
    placed_so_n = len(_placed_supplier_orders(supplier_orders))
    assembly_done = status in {
        "assembling",
        "delivery",
        "completed",
    }
    if has_new_flow:
        assembly_done = assembly_done or (
            active_so_n > 0 and placed_so_n == active_so_n
        )
    else:
        assembly_done = assembly_done or bool(supplier_order_id)
    delivery_done = status == "completed"
    completed = [True, availability_done, payment_done, assembly_done, delivery_done]
    is_terminal_error = status in {"cancelled", "failed"}
    current_index = next((idx for idx, done in enumerate(completed) if not done), 4)

    event_dates: dict[str, str] = {}
    notification_count = 0
    for row in event_rows:
        event_type = str(row.get("event_type") or "")
        created_at_display = row.get("created_at_display")
        if event_type and created_at_display and event_type not in event_dates:
            event_dates[event_type] = str(created_at_display)
        if event_type == "customer_notified":
            notification_count += 1

    if availability == "not_required":
        availability_subtitle = "не требуется"
    elif availability == "confirmed":
        availability_subtitle = "подтверждено"
    elif availability == "unavailable":
        availability_subtitle = "недоступно"
    else:
        availability_subtitle = "ожидает проверки"

    availability_facts = _availability_journey_facts(availability, event_rows)

    payment_method = (
        getattr(order, "payment_method_label", None)
        or getattr(order, "payment_provider", None)
        or "SBP"
    )
    if payment_done:
        payment_subtitle = f"{payment_method} · получена"
    else:
        payment_subtitle = "ожидается"

    if has_new_flow:
        assembly_subtitle, assembly_facts = _new_flow_assembly_copy(
            status, supplier_orders
        )
        delivery_subtitle, delivery_facts = _new_flow_delivery_copy(
            delivery_done, status, shipments
        )
    elif supplier_order_id:
        assembly_subtitle = "TP оформлен"
        assembly_facts = [str(supplier_order_id)]
        if delivery_done:
            delivery_subtitle = "завершена"
        elif supplier_tracking_id:
            delivery_subtitle = "в пути · DHL"
        else:
            delivery_subtitle = "ожидается"
        delivery_facts = [str(supplier_tracking_id)] if supplier_tracking_id else []
    else:
        assembly_subtitle = "не начата"
        assembly_facts = ["Нужен номер поставщика"]
        if delivery_done:
            delivery_subtitle = "завершена"
        elif supplier_tracking_id:
            delivery_subtitle = "в пути · DHL"
        else:
            delivery_subtitle = "ожидается"
        delivery_facts = [str(supplier_tracking_id)] if supplier_tracking_id else []

    if availability == "confirmed":
        availability_date_types: tuple[str, ...] = (
            "availability_confirmed",
            "availability_stock_check_saved",
        )
    elif availability == "unavailable":
        availability_date_types = (
            "availability_rejected",
            "availability_stock_check_saved",
        )
    elif availability_done:
        availability_date_types = ("availability_confirmed",)
    else:
        availability_date_types = ("availability_confirmation_requested",)

    definitions = [
        (
            "Клиент",
            "оформил",
            "order_created",
            [],
        ),
        (
            "Наличие",
            availability_subtitle,
            availability_date_types[0],
            availability_facts,
        ),
        (
            "Оплата",
            payment_subtitle,
            "payment_accepted",
            [],
        ),
        (
            "Сборка",
            assembly_subtitle,
            "assembly_started",
            assembly_facts,
        ),
        (
            "Доставка",
            delivery_subtitle,
            "delivery_started",
            delivery_facts,
        ),
    ]
    stages: list[dict[str, object]] = []
    for index, (title, subtitle, event_type, facts) in enumerate(definitions):
        state = "done" if completed[index] else "pending"
        if not completed[index] and index == current_index:
            state = "error" if is_terminal_error else "current"
        stage_date = event_dates.get(event_type)
        if index == 1:
            stage_date = _journey_event_date(event_dates, *availability_date_types)
        stage_key = JOURNEY_STAGE_KEYS[index]
        stage_channels = resolve_stage_channels(
            stage_key,
            order,
            customer_notifications,
            outbox,
            shipment_ids,
        )
        stages.append(
            {
                "number": index + 1,
                "title": title,
                "subtitle": subtitle,
                "state": state,
                "facts": facts,
                "notifications": _journey_step_notifications(
                    stage_key,
                    stage_channels,
                    event_rows,
                    composition_tg,
                ),
                "notify_badges": _journey_client_notify_badges(
                    stage_key,
                    availability,
                    stage_channels,
                ),
                "date": stage_date,
            }
        )
    progress_percent = 0
    if current_index > 0:
        progress_percent = min(100, round((current_index / 4) * 100))
    return {
        "stages": stages,
        "current_index": current_index,
        "progress_percent": progress_percent,
        "customer_notification_count": notification_count,
        "supplier_timeline": supplier_timeline,
        "store_timeline": store_timeline,
        "carrier_timeline": carrier_timeline,
        "russian_post_timeline": russian_post_timeline,
    }


# Форматирует значение для отображения.
def _fmt(value: object) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


# Формирует строки изменений для события истории заказа.
def _item_change_lines(
    before: list[dict[str, object]],
    after: list[dict[str, object]],
) -> list[dict[str, str]]:
    # Создаем словарь предыдущих значений по ID.
    before_map = {item["id"]: item for item in before if "id" in item}
    # Создаем словарь новых значений по ID.
    after_map = {item["id"]: item for item in after if "id" in item}
    # Создаем список строк изменений.
    lines: list[dict[str, str]] = []
    # Проходим по всем ID в порядке возрастания.
    item_ids = sorted(
        {int(k) for k in set(before_map) | set(after_map) if isinstance(k, int)}
    )
    for item_id in item_ids:
        # Получаем предыдущее и новое значение по ID.
        b = before_map.get(item_id, {})
        a = after_map.get(item_id, {})
        # Создаем список частей изменения.
        parts: list[str] = []
        # Если количество отличается, добавляем строку с изменением количества.
        if b.get("quantity") != a.get("quantity"):
            parts.append(
                f"кол-во {_fmt(b.get('quantity'))} → {_fmt(a.get('quantity'))}"
            )
        if b.get("unit_price") != a.get("unit_price"):
            # Если цена отличается, добавляем строку с изменением цены.
            parts.append(
                f"цена {_fmt(b.get('unit_price'))} → {_fmt(a.get('unit_price'))}"
            )
        # Если есть изменения, добавляем строку с изменением позиции.
        if parts:
            # Создаем строку с изменением позиции.
            lines.append(
                {
                    "label": f"Позиция #{item_id}",
                    "before": "—",
                    "after": ", ".join(parts),
                }
            )
    return lines


# Формирует строки изменений для события истории заказа.
def _order_event_change_lines(
    payload: dict[str, object] | None,
    status_labels: dict[str, str],
) -> list[dict[str, str]]:
    if not payload:
        return []

    lines: list[dict[str, str]] = []
    if payload.get("manual") and payload.get("channel"):
        channel_raw = str(payload.get("channel"))
        channel_label = {
            "telegram": "Telegram",
            "email": "Email",
        }.get(channel_raw, channel_raw)
        lines.append({"label": "Канал", "before": "—", "after": channel_label})

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        lines.append({"label": "Сообщение", "before": "—", "after": message.strip()})
    if lines:
        return lines

    before = payload.get("before")
    after = payload.get("after")

    # Если статусы изменились, добавляем строку с изменением статуса.
    if isinstance(before, str) and isinstance(after, str):
        return [
            {
                "label": "Статус",
                "before": status_labels.get(before, before),
                "after": status_labels.get(after, after),
            }
        ]

    # Если изменились позиции, добавляем строку с изменением позиций.
    if isinstance(before, dict) and isinstance(after, dict):
        field_lines: list[dict[str, str]] = []
        for key in after:
            # Получаем предыдущее и новое значение по ключу.
            b_val = before.get(key)
            a_val = after.get(key)
            if b_val == a_val:
                continue
            field_lines.append(
                {
                    "label": DELIVERY_FIELD_LABELS.get(key, key),
                    "before": _fmt(b_val),
                    "after": _fmt(a_val),
                }
            )
        return field_lines

    # Если изменились позиции, формируем строки изменений для события истории заказа.
    if isinstance(before, list) and isinstance(after, list):
        return _item_change_lines(before, after)

    return []


# Форматирует события истории заказа.
def format_order_event_rows(
    events: list[OrderEventSchema],
    event_labels: dict[str, str],
    status_labels: dict[str, str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for event in events:
        technical_lines: list[str] = []
        if event.event_type == "payment_accepted" and event.payload_json:
            provider_status = event.payload_json.get("payment_status")
            if provider_status:
                technical_lines.append(f"Статус провайдера: {provider_status}")
        rows.append(
            {
                "event_type": event.event_type,
                "title": event_labels.get(event.event_type, event.event_type),
                "message": (
                    None
                    if event.event_type == "payment_accepted"
                    else event.event_message
                ),
                "created_by": event.created_by,
                "created_at_display": event.created_at_display,
                "changes": _order_event_change_lines(
                    event.payload_json,
                    status_labels,
                ),
                "payload_json": event.payload_json,
                "technical_lines": technical_lines,
            }
        )
    return rows
