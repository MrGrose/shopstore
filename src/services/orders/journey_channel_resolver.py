from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from src.models.notification_outbox import NotificationOutboxStatus
from src.models.order import AvailabilityConfirmationStatus, OrderStatus
from src.services.notifications.customer_notification_keys import (
    assembly_notify_key,
    availability_notify_key,
    customer_outbox_keys_for_journey,
    finalize_notify_key,
    payment_received_key,
    shipment_delivered_notify_key,
)

# Тип для ключа этапа заказа.
JourneyStageKey = Literal["created", "availability", "payment", "assembly", "delivery"]

# Ключи этапов заказа.
JOURNEY_STAGE_KEYS: tuple[JourneyStageKey, ...] = (
    "created",
    "availability",
    "payment",
    "assembly",
    "delivery",
)

# Состояния канала.
ChannelState = Literal["sent", "waiting", "error", "na"]
# Состояния ЛК.
LkState = Literal["sent", "na"]

# Состояния очереди outbox.
_OUTBOX_WAITING = {
    NotificationOutboxStatus.PENDING,
    NotificationOutboxStatus.PROCESSING,
}

StageKeyBuilder = Callable[[int], str]

# Строители ключей для этапов заказа.
_STAGE_KEY_BUILDERS: dict[JourneyStageKey, StageKeyBuilder] = {
    "availability": availability_notify_key,
    "payment": payment_received_key,
    "assembly": assembly_notify_key,
    "delivery": finalize_notify_key,
}


# Запись о событии уведомления клиенту.
@dataclass(frozen=True)
class CustomerNotificationRecord:
    template: str | None
    idempotency_key: str | None
    channel: str | None = "telegram"


# Снимок каналов для одного этапа journey.
@dataclass(frozen=True)
class StageChannelSnapshot:
    tg: ChannelState
    email: ChannelState
    lk: LkState
    telegram_enabled: bool
    email_enabled: bool


# Политика для этапа заказа.
@dataclass(frozen=True)
class StageTgPolicy:
    mode: Literal["na", "required", "optional"]
    templates: tuple[str, ...]
    keys: tuple[str, ...] = ()


# Политика для этапа заказа.
JOURNEY_CHANNEL_POLICY: dict[JourneyStageKey, StageTgPolicy] = {
    "created": StageTgPolicy(mode="na", templates=()),
    "availability": StageTgPolicy(
        mode="optional",
        templates=(
            "availability.check",
            "availability.confirmed",
            "availability.unavailable",
            "order_status",
        ),
    ),
    "payment": StageTgPolicy(
        mode="required",
        templates=("payment.received", "payment.late.received"),
    ),
    "assembly": StageTgPolicy(
        mode="optional",
        templates=("order_status",),
    ),
    "delivery": StageTgPolicy(
        mode="optional",
        templates=("order_status",),
    ),
}


# Собирает idempotency keys и templates для этапа заказа.
def _stage_policy(order_id: int, stage: JourneyStageKey) -> StageTgPolicy:
    base = JOURNEY_CHANNEL_POLICY[stage]
    key_builder = _STAGE_KEY_BUILDERS.get(stage)
    if key_builder is None:
        return base
    key = key_builder(order_id)
    return StageTgPolicy(mode=base.mode, templates=base.templates, keys=(key,))


def _delivery_shipment_tg_policy(
    order_id: int, shipment_ids: Sequence[int]
) -> StageTgPolicy | None:
    keys: list[str] = []
    seen: set[str] = set()
    for shipment_id in shipment_ids:
        key = shipment_delivered_notify_key(order_id, int(shipment_id))
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        return None
    return StageTgPolicy(
        mode="optional",
        templates=("notify_order_status",),
        keys=tuple(keys),
    )


# Извлекает customer_notified из строк истории заказа.
def extract_customer_notifications(
    event_rows: Sequence[Mapping[str, object]],
) -> list[CustomerNotificationRecord]:
    records: list[CustomerNotificationRecord] = []
    for row in event_rows:
        if str(row.get("event_type") or "") != "customer_notified":
            continue
        payload = row.get("payload_json")
        payload_map = payload if isinstance(payload, dict) else {}
        template_raw = payload_map.get("template")
        template = str(template_raw) if template_raw else None
        key_raw = payload_map.get("idempotency_key")
        idempotency_key = str(key_raw) if key_raw else None
        channel_raw = payload_map.get("channel")
        channel = str(channel_raw) if channel_raw else None
        records.append(
            CustomerNotificationRecord(
                template=template,
                idempotency_key=idempotency_key,
                channel=channel,
            )
        )
    return records


def _idempotency_key_matches(record_key: str, policy_keys: tuple[str, ...]) -> bool:
    if not record_key or not policy_keys:
        return False
    for key in policy_keys:
        if record_key == key or record_key.startswith(f"{key}:"):
            return True
    return False


def _record_targets_channel(
    record: CustomerNotificationRecord,
    channel: Literal["telegram", "email"],
) -> bool:
    if record.channel is None:
        return channel == "telegram"
    record_channel = record.channel
    if channel == "telegram" and record_channel == "customer":
        return True
    return record_channel == channel


# Проверяет, что уведомление относится к этапу (template + idempotency key).
def _notification_matches_stage(
    record: CustomerNotificationRecord,
    policy: StageTgPolicy,
    stage: JourneyStageKey,
) -> bool:
    if record.idempotency_key and policy.keys:
        if _idempotency_key_matches(record.idempotency_key, policy.keys):
            return True
    template = record.template or ""
    if not template or template not in policy.templates:
        return False
    if stage in {"delivery", "assembly", "availability"} and policy.keys:
        return False
    if stage == "payment" and template == "composition.changed":
        return False
    return True


# Состояние TG для этапа по событиям, outbox и политике.
def resolve_tg_state(
    stage: JourneyStageKey,
    order_id: int,
    notifications: list[CustomerNotificationRecord],
    outbox_by_key: Mapping[str, str],
    shipment_ids: Sequence[int] = (),
) -> ChannelState:
    policy = _stage_policy(order_id, stage)
    if stage == "delivery":
        delivery_policy = _delivery_shipment_tg_policy(order_id, shipment_ids)
        if delivery_policy is not None:
            policy = delivery_policy
    if policy.mode == "na":
        return "na"

    for record in notifications:
        if _record_targets_channel(record, "telegram") and _notification_matches_stage(
            record, policy, stage
        ):
            return "sent"

    key_states: list[str] = []
    for key in policy.keys:
        if key in outbox_by_key:
            key_states.append(outbox_by_key[key])
        telegram_key = f"{key}:telegram"
        if telegram_key in outbox_by_key:
            key_states.append(outbox_by_key[telegram_key])
    if any(status in _OUTBOX_WAITING for status in key_states):
        return "waiting"
    if any(status == NotificationOutboxStatus.FAILED for status in key_states):
        return "error"
    if policy.mode == "required":
        return "waiting"
    return "na"


# Состояние ЛК для этапа — по полям заказа, не по событиям TG.
def resolve_lk_state(stage: JourneyStageKey, order: object) -> LkState:
    status = str(getattr(order, "status", "") or "").lower()
    availability = str(
        getattr(order, "availability_confirmation_status", "not_required")
        or "not_required"
    ).lower()
    payment_state = str(getattr(order, "payment_state", "not_started") or "")
    supplier_order_id = getattr(order, "supplier_order_id", None)
    supplier_tracking_id = getattr(order, "supplier_tracking_id", None)

    if stage == "created":
        return "sent"
    if stage == "availability":
        if availability in {
            AvailabilityConfirmationStatus.PENDING,
            AvailabilityConfirmationStatus.CONFIRMED,
            AvailabilityConfirmationStatus.UNAVAILABLE,
            AvailabilityConfirmationStatus.NOT_REQUIRED,
        }:
            return "sent"
        return "na"
    if stage == "payment":
        if getattr(order, "payment_paid_at", None) is not None:
            return "sent"
        if payment_state in {"paid", "late_paid_after_cancel"}:
            return "sent"
        return "na"
    if stage == "assembly":
        if supplier_order_id or status in {
            OrderStatus.ASSEMBLING,
            OrderStatus.DELIVERY,
            OrderStatus.COMPLETED,
        }:
            return "sent"
        return "na"
    if stage == "delivery":
        if supplier_tracking_id or status in {
            OrderStatus.DELIVERY,
            OrderStatus.COMPLETED,
        }:
            return "sent"
        return "na"
    return "na"


# TG для уведомления об изменении состава на шаге оплаты.
def resolve_composition_tg_state(
    notifications: list[CustomerNotificationRecord],
) -> ChannelState:
    for record in notifications:
        if record.template == "composition.changed":
            return "sent"
    return "na"


# Снимок TG/ЛК для одного этапа journey.
def resolve_stage_channels(
    stage: JourneyStageKey,
    order: object,
    notifications: list[CustomerNotificationRecord],
    outbox_by_key: Mapping[str, str],
    shipment_ids: Sequence[int] = (),
) -> StageChannelSnapshot:
    order_id = int(getattr(order, "id"))
    selected_channels = set(getattr(order, "notification_channels", []) or [])
    if not selected_channels:
        selected_channels = {"telegram"}
    email_enabled = "email" in set(getattr(order, "notification_channels", []) or [])
    stage_policy = _stage_policy(order_id, stage)
    email_key = (
        f"{stage_policy.keys[0]}:email" if email_enabled and stage_policy.keys else None
    )
    email_states = (
        [outbox_by_key[email_key]] if email_key and email_key in outbox_by_key else []
    )
    email_state: ChannelState = "na"
    if email_enabled and stage_policy.mode != "na":
        if any(
            _record_targets_channel(record, "email")
            and _notification_matches_stage(record, stage_policy, stage)
            for record in notifications
        ):
            email_state = "sent"
        elif any(status == NotificationOutboxStatus.SENT for status in email_states):
            email_state = "sent"
        elif any(status in _OUTBOX_WAITING for status in email_states):
            email_state = "waiting"
        elif any(status == NotificationOutboxStatus.FAILED for status in email_states):
            email_state = "error"
        elif stage_policy.mode == "required":
            email_state = "waiting"
    return StageChannelSnapshot(
        tg=(
            resolve_tg_state(
                stage, order_id, notifications, outbox_by_key, shipment_ids
            )
            if "telegram" in selected_channels
            else "na"
        ),
        email=email_state,
        lk=resolve_lk_state(stage, order),
        telegram_enabled="telegram" in selected_channels,
        email_enabled=email_enabled,
    )


# Бейджи TG/EM/ЛК для шага карты заказа.
def build_stage_notify_badges(
    snapshot: StageChannelSnapshot,
) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    for channel, state in (
        ("TG", snapshot.tg),
        ("EM", snapshot.email),
        ("ЛК", snapshot.lk),
    ):
        if state == "na":
            continue
        if channel == "ЛК":
            badge_state = "sent" if state == "sent" else "na"
        else:
            badge_state = state
        badges.append({"channel": channel, "state": badge_state})
    return badges


# Все outbox keys клиента для загрузки в админке.
def customer_outbox_keys_for_order(
    order_id: int,
    shipment_ids: Sequence[int] = (),
) -> list[str]:
    return customer_outbox_keys_for_journey(order_id, shipment_ids)


# Подпись канала для текстовых строк уведомлений в journey.
def channel_label(token: str, state: ChannelState | LkState) -> str:
    if state == "sent":
        return f"{token} ✓"
    if state == "waiting":
        return f"{token} …"
    if state == "error":
        return f"{token} !"
    return f"{token} —"


# Строка «Клиент: TG · EM · ЛК» для шага journey.
def client_notify_line(snapshot: StageChannelSnapshot) -> str:
    tg_state: ChannelState | LkState = snapshot.tg
    lk_state: ChannelState | LkState = snapshot.lk
    labels = [
        channel_label("TG", tg_state) if snapshot.telegram_enabled else None,
        channel_label("EM", snapshot.email) if snapshot.email_enabled else None,
        channel_label("ЛК", lk_state),
    ]
    return "Клиент: " + " · ".join(label for label in labels if label is not None)
