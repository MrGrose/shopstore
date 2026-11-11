from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from src.utils.datetime_fmt import utc_now_naive

# Статусы оплаты.
PAYMENT_ACCEPTED_STATUS = "IPS_ACCEPTED"
# Статусы ожидания оплаты.
PAYMENT_WAIT_STATUSES: frozenset[str] = frozenset(
    {"QRCDATA_CREATED", "IN_PROCESS", "QRCDATA_IN_PROGRESS"}
)
# Статусы терминала попытки (оплачено / отклонено).
PAYMENT_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {PAYMENT_ACCEPTED_STATUS, "DECLINED"}
)
# Статусы ошибок оплаты.
PAYMENT_FAILED_STATUSES: frozenset[str] = frozenset({"DECLINED", "EXPIRED"})
# Статусы инициализации оплаты.
PAYMENT_INIT_STATUS = "CREATED"
# Статус инициализации оплаты.
PAYMENT_INIT_STATE_CREATING = "creating"
# Провайдер оплаты.
PAYMENT_PROVIDER_SBP = "sbp"
# Разрешённые переходы статусов оплаты.
ALLOWED_PROVIDER_TRANSITIONS: dict[str, frozenset[str]] = {
    PAYMENT_INIT_STATUS: frozenset(
        {
            "QRCDATA_CREATED",
            "IN_PROCESS",
            "QRCDATA_IN_PROGRESS",
            "DECLINED",
            PAYMENT_ACCEPTED_STATUS,
        }
    ),
    "QRCDATA_CREATED": frozenset(
        {
            "IN_PROCESS",
            "QRCDATA_IN_PROGRESS",
            "DECLINED",
            PAYMENT_ACCEPTED_STATUS,
        }
    ),
    "IN_PROCESS": frozenset(
        {
            "QRCDATA_IN_PROGRESS",
            "DECLINED",
            PAYMENT_ACCEPTED_STATUS,
        }
    ),
    "QRCDATA_IN_PROGRESS": frozenset(
        {
            "IN_PROCESS",
            "DECLINED",
            PAYMENT_ACCEPTED_STATUS,
        }
    ),
    "DECLINED": frozenset({PAYMENT_ACCEPTED_STATUS}),
    PAYMENT_ACCEPTED_STATUS: frozenset(),
}

# Состояния оплаты.
PaymentState = Literal[
    "paid",
    "waiting",
    "failed",
    "initializing",
    "not_started",
    "exhausted",
    "late_paid_after_cancel",
]
# Лейблы состояний оплаты.
PAYMENT_STATE_LABELS: dict[str, str] = {
    "paid": "Оплачено",
    "waiting": "Ожидает оплаты",
    "failed": "Оплата не прошла",
    "initializing": "Создаём оплату",
    "not_started": "Можно оплатить",
}
PAYMENT_EXHAUSTED_LABEL = "Лимит попыток исчерпан"


# Протокол для попытки оплаты.
class _PaymentAttemptLike(Protocol):
    provider_status: str | None
    paid_at: datetime | None
    qr_expires_at: datetime | None
    init_state: str
    provider_order_id: str | None


# Отображаемое состояние оплаты.
@dataclass(frozen=True)
class OrderPaymentDisplay:
    payment_state: PaymentState
    payment_label: str
    payment_method_label: str | None


# Разрешён ли переход provider status.
def is_provider_status_transition_allowed(
    current_status: str | None,
    new_status: str,
) -> bool:
    current = str(current_status or "").upper()
    new = str(new_status or "").upper()
    if not new:
        return False
    if current == new:
        return True
    if current == PAYMENT_ACCEPTED_STATUS:
        return False
    allowed = ALLOWED_PROVIDER_TRANSITIONS.get(current)
    if allowed is None:
        return True
    return new in allowed


# Истёк ли QR у попытки.
def attempt_qr_expired(
    qr_expires_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if qr_expires_at is None:
        return False
    check_at = now or utc_now_naive()
    return qr_expires_at <= check_at


# Жив ли QR попытки (можно возобновить оплату).
def attempt_qr_alive(
    attempt: _PaymentAttemptLike | None,
    now: datetime | None = None,
) -> bool:
    if attempt is None:
        return False
    if attempt.qr_expires_at is None:
        return False
    if attempt_qr_expired(attempt.qr_expires_at, now):
        return False
    status = str(attempt.provider_status or "").upper()
    if status in PAYMENT_TERMINAL_STATUSES:
        return False
    return status in PAYMENT_WAIT_STATUSES | {PAYMENT_INIT_STATUS}


# Незавершённая попытка до вызова провайдера — можно complete_provider.
def attempt_init_incomplete(attempt: _PaymentAttemptLike | None) -> bool:
    if attempt is None:
        return False
    if attempt.provider_order_id:
        return False
    status = str(attempt.provider_status or "").upper()
    if status in PAYMENT_TERMINAL_STATUSES:
        return False
    init_state = str(attempt.init_state or "").lower()
    return init_state == PAYMENT_INIT_STATE_CREATING


# Можно возобновить оплату по существующей попытке (живой QR или незавершённый init).
def attempt_payment_resumable(
    attempt: _PaymentAttemptLike | None,
    now: datetime | None = None,
) -> bool:
    return attempt_qr_alive(attempt, now) or attempt_init_incomplete(attempt)


# Исчерпан ли лимит попыток (5-я resumable попытка — не exhausted).
def payment_attempts_exhausted(
    attempts_used: int,
    limit: int,
    latest_attempt: _PaymentAttemptLike | None,
    now: datetime | None = None,
) -> bool:
    if attempts_used < limit:
        return False
    return not attempt_payment_resumable(latest_attempt, now)


# Просрочен ли срок оплаты заказа.
def payment_deadline_passed(
    payment_due_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if payment_due_at is None:
        return False
    return payment_due_at <= (now or utc_now_naive())


# Блокирует ли deadline новую оплату (живой QR — не блокирует).
def payment_deadline_blocks_payment(
    payment_due_at: datetime | None,
    latest_attempt: _PaymentAttemptLike | None,
    now: datetime | None = None,
) -> bool:
    if not payment_deadline_passed(payment_due_at, now):
        return False
    return not attempt_payment_resumable(latest_attempt, now)


# Есть ли у заказа QR для оплаты.
def _order_has_payment_qr(
    payment_qr_id: str | None,
    payment_qr_payload: str | None,
) -> bool:
    if payment_qr_id and str(payment_qr_id).strip():
        return True
    return bool(payment_qr_payload and str(payment_qr_payload).strip())


# Подпись способа оплаты по провайдеру.
def _payment_method_label(payment_provider: str | None) -> str | None:
    if str(payment_provider or "").lower() == PAYMENT_PROVIDER_SBP:
        return "СБП"
    return None


# Нормализует бизнес-состояние оплаты заказа для UI.
def normalize_order_payment(
    payment_paid_at: datetime | None,
    payment_status: str | None,
    payment_qr_id: str | None,
    payment_qr_payload: str | None,
    payment_provider: str | None,
    payment_order_id: str | None,
    payment_init_state: str | None = None,
) -> OrderPaymentDisplay:
    status = str(payment_status or "").upper()
    method_label = _payment_method_label(payment_provider)
    has_qr = _order_has_payment_qr(payment_qr_id, payment_qr_payload)

    if payment_paid_at is not None or status == PAYMENT_ACCEPTED_STATUS:
        state: PaymentState = "paid"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if status in PAYMENT_FAILED_STATUSES:
        state = "failed"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if has_qr or status in PAYMENT_WAIT_STATUSES:
        state = "waiting"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    init_state = str(payment_init_state or "").lower()
    payment_started = (
        status == PAYMENT_INIT_STATUS
        or bool(str(payment_provider or "").strip())
        or bool(str(payment_order_id or "").strip())
        or init_state == PAYMENT_INIT_STATE_CREATING
    )
    if payment_started:
        state = "initializing"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    state = "not_started"
    return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)


# Нормализует бизнес-состояние оплаты по последней попытке.
def normalize_order_payment_from_attempt(
    payment_paid_at: datetime | None,
    latest_attempt: _PaymentAttemptLike | None,
    payment_provider: str | None = None,
) -> OrderPaymentDisplay:
    method_label = _payment_method_label(payment_provider)

    if payment_paid_at is not None:
        state: PaymentState = "paid"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if latest_attempt is None:
        state = "not_started"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    now = utc_now_naive()
    status = str(latest_attempt.provider_status or "").upper()
    if status == PAYMENT_ACCEPTED_STATUS or latest_attempt.paid_at is not None:
        state = "paid"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if status in PAYMENT_FAILED_STATUSES:
        state = "failed"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    expired = attempt_qr_expired(latest_attempt.qr_expires_at, now)
    if expired:
        if status == "DECLINED":
            state = "failed"
            return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)
        if status in {PAYMENT_INIT_STATUS, *PAYMENT_WAIT_STATUSES}:
            state = "initializing"
            return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)
        state = "failed"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    qr_alive = (
        latest_attempt.qr_expires_at is not None
        and latest_attempt.qr_expires_at > now
        and status in PAYMENT_WAIT_STATUSES | {PAYMENT_INIT_STATUS}
    )
    if qr_alive:
        state = "waiting"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if status in PAYMENT_WAIT_STATUSES:
        state = "waiting"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if status == PAYMENT_INIT_STATUS or latest_attempt.init_state == "creating":
        state = "initializing"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    if latest_attempt.provider_order_id or latest_attempt.provider_status:
        state = "initializing"
        return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)

    state = "not_started"
    return OrderPaymentDisplay(state, PAYMENT_STATE_LABELS[state], method_label)
