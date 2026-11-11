from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict, cast

from src.models.notification_outbox import NotificationOutboxStatus
from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.schemas.order import OrderSchema
from src.services.notifications.customer_notification_keys import (
    assembly_notify_key,
    availability_notify_key,
    finalize_notify_key,
    payment_received_key,
)
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import (
    packing_assembly_complete,
    supplier_order_allocated_qty,
)

RailStepState = Literal["active", "done", "locked", "hidden"]
ActiveStep = Literal[
    "composition",
    "availability",
    "payment",
    "assembly",
    "delivery",
    "finalize",
    "terminal",
]

RAIL_STEP_IDS = (
    "composition",
    "availability",
    "payment",
    "assembly",
    "delivery",
    "finalize",
    "status_manual",
    "notify_freeform",
    "comment",
)

FLOW_STEP_IDS = (
    "availability",
    "composition",
    "payment",
    "assembly",
    "delivery",
)

_STEP_TITLES: dict[str, str] = {
    "availability": "Наличие",
    "composition": "Состав и стоимость",
    "payment": "Оплата",
    "assembly": "Сборка",
    "delivery": "Доставка",
    "finalize": "Завершение",
}

_STEP_NUMBERS: dict[str, int] = {
    "availability": 1,
    "composition": 2,
    "payment": 3,
    "assembly": 4,
    "delivery": 5,
    "finalize": 6,
}


class _StepKw(TypedDict):
    order_id: int
    outbox_by_key: dict[str, str] | None


_PAYMENT_WAITING_MESSAGE = (
    "Действие не требуется — клиент оплачивает сам. "
    "Уведомление не нужно. Дальше — сборка у поставщика."
)


class RailStepConfig(TypedDict):
    state: RailStepState
    open: bool
    hint: str | None
    notify_visible: bool
    notify_default: bool
    notify_hint: str | None
    notify_outbox_pending: bool
    title: str
    step_number: int
    waiting: bool
    body_editable: bool
    queue_summary: str | None
    waiting_message: str | None


class AdminActionRail(TypedDict):
    active_step: ActiveStep
    callout: str | None
    alert: str | None
    flow_steps: tuple[str, ...]
    steps: dict[str, RailStepConfig]


_NOTIFY_CONFIG: dict[str, tuple[bool, bool]] = {
    "availability": (True, True),
    "composition": (True, True),
    "payment": (False, False),
    "assembly": (True, True),
    "delivery": (False, False),
    "finalize": (True, False),
    "status_manual": (True, False),
    "notify_freeform": (False, False),
    "comment": (False, False),
}

_NOTIFY_HINTS: dict[str, str] = {
    "availability": "Результат проверки наличия",
    "composition": "Изменение состава заказа",
    "assembly": "Передан в сборку у поставщика",
    "finalize": "Заказ выполнен",
    "status_manual": "Смена статуса заказа",
}

_STEP_OUTBOX_KEY = {
    "availability": availability_notify_key,
    "payment": payment_received_key,
    "assembly": assembly_notify_key,
    "finalize": finalize_notify_key,
}

_OUTBOX_WAITING = frozenset(
    {
        NotificationOutboxStatus.PENDING,
        NotificationOutboxStatus.PROCESSING,
    }
)

_PAYMENT_DONE_STATES = frozenset({"paid", "late_paid_after_cancel"})
_TERMINAL_STATUSES = frozenset(
    {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.FAILED}
)


# True, если для шага rail в outbox уже есть pending/processing запись.
def _outbox_pending_for_step(
    step_id: str,
    order_id: int,
    outbox_by_key: dict[str, str] | None,
) -> bool:
    if not outbox_by_key or order_id <= 0:
        return False
    key_fn = _STEP_OUTBOX_KEY.get(step_id)
    if key_fn is None:
        return False
    key = key_fn(order_id)
    for candidate in (key, f"{key}:telegram"):
        if outbox_by_key.get(candidate) in _OUTBOX_WAITING:
            return True
    return False


# Собирает конфиг одного шага guided rail для шаблона админки.
def _step(
    state: RailStepState,
    step_id: str,
    open: bool | None = None,
    hint: str | None = None,
    order_id: int = 0,
    outbox_by_key: dict[str, str] | None = None,
    waiting: bool = False,
    body_editable: bool = False,
    queue_summary: str | None = None,
    waiting_message: str | None = None,
) -> RailStepConfig:
    notify_visible, notify_default = _NOTIFY_CONFIG.get(step_id, (False, False))
    if open is None:
        open = state == "active"
    return {
        "state": state,
        "open": open,
        "hint": hint,
        "notify_visible": notify_visible,
        "notify_default": notify_default,
        "notify_hint": _NOTIFY_HINTS.get(step_id) if notify_visible else None,
        "notify_outbox_pending": (
            _outbox_pending_for_step(step_id, order_id, outbox_by_key)
            if notify_visible
            else False
        ),
        "title": _STEP_TITLES.get(step_id, step_id),
        "step_number": _STEP_NUMBERS.get(step_id, 0),
        "waiting": waiting,
        "body_editable": body_editable,
        "queue_summary": queue_summary,
        "waiting_message": waiting_message,
    }


# True, если заказ считается оплаченным для rail.
def _is_paid(order: object, payment_state: str) -> bool:
    if payment_state in _PAYMENT_DONE_STATES:
        return True
    return getattr(order, "payment_paid_at", None) is not None


# True, если оплата пришла после автоотмены заказа.
def _is_late_paid(order: object, payment_state: str) -> bool:
    if payment_state == "late_paid_after_cancel":
        return True
    return bool(getattr(order, "late_payment_after_auto_cancel", False))


# Текст предупреждения для терминального или заблокированного заказа.
def _terminal_alert(
    status: str,
    availability: str,
    late_paid: bool,
    assembly_locked: bool,
) -> str | None:
    if availability == AvailabilityConfirmationStatus.UNAVAILABLE:
        return "Товар недоступен. Дальнейшие шаги закрыты."
    if late_paid and assembly_locked:
        return (
            "Оплата поступила после автоотмены. Сборка недоступна — "
            "свяжитесь с клиентом."
        )
    if status == OrderStatus.CANCELLED:
        return "Заказ отменён. Действия по цепочке недоступны."
    if status == OrderStatus.FAILED:
        return "Заказ в статусе «не выполнен». Действия по цепочке недоступны."
    if status == OrderStatus.COMPLETED:
        return None
    return None


# Подсказка в очереди, почему шаг цепочки ещё недоступен.
def _locked_hint(step_id: str, availability: str, payment_done: bool) -> str | None:
    if step_id == "payment" and availability == AvailabilityConfirmationStatus.PENDING:
        return "Оплата станет доступна клиенту после проверки наличия."
    if step_id == "assembly" and not payment_done:
        return "Можно собрать заказы поставщика до оплаты."
    if step_id == "delivery":
        return "Доставка станет доступна после оформления всех посылок."
    if step_id == "finalize":
        return "Завершение станет доступно после доставки."
    return None


# Состояние шага «Состав и стоимость» в guided rail.
def _composition_state(
    composition_edit_allowed: bool,
    payment_done: bool,
    terminal: bool,
    active_step: ActiveStep,
    order_id: int,
    outbox_by_key: dict[str, str] | None,
    item_count: int = 0,
) -> RailStepConfig:
    summary = f"{item_count} поз." if item_count else None
    if terminal:
        return _step(
            "done" if payment_done else "locked",
            step_id="composition",
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            queue_summary=summary,
        )
    if payment_done:
        return _step(
            "done",
            step_id="composition",
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            queue_summary=summary,
        )
    if active_step == "payment":
        return _step(
            "locked",
            open=False,
            hint=(
                "Можно изменить состав до оплаты" if composition_edit_allowed else None
            ),
            step_id="composition",
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            body_editable=True,
            queue_summary=summary,
        )
    if composition_edit_allowed:
        return _step(
            "locked",
            open=False,
            hint="Изменение состава — на шаге оплаты",
            step_id="composition",
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            queue_summary=summary,
        )
    return _step(
        "locked",
        step_id="composition",
        order_id=order_id,
        outbox_by_key=outbox_by_key,
        queue_summary=summary,
    )


# Состояние шага основной цепочки (наличие → доставка).
def _step_state_for_flow(
    step_id: str,
    active_step: ActiveStep,
    done: bool,
    availability: str,
    payment_done: bool,
    terminal: bool,
    order_id: int,
    outbox_by_key: dict[str, str] | None,
) -> RailStepConfig:
    hint = _locked_hint(
        step_id,
        availability=availability,
        payment_done=payment_done,
    )
    if terminal:
        state: RailStepState = "done" if done else "locked"
        return _step(
            state,
            hint=hint if state == "locked" else None,
            step_id=step_id,
            order_id=order_id,
            outbox_by_key=outbox_by_key,
        )
    if step_id == active_step:
        waiting = step_id == "payment" and not payment_done
        return _step(
            "active",
            step_id=step_id,
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            waiting=waiting,
            waiting_message=_PAYMENT_WAITING_MESSAGE if waiting else None,
        )
    if done:
        return _step(
            "done",
            step_id=step_id,
            order_id=order_id,
            outbox_by_key=outbox_by_key,
        )
    if step_id == "assembly" and not payment_done:
        return _step(
            "locked",
            hint=hint,
            step_id=step_id,
            order_id=order_id,
            outbox_by_key=outbox_by_key,
            body_editable=True,
            open=False,
        )
    return _step(
        "locked",
        hint=hint,
        step_id=step_id,
        order_id=order_id,
        outbox_by_key=outbox_by_key,
    )


# Заполняет краткие подписи шагов в свёрнутой очереди rail.
def _apply_queue_summaries(
    steps: dict[str, RailStepConfig],
    order: object,
    availability: str,
    payment_done: bool,
    packing: Mapping[str, object] | None = None,
    shipment_summary: str | None = None,
) -> None:
    av_labels = {
        AvailabilityConfirmationStatus.CONFIRMED.value: "Подтверждено",
        AvailabilityConfirmationStatus.NOT_REQUIRED.value: "Не требуется",
        AvailabilityConfirmationStatus.PENDING.value: "Ожидает",
        AvailabilityConfirmationStatus.UNAVAILABLE.value: "Недоступен",
    }
    if steps["availability"]["state"] == "done":
        steps["availability"]["queue_summary"] = av_labels.get(
            availability, availability
        )
    if steps["payment"]["state"] == "done" and payment_done:
        steps["payment"]["queue_summary"] = "Оплачен"
    supplier_order_id = getattr(order, "supplier_order_id", None)
    status = str(getattr(order, "status", "") or "").lower()
    packing = packing or {}
    placed = packing.get("placed_count")
    placeable = packing.get("placeable_count")
    if steps["assembly"]["state"] == "done":
        if placeable:
            steps["assembly"]["queue_summary"] = f"{placed} / {placeable} оформлены"
        elif supplier_order_id:
            steps["assembly"]["queue_summary"] = f"#{supplier_order_id}"
    elif placeable:
        steps["assembly"]["queue_summary"] = f"Собрано: {placed} / {placeable}"
    if steps["delivery"]["state"] == "done":
        if status == OrderStatus.COMPLETED:
            steps["delivery"]["queue_summary"] = "Доставлен"
        elif shipment_summary:
            steps["delivery"]["queue_summary"] = shipment_summary
        elif supplier_order_id:
            steps["delivery"]["queue_summary"] = "В работе"
    elif shipment_summary:
        steps["delivery"]["queue_summary"] = shipment_summary
    if steps["finalize"]["state"] == "done" and status == OrderStatus.COMPLETED:
        steps["finalize"]["queue_summary"] = "Выполнен"


# Сборка done по packing, иначе legacy первый TP / status.
def _assembly_complete(
    status: str,
    legacy_tp: object,
    packing: Mapping[str, object] | None,
    supplier_orders: Sequence[object] | None,
) -> bool:
    if status in {OrderStatus.DELIVERY, OrderStatus.COMPLETED}:
        return True
    orders = list(supplier_orders or [])
    if orders:
        fully = bool((packing or {}).get("fully_allocated"))
        pairs = [
            (
                str(getattr(so, "status", "") or ""),
                supplier_order_allocated_qty(so),
            )
            for so in orders
        ]
        return packing_assembly_complete(fully, pairs)
    return bool(legacy_tp)


# Собирает guided action-rail для карточки заказа в админке.
def resolve_admin_action_rail(
    order: object,
    composition_edit_allowed: bool = True,
    outbox_by_key: dict[str, str] | None = None,
    packing: Mapping[str, object] | None = None,
    supplier_orders: Sequence[object] | None = None,
    shipment_summary: str | None = None,
) -> AdminActionRail:
    order_id = int(getattr(order, "id", 0) or 0)
    item_count = len(getattr(order, "items", None) or [])
    status = str(getattr(order, "status", "") or "").lower()
    availability = str(
        getattr(order, "availability_confirmation_status", "not_required")
        or AvailabilityConfirmationStatus.NOT_REQUIRED
    ).lower()
    payment_state = str(getattr(order, "payment_state", "not_started") or "")
    supplier_order_id = getattr(order, "supplier_order_id", None)

    terminal = (
        status in _TERMINAL_STATUSES
        or availability == AvailabilityConfirmationStatus.UNAVAILABLE
    )
    late_paid = _is_late_paid(order, payment_state)
    payment_done = _is_paid(order, payment_state)
    availability_done = availability in {
        AvailabilityConfirmationStatus.CONFIRMED,
        AvailabilityConfirmationStatus.NOT_REQUIRED,
    }
    assembly_done = _assembly_complete(
        status, supplier_order_id, packing, supplier_orders
    )
    delivery_done = status == OrderStatus.COMPLETED
    delivery_step_done = delivery_done
    delivery_monitoring = assembly_done and not delivery_done
    can_assemble = OrderService.can_start_assembling(
        cast(OrderSchema, order),
        supplier_orders=supplier_orders,
        packing=packing,
    )
    assembly_locked = late_paid and not can_assemble

    active_step: ActiveStep
    callout: str | None

    if terminal or assembly_locked:
        active_step = "terminal"
        callout = None
    elif availability == AvailabilityConfirmationStatus.PENDING:
        active_step = "availability"
        callout = "Проверьте наличие и сохраните решение."
    elif not payment_done:
        active_step = "payment"
        callout = "Ожидается оплата от клиента."
    elif not assembly_done:
        active_step = "assembly"
        callout = "Добавьте посылку, сохраните состав и укажите TP номер."
    elif assembly_done and not delivery_done:
        active_step = "delivery"
        if status == OrderStatus.DELIVERY:
            callout = (
                "Отслеживайте посылки. Когда клиент получил заказ — завершите его ниже."
            )
        else:
            callout = (
                "Проверьте посылки. Трек появится после синхронизации с перевозчиком."
            )
    else:
        active_step = "terminal"
        callout = None

    alert = _terminal_alert(
        status,
        availability,
        late_paid=late_paid,
        assembly_locked=assembly_locked,
    )

    step_kw: _StepKw = {"order_id": order_id, "outbox_by_key": outbox_by_key}
    steps: dict[str, RailStepConfig] = {
        "composition": _composition_state(
            composition_edit_allowed=composition_edit_allowed,
            payment_done=payment_done,
            terminal=terminal or assembly_locked,
            active_step=active_step,
            item_count=item_count,
            **step_kw,
        ),
        "availability": _step_state_for_flow(
            "availability",
            active_step,
            done=availability_done,
            availability=availability,
            payment_done=payment_done,
            terminal=terminal or assembly_locked,
            **step_kw,
        ),
        "payment": _step_state_for_flow(
            "payment",
            active_step,
            done=payment_done,
            availability=availability,
            payment_done=payment_done,
            terminal=terminal or assembly_locked,
            **step_kw,
        ),
        "assembly": _step_state_for_flow(
            "assembly",
            active_step,
            done=assembly_done,
            availability=availability,
            payment_done=payment_done,
            terminal=terminal or assembly_locked,
            **step_kw,
        ),
        "delivery": _step_state_for_flow(
            "delivery",
            active_step,
            done=delivery_step_done,
            availability=availability,
            payment_done=payment_done,
            terminal=terminal or assembly_locked,
            **step_kw,
        ),
        "finalize": _step(
            "hidden",
            step_id="finalize",
            **step_kw,
        ),
        "status_manual": _step(
            "locked",
            open=False,
            hint="Только для исключений",
            step_id="status_manual",
            **step_kw,
        ),
        "notify_freeform": _step(
            "done",
            open=False,
            step_id="notify_freeform",
            **step_kw,
        ),
        "comment": _step("done", open=False, step_id="comment", **step_kw),
    }

    if assembly_locked and steps["assembly"]["state"] != "done":
        steps["assembly"] = _step(
            "locked",
            hint="Сборка недоступна после оплаты по отменённому заказу.",
            step_id="assembly",
            **step_kw,
        )

    _apply_queue_summaries(
        steps,
        order,
        availability=availability,
        payment_done=payment_done,
        packing=packing,
        shipment_summary=shipment_summary,
    )

    if delivery_monitoring and steps["delivery"]["state"] != "active":
        delivery_step = dict(steps["delivery"])
        delivery_step["open"] = True
        if shipment_summary:
            delivery_step["queue_summary"] = shipment_summary
        elif not delivery_step.get("queue_summary"):
            delivery_step["queue_summary"] = "В работе"
        steps["delivery"] = delivery_step  # type: ignore[assignment]

    return {
        "active_step": active_step,
        "callout": callout,
        "alert": alert,
        "flow_steps": FLOW_STEP_IDS,
        "steps": steps,
    }
