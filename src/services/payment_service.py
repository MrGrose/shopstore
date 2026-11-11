import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.integrations.sbp import SBPClient
from src.integrations.sbp.errors import (
    SBPError,
    SBPPaymentReconciliationError,
    SBPTimeoutError,
)
from src.integrations.sbp.redis_lock import release_redis_lock, try_acquire_redis_lock
from src.models.order import (
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderPaymentAttempt,
    OrderStatus,
)
from src.repositories.notification_outbox_repo import NotificationOutboxRepo
from src.repositories.order_repo import CrudOrder
from src.schemas.order import PaymentInitSchema, PaymentStatusSchema
from src.services.admin_notification_service import AdminNotificationService
from src.services.customer_notification_service import CustomerNotificationService
from src.services.orders.order_service import OrderService
from src.services.orders.supplier_orders import SupplierOrderService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import (
    PAYMENT_ACCEPTED_STATUS,
    PAYMENT_FAILED_STATUSES,
    PAYMENT_INIT_STATUS,
    attempt_qr_alive,
    is_provider_status_transition_allowed,
    normalize_order_payment_from_attempt,
    payment_attempts_exhausted,
    payment_deadline_blocks_payment,
)

logger = logging.getLogger(__name__)

PAYMENT_PROVIDER = "sbp"
INIT_STATE_CREATING = "creating"
INIT_STATE_READY = "ready"
# Окно для x-req-id.
X_REQ_ID_WINDOW = timedelta(minutes=60)
# TTL QR.
QR_TTL = timedelta(minutes=15)
# TTL блокировки инициализации оплаты.
PAYMENT_INIT_LOCK_TTL = 60
# Префикс блокировки инициализации оплаты.
PAYMENT_INIT_LOCK_PREFIX = "sbp:payment_init:"
# Префикс блокировки сверки оплат.
RECONCILE_LOCK_PREFIX = "sbp:reconcile:"
# Префикс merchant order ID.
MERCHANT_ORDER_PREFIX = "shopstore-"
# Тип события оплаты.
PAYMENT_EVENT_TYPE = "payment_accepted"
# Тип события повторной оплаты.
PAYMENT_DUPLICATE_EVENT_TYPE = "payment_duplicate_accepted"
# Тип события поздней оплаты после автоотмены.
LATE_PAYMENT_EVENT_TYPE = "late_payment_after_auto_cancel"
# Статусы терминала.
TERMINAL_STATUSES = frozenset({PAYMENT_ACCEPTED_STATUS, "DECLINED"})


# Генерирует merchant order ID для заказа.
def merchant_order_id_for(order_id: int, attempt_number: int) -> str:
    return f"{MERCHANT_ORDER_PREFIX}{order_id}/{attempt_number}"


# Генерирует legacy merchant order ID для заказа.
def legacy_merchant_order_id_for(order_id: int) -> str:
    return f"{MERCHANT_ORDER_PREFIX}{order_id}"


# Парсит local order ID из merchant order ID.
def parse_local_order_id_from_merchant(merchant_order_id: str | None) -> int | None:
    if not merchant_order_id:
        return None
    value = merchant_order_id.strip()
    match = re.fullmatch(rf"{re.escape(MERCHANT_ORDER_PREFIX)}(\d+)(?:/(\d+))?", value)
    if not match:
        return None
    return int(match.group(1))


# Конвертирует total_amount в minor units.
def order_amount_minor(total_amount: Decimal) -> int:
    return int((total_amount * Decimal("100")).to_integral_value())


# Генерирует x-req-id order для заказа.
def x_req_id_for_order(order_id: int, attempt_number: int) -> str:
    return f"shopstore-order-{order_id}-{attempt_number}"


# Генерирует x-req-id QR для заказа.
def x_req_id_for_qr(order_id: int, attempt_number: int) -> str:
    return f"shopstore-qrc-{order_id}-{attempt_number}"


# Генерирует x-req-id для GET запроса.
def new_provider_get_x_req_id() -> str:
    return f"shopstore-get-{uuid.uuid4().hex}"


@dataclass
class _InitBootstrap:
    # Результат короткой фазы init под блокировкой заказа.
    kind: str
    attempt_id: int | None = None


@dataclass(frozen=True)
class LateNotify:
    order_id: int
    attempt_id: int


@dataclass(frozen=True)
class PaymentAcceptedNotify:
    order_id: int
    attempt_id: int


@dataclass(frozen=True)
class PaymentFailedCustomerNotify:
    order_id: int
    attempt_id: int


@dataclass(frozen=True)
class DuplicatePaymentNotify:
    order_id: int
    attempt_id: int


PaymentAdminNotify = LateNotify | PaymentAcceptedNotify
PaymentSideEffect = (
    PaymentAdminNotify | PaymentFailedCustomerNotify | DuplicatePaymentNotify
)


class PaymentService:
    # Оплата заказа через SBP (СБП).
    def __init__(
        self,
        session: AsyncSession,
        sbp_client: SBPClient | None = None,
    ) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)
        self.sbp = sbp_client or SBPClient()

    async def init_payment(self, order_id: int, user_id: int) -> PaymentInitSchema:
        if not settings.SBP_ENABLED:
            raise ValueError("Платёжная интеграция на этом окружении отключена.")
        order = await self._get_user_order(order_id=order_id, user_id=user_id)

        if order.payment_paid_at is not None:
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            return self._build_init_schema(
                order, latest, qr_payload=None, payment_state="paid"
            )

        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        attempts_used = await self.order_crud.count_payment_attempts(order_id)
        limit = settings.ORDER_MAX_PAYMENT_ATTEMPTS
        if payment_attempts_exhausted(attempts_used, limit, latest):
            return self._build_init_schema(
                order,
                latest,
                qr_payload=None,
                payment_state="exhausted",
                payment_attempts_used=attempts_used,
            )

        if payment_deadline_blocks_payment(order.payment_due_at, latest):
            raise ValueError("Срок оплаты заказа истёк")

        self._ensure_payment_allowed(order, latest_attempt=latest)

        lock_key = f"{PAYMENT_INIT_LOCK_PREFIX}{order_id}"
        lock_owner = await try_acquire_redis_lock(lock_key, PAYMENT_INIT_LOCK_TTL)
        if lock_owner is None:
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            if latest and self._qr_payload_from_attempt(latest) is not None:
                return self._build_init_schema(
                    order,
                    latest,
                    qr_payload=self._qr_payload_from_attempt(latest),
                )
            raise ValueError(
                "Оплата уже инициализируется, повторите запрос через несколько секунд"
            )

        try:
            bootstrap = await self._init_bootstrap_under_order_lock(order_id, user_id)
            return await self._init_continue_without_order_lock(
                order_id, user_id, bootstrap
            )
        except SBPTimeoutError as exc:
            raise ValueError(
                "Платёжный провайдер не ответил вовремя. "
                "Повторите инициализацию через минуту."
            ) from exc
        except SBPPaymentReconciliationError as exc:
            raise ValueError(str(exc)) from exc
        except SBPError as exc:
            logger.warning("Ошибка SBP при init_payment order_id=%s: %s", order_id, exc)
            raise ValueError(
                "Не удалось инициализировать оплату. Попробуйте позже."
            ) from exc
        finally:
            if lock_owner:
                await release_redis_lock(lock_key, lock_owner)

    # Инициализирует оплату заказа под блокировкой заказа.
    async def _init_bootstrap_under_order_lock(
        self, order_id: int, user_id: int
    ) -> _InitBootstrap:
        locked = await self.order_crud.get_by_id_for_update(order_id)
        if not locked or locked.user_id != user_id:
            raise ValueError("Заказ не найден")
        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        if locked.payment_paid_at is not None:
            await self.session.commit()
            return _InitBootstrap("paid", latest.id if latest else None)
        self._ensure_payment_allowed(locked, latest_attempt=latest)

        if latest is None:
            count = await self.order_crud.count_payment_attempts(order_id)
            if count >= settings.ORDER_MAX_PAYMENT_ATTEMPTS:
                await self.session.commit()
                return _InitBootstrap("exhausted")
            attempt = await self._create_payment_attempt_row(locked, attempt_number=1)
            await self.session.commit()
            return _InitBootstrap("complete_provider", attempt.id)

        if latest.init_state == INIT_STATE_CREATING and not latest.provider_order_id:
            self._ensure_init_window_for_attempt(latest)
            await self.session.commit()
            return _InitBootstrap("complete_provider", latest.id)

        await self.session.commit()
        return _InitBootstrap("continue", latest.id)

    # Продолжает инициализацию оплаты заказа без блокировки заказа.
    async def _init_continue_without_order_lock(
        self,
        order_id: int,
        user_id: int,
        bootstrap: _InitBootstrap,
    ) -> PaymentInitSchema:
        order = await self._get_user_order(order_id=order_id, user_id=user_id)

        if bootstrap.kind == "paid":
            attempt = None
            if bootstrap.attempt_id is not None:
                attempt = await self.order_crud.get_payment_attempt_by_id(
                    bootstrap.attempt_id
                )
            return self._build_init_schema(
                order, attempt, qr_payload=None, payment_state="paid"
            )

        if bootstrap.kind == "exhausted":
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            attempts_used = await self.order_crud.count_payment_attempts(order_id)
            return self._build_init_schema(
                order,
                latest,
                qr_payload=None,
                payment_state="exhausted",
                payment_attempts_used=attempts_used,
            )

        if bootstrap.kind == "complete_provider":
            if bootstrap.attempt_id is None:
                raise ValueError("Платёжная попытка не найдена")
            attempt = await self.order_crud.get_payment_attempt_by_id(
                bootstrap.attempt_id
            )
            if attempt is None:
                raise ValueError("Платёжная попытка не найдена")
            return await self._complete_provider_order_for_attempt(order, attempt)

        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        if latest is None:
            raise ValueError("Платёжная попытка не найдена")

        if latest.provider_order_id:
            admin_notify = await self._refresh_attempt_from_provider(latest.id)
            if admin_notify is not None:
                await self._schedule_payment_notifications(admin_notify)
            await self.session.commit()
            order = await self._get_user_order(order_id=order_id, user_id=user_id)
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            if latest is None:
                raise ValueError("Платёжная попытка не найдена")

        status = str(latest.provider_status or "").upper()
        if status == PAYMENT_ACCEPTED_STATUS or latest.paid_at is not None:
            return await self._commit_init_return(
                order, latest, qr_payload=None, payment_state="paid"
            )

        if status == "DECLINED":
            return await self._start_new_attempt_after_order_lock(order_id, user_id)

        if self._qr_is_alive(latest):
            qr_payload = await self._fetch_live_qr(latest)
            await self.session.commit()
            order = await self._get_user_order(order_id=order_id, user_id=user_id)
            latest = await self.order_crud.get_payment_attempt_by_id(latest.id)
            if latest is None:
                raise ValueError("Платёжная попытка не найдена")
            status = str(latest.provider_status or "").upper()
            if status == PAYMENT_ACCEPTED_STATUS or latest.paid_at is not None:
                return await self._commit_init_return(
                    order, latest, qr_payload=None, payment_state="paid"
                )
            if not qr_payload:
                status = str(latest.provider_status or "").upper()
                if status in PAYMENT_FAILED_STATUSES or not self._qr_is_alive(latest):
                    return self._build_init_schema(order, latest, qr_payload=None)
                raise ValueError(
                    "Не удалось получить QR-код. Попробуйте открыть оплату "
                    "через несколько секунд."
                )
            return self._build_init_schema(order, latest, qr_payload=qr_payload)

        if (
            latest.provider_order_id
            and not latest.qr_created_at
            and status in {PAYMENT_INIT_STATUS, ""}
        ):
            return await self._complete_qr_for_attempt(order, latest)

        if status == PAYMENT_INIT_STATUS and latest.provider_order_id:
            return await self._complete_qr_for_attempt(order, latest)

        return await self._start_new_attempt_after_order_lock(order_id, user_id)

    async def _create_payment_attempt_row(
        self, order: Order, attempt_number: int
    ) -> OrderPaymentAttempt:
        amount_minor = order_amount_minor(order.total_amount)
        self._validate_amount_minor(amount_minor)
        return await self.order_crud.create_payment_attempt(
            order_id=order.id,
            attempt_number=attempt_number,
            provider=PAYMENT_PROVIDER,
            merchant_order_id=merchant_order_id_for(order.id, attempt_number),
            x_req_id_order=x_req_id_for_order(order.id, attempt_number),
            x_req_id_qr=x_req_id_for_qr(order.id, attempt_number),
            payment_amount_minor=amount_minor,
            payment_currency="RUB",
            init_state=INIT_STATE_CREATING,
        )

    # Начинает новую попытку оплаты заказа после блокировки заказа.
    async def _start_new_attempt_after_order_lock(
        self, order_id: int, user_id: int
    ) -> PaymentInitSchema:
        locked = await self.order_crud.get_by_id_for_update(order_id)
        if not locked or locked.user_id != user_id:
            raise ValueError("Заказ не найден")
        if locked.payment_paid_at is not None:
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            await self.session.commit()
            order = await self._get_user_order(order_id=order_id, user_id=user_id)
            return self._build_init_schema(
                order,
                latest,
                qr_payload=None,
                payment_state="paid",
            )
        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        self._ensure_payment_allowed(locked, latest_attempt=latest)
        count = await self.order_crud.count_payment_attempts(locked.id)
        if payment_attempts_exhausted(
            count, settings.ORDER_MAX_PAYMENT_ATTEMPTS, latest
        ):
            await self.session.commit()
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            attempts_used = await self.order_crud.count_payment_attempts(order_id)
            order = await self._get_user_order(order_id=order_id, user_id=user_id)
            return self._build_init_schema(
                order,
                latest,
                qr_payload=None,
                payment_state="exhausted",
                payment_attempts_used=attempts_used,
            )
        next_num = await self.order_crud.get_next_payment_attempt_number(locked.id)
        attempt = await self._create_payment_attempt_row(
            locked, attempt_number=next_num
        )
        await self.session.commit()
        order = await self._get_user_order(order_id=order_id, user_id=user_id)
        return await self._complete_provider_order_for_attempt(order, attempt)

    # Возвращает статус оплаты заказа.
    async def get_payment_status(
        self,
        order_id: int,
        user_id: int,
        payment_attempt_id: int,
    ) -> PaymentStatusSchema:
        order = await self._get_user_order(order_id=order_id, user_id=user_id)
        attempt = await self.order_crud.get_payment_attempt_by_id(payment_attempt_id)
        if not attempt or attempt.order_id != order.id:
            raise ValueError("Платёжная попытка не найдена")

        if not settings.SBP_ENABLED:
            return self._build_status_schema(order, attempt)

        admin_notify: PaymentSideEffect | None = None
        if attempt.provider_order_id:
            try:
                admin_notify = await self._refresh_attempt_from_provider(attempt.id)
            except SBPError as exc:
                logger.warning(
                    "Ошибка SBP status order_id=%s attempt_id=%s: %s",
                    order_id,
                    payment_attempt_id,
                    exc,
                )
                admin_notify = None
        if admin_notify is not None:
            await self._schedule_payment_notifications(admin_notify)
        await self.session.commit()
        await self.session.refresh(order)
        await self.session.refresh(attempt)
        attempts_used = await self.order_crud.count_payment_attempts(order.id)
        return self._build_status_schema(
            order, attempt, payment_attempts_used=attempts_used
        )

    # Обновляет попытку оплаты заказа для администратора.
    async def refresh_payment_attempt_admin(
        self, attempt_id: int, order_id: int | None = None
    ) -> OrderPaymentAttempt:
        attempt = await self.order_crud.get_payment_attempt_by_id(attempt_id)
        if not attempt:
            raise ValueError("Платёжная попытка не найдена")
        if order_id is not None and attempt.order_id != order_id:
            raise ValueError("Платёжная попытка не принадлежит заказу")
        if not attempt.provider_order_id:
            raise ValueError("У попытки нет provider_order_id")
        if not settings.SBP_ENABLED:
            return attempt
        admin_notify = await self._refresh_attempt_from_provider(attempt.id)
        if admin_notify is not None:
            await self._schedule_payment_notifications(admin_notify)
        await self.session.commit()
        await self.session.refresh(attempt)
        return attempt

    # Сверяет просроченные попытки оплаты.
    async def reconcile_expired_attempts(self, limit: int = 50) -> dict[str, int]:
        now = utc_now_naive()
        attempts = await self.order_crud.find_payment_attempts_for_reconciliation(
            now, limit=limit
        )
        processed = 0
        errors = 0
        for attempt in attempts:
            lock_key = f"{RECONCILE_LOCK_PREFIX}{attempt.id}"
            lock_owner = await try_acquire_redis_lock(lock_key, PAYMENT_INIT_LOCK_TTL)
            if lock_owner is None:
                continue
            try:
                if not attempt.provider_order_id:
                    continue
                admin_notify = await self._refresh_attempt_from_provider(attempt.id)
                if admin_notify is not None:
                    await self._schedule_payment_notifications(admin_notify)
                await self.session.commit()
                processed += 1
            except SBPError as exc:
                errors += 1
                logger.warning(
                    "Reconciliation: ошибка attempt_id=%s: %s", attempt.id, exc
                )
                await self.session.rollback()
            finally:
                await release_redis_lock(lock_key, lock_owner)
        return {"processed": processed, "errors": errors, "candidates": len(attempts)}

    # Обрабатывает callback от SBP.
    async def handle_sbp_callback(self, payload: dict[str, Any]) -> None:
        order_data = payload.get("order")
        if not isinstance(order_data, dict):
            raise ValueError("Некорректное тело callback")
        provider_order_id_raw = order_data.get("id")
        if provider_order_id_raw is None:
            raise ValueError("Callback без id заказа провайдера")
        provider_order_id = str(provider_order_id_raw)
        provider_status = str(order_data.get("status") or "")
        callback_at = utc_now_naive()

        attempt = await self.order_crud.get_payment_attempt_by_provider_order_id(
            provider_order_id
        )
        if attempt:
            if not self._callback_payload_matches_attempt(attempt, order_data):
                return
            admin_notify = await self._apply_provider_status_to_attempt(
                attempt.id, provider_status, callback_at=callback_at
            )
            if admin_notify is not None:
                await self._schedule_payment_notifications(admin_notify)
            await self.session.commit()
            return

        merchant_id = order_data.get("merchantOrderId")
        if merchant_id is not None:
            attempt = await self.order_crud.get_payment_attempt_by_merchant_order_id(
                str(merchant_id)
            )
            if attempt:
                if not self._callback_payload_matches_attempt(attempt, order_data):
                    return
                if not attempt.provider_order_id:
                    bound = await self.order_crud.try_bind_attempt_provider_order_id(
                        attempt.id,
                        provider_order_id,
                        provider_status or None,
                    )
                    if not bound:
                        return
                admin_notify = await self._apply_provider_status_to_attempt(
                    attempt.id, provider_status, callback_at=callback_at
                )
                if admin_notify is not None:
                    await self._schedule_payment_notifications(admin_notify)
                await self.session.commit()
                return

        if merchant_id is None:
            logger.warning(
                "SBP callback: recovery пропущен — "
                "нет merchantOrderId provider_id=%s",
                provider_order_id,
            )
            return

        local_id = parse_local_order_id_from_merchant(str(merchant_id))
        if local_id is None:
            logger.warning(
                "SBP callback: заказ не найден provider_id=%s merchant=%s",
                provider_order_id,
                merchant_id,
            )
            return

        attempt = await self.order_crud.get_payment_attempt_by_merchant_order_id(
            str(merchant_id)
        )
        if not attempt:
            latest = await self.order_crud.get_latest_payment_attempt(local_id)
            if (
                latest
                and latest.init_state == INIT_STATE_CREATING
                and not latest.provider_order_id
            ):
                attempt = latest
            else:
                logger.warning(
                    "SBP callback: попытка не найдена order_id=%s provider_id=%s",
                    local_id,
                    provider_order_id,
                )
                return

        if not self._callback_payload_matches_attempt(attempt, order_data):
            return
        if attempt.init_state != INIT_STATE_CREATING:
            logger.warning(
                "SBP callback: recovery отклонён — init_state=%s attempt_id=%s",
                attempt.init_state,
                attempt.id,
            )
            return

        bound = await self.order_crud.try_bind_attempt_provider_order_id(
            attempt.id,
            provider_order_id,
            provider_status or None,
        )
        if not bound:
            return
        admin_notify = await self._apply_provider_status_to_attempt(
            attempt.id, provider_status, callback_at=callback_at
        )
        if admin_notify is not None:
            await self._schedule_payment_notifications(admin_notify)
        await self.session.commit()

    # Применяет статус попытки оплаты.
    async def _apply_provider_status_to_attempt(
        self,
        attempt_id: int,
        provider_status: str,
        callback_at: datetime | None,
    ) -> PaymentSideEffect | None:
        attempt = await self.order_crud.get_payment_attempt_by_id_for_update(attempt_id)
        if not attempt:
            return None
        return await self._apply_status_on_locked_attempt(
            attempt, provider_status, callback_at=callback_at
        )

    # Применяет статус попытки оплаты на блокированной попытке.
    async def _apply_status_on_locked_attempt(
        self,
        attempt: OrderPaymentAttempt,
        provider_status: str,
        callback_at: datetime | None,
    ) -> PaymentSideEffect | None:
        status = str(provider_status or "").upper()
        if not status:
            return None
        if callback_at is not None:
            attempt.last_callback_at = callback_at

        current = str(attempt.provider_status or "").upper()
        if not is_provider_status_transition_allowed(current, status):
            self.session.add(attempt)
            await self.session.flush()
            return None

        if status == PAYMENT_ACCEPTED_STATUS and attempt.paid_at is not None:
            self.session.add(attempt)
            await self.session.flush()
            return None

        attempt.provider_status = status
        self.session.add(attempt)
        await self.session.flush()

        order = await self.order_crud.get_by_id(attempt.order_id)
        if not order:
            return None

        if status == PAYMENT_ACCEPTED_STATUS:
            return await self._mark_attempt_accepted(attempt, order, callback_at)

        if order.payment_paid_at is not None:
            return None

        latest = await self.order_crud.get_latest_payment_attempt(order.id)
        is_latest = latest is not None and latest.id == attempt.id
        await self.order_crud.sync_order_payment_aggregate(
            order, attempt, is_latest_attempt=is_latest
        )
        if (
            status in PAYMENT_FAILED_STATUSES
            and is_latest
            and current not in PAYMENT_FAILED_STATUSES
        ):
            return PaymentFailedCustomerNotify(
                order_id=order.id,
                attempt_id=attempt.id,
            )
        return None

    # Подтверждает оплату попытки оплаты.
    async def _mark_attempt_accepted(
        self,
        attempt: OrderPaymentAttempt,
        order: Order,
        callback_at: datetime | None,
    ) -> PaymentSideEffect | None:
        paid_at = utc_now_naive()
        locked_order = await self.order_crud.get_by_id_for_update(order.id)
        if locked_order is None:
            return None
        accepted_attempt_id = await self.order_crud.mark_payment_attempt_paid_if_unpaid(
            attempt.id,
            paid_at=paid_at,
            provider_status=PAYMENT_ACCEPTED_STATUS,
            last_callback_at=callback_at,
        )
        if accepted_attempt_id is None:
            return None

        attempt.paid_at = paid_at
        attempt.provider_status = PAYMENT_ACCEPTED_STATUS

        paid_n: int | None = None
        if locked_order.payment_paid_at is None:
            paid_n = await SupplierOrderService(
                self.session
            ).freeze_paid_supplier_order_count(locked_order)

        order_accepted_id = await self.order_crud.mark_payment_accepted_if_unpaid(
            locked_order.id,
            payment_status=PAYMENT_ACCEPTED_STATUS,
            payment_paid_at=paid_at,
            payment_last_callback_at=callback_at,
            paid_supplier_order_count=paid_n,
        )
        if order_accepted_id is not None:
            locked_order.payment_paid_at = paid_at
            locked_order.payment_status = PAYMENT_ACCEPTED_STATUS
            if paid_n is not None:
                locked_order.paid_supplier_order_count = paid_n

        is_late = str(locked_order.status or "").lower() == OrderStatus.CANCELLED
        await self.order_crud.sync_order_payment_aggregate(
            locked_order, attempt, is_latest_attempt=True
        )

        if order_accepted_id is None:
            has_other = await self.order_crud.has_paid_payment_attempt_excluding(
                locked_order.id, attempt.id
            )
            if not has_other:
                return None
            await self.order_crud.create_order_event(
                order_id=locked_order.id,
                event_type=PAYMENT_DUPLICATE_EVENT_TYPE,
                event_message="Обнаружена повторная успешная оплата (другая попытка)",
                created_by="sbp",
                payload_json={
                    "payment_status": PAYMENT_ACCEPTED_STATUS,
                    "payment_attempt_id": attempt.id,
                },
            )
            return DuplicatePaymentNotify(
                order_id=locked_order.id,
                attempt_id=attempt.id,
            )

        if is_late:
            if await self.order_crud.has_order_event_type(
                locked_order.id, LATE_PAYMENT_EVENT_TYPE
            ):
                return None
            await self.order_crud.create_order_event(
                order_id=locked_order.id,
                event_type=LATE_PAYMENT_EVENT_TYPE,
                event_message="Оплата получена после отмены заказа",
                created_by="sbp",
                payload_json={
                    "payment_status": PAYMENT_ACCEPTED_STATUS,
                    "payment_attempt_id": attempt.id,
                    "provider_order_id": attempt.provider_order_id,
                    "payment_amount_minor": attempt.payment_amount_minor,
                },
            )
            return LateNotify(order_id=locked_order.id, attempt_id=attempt.id)

        await self.order_crud.create_order_event(
            order_id=order_accepted_id,
            event_type=PAYMENT_EVENT_TYPE,
            event_message="Оплата подтверждена через SBP (СБП)",
            created_by="sbp",
            payload_json={
                "payment_status": PAYMENT_ACCEPTED_STATUS,
                "payment_attempt_id": attempt.id,
            },
        )
        return PaymentAcceptedNotify(
            order_id=locked_order.id,
            attempt_id=attempt.id,
        )

    # Начинает новую попытку оплаты заказа.
    async def _start_new_attempt(
        self, order: Order, attempt_number: int
    ) -> PaymentInitSchema:
        attempt = await self._create_payment_attempt_row(order, attempt_number)
        await self.session.commit()
        fresh_order = await self.order_crud.get_by_id(order.id)
        if fresh_order is None:
            raise ValueError("Заказ не найден")
        return await self._complete_provider_order_for_attempt(fresh_order, attempt)

    # Завершает попытку оплаты заказа.
    async def _complete_provider_order_for_attempt(
        self, order: Order, attempt: OrderPaymentAttempt
    ) -> PaymentInitSchema:
        attempt_id = attempt.id
        provider_order = await self.sbp.create_order(
            merchant_order_id=attempt.merchant_order_id,
            payment_amount_minor=attempt.payment_amount_minor,
            description=f"Оплата заказа #{order.id}",
            callback_url=settings.SBP_CALLBACK_URL.strip(),
            x_req_id=attempt.x_req_id_order,
        )
        locked = await self.order_crud.get_payment_attempt_by_id_for_update(attempt_id)
        if locked is None:
            raise ValueError("Платёжная попытка не найдена")
        provider_order_id = str(provider_order.get("id"))
        if locked.provider_order_id is None:
            locked.provider_order_id = provider_order_id
            locked.provider_external_order_id = self._provider_external_order_id(
                provider_order
            )
        elif locked.provider_order_id != provider_order_id:
            logger.warning(
                "create_order: provider_order_id mismatch attempt_id=%s exp=%s got=%s",
                attempt_id,
                locked.provider_order_id,
                provider_order_id,
            )
        provider_status = str(provider_order.get("status") or PAYMENT_INIT_STATUS)
        await self._apply_status_on_locked_attempt(
            locked, provider_status, callback_at=None
        )
        await self.session.commit()
        fresh = await self.order_crud.get_payment_attempt_by_id(attempt_id)
        if fresh is None:
            raise ValueError("Платёжная попытка не найдена")
        if str(fresh.provider_status or "").upper() == PAYMENT_ACCEPTED_STATUS:
            fresh_order = await self.order_crud.get_by_id(order.id)
            if fresh_order is None:
                raise ValueError("Заказ не найден")
            return await self._commit_init_return(
                fresh_order, fresh, qr_payload=None, payment_state="paid"
            )
        return await self._complete_qr_for_attempt(order, fresh)

    # Завершает создание QR для попытки оплаты заказа.
    async def _complete_qr_for_attempt(
        self, order: Order, attempt: OrderPaymentAttempt
    ) -> PaymentInitSchema:
        attempt_id = attempt.id
        if not attempt.provider_order_id:
            raise ValueError("Нет provider_order_id для создания QR")
        qr_data = await self.sbp.create_qr(
            attempt.provider_order_id,
            attempt.x_req_id_qr,
        )
        locked = await self.order_crud.get_payment_attempt_by_id_for_update(attempt_id)
        if locked is None:
            raise ValueError("Платёжная попытка не найдена")
        qr_payload = self._extract_qr_payload(qr_data)
        qr_was_new = False
        if locked.paid_at is None and locked.qr_created_at is None:
            qr_was_new = True
            now = utc_now_naive()
            locked.qr_created_at = now
            locked.qr_expires_at = now + QR_TTL
            locked.init_state = INIT_STATE_READY
        status = str(qr_data.get("status") or "")
        if status:
            await self._apply_status_on_locked_attempt(locked, status, callback_at=None)
        fresh_order = await self.order_crud.get_by_id(order.id)
        fresh_attempt = await self.order_crud.get_payment_attempt_by_id(attempt_id)
        if fresh_order is None or fresh_attempt is None:
            raise ValueError("Заказ или попытка не найдены")
        latest = await self.order_crud.get_latest_payment_attempt(fresh_order.id)
        is_latest = latest is not None and latest.id == fresh_attempt.id
        if fresh_order.payment_paid_at is None:
            await self.order_crud.sync_order_payment_aggregate(
                fresh_order, fresh_attempt, is_latest_attempt=is_latest
            )
        if str(fresh_attempt.provider_status or "").upper() == PAYMENT_ACCEPTED_STATUS:
            return await self._commit_init_return(
                fresh_order,
                fresh_attempt,
                qr_payload=None,
                payment_state="paid",
            )
        schedule_awaiting = (
            qr_was_new
            and qr_payload is not None
            and fresh_order.payment_paid_at is None
        )
        return await self._commit_init_return(
            fresh_order,
            fresh_attempt,
            qr_payload=qr_payload,
            schedule_awaiting=schedule_awaiting,
        )

    # Получает живой QR для попытки оплаты заказа.
    async def _fetch_live_qr(self, attempt: OrderPaymentAttempt) -> str | None:
        if not attempt.provider_order_id:
            raise ValueError("Нет provider_order_id для получения QR")
        provider_order = await self.sbp.get_order(
            attempt.provider_order_id,
            new_provider_get_x_req_id(),
        )
        status = str(provider_order.get("status") or "")
        if status:
            await self._apply_provider_status_to_attempt(
                attempt.id, status, callback_at=None
            )
            fresh = await self.order_crud.get_payment_attempt_by_id(attempt.id)
            if (
                fresh
                and str(fresh.provider_status or "").upper() == PAYMENT_ACCEPTED_STATUS
            ):
                return None
        fresh = await self.order_crud.get_payment_attempt_by_id(attempt.id)
        if fresh is None:
            raise ValueError("Платёжная попытка не найдена")
        if not self._qr_is_alive(fresh):
            return None
        qr_payload = self._extract_qr_payload(provider_order)
        if qr_payload:
            return self._accept_live_qr_payload(fresh, qr_payload)
        return await self._refetch_qr_payload_via_post(fresh)

    # Повторно запрашивает QR-код через POST запрос.
    async def _refetch_qr_payload_via_post(
        self, attempt: OrderPaymentAttempt
    ) -> str | None:
        if not attempt.provider_order_id or not attempt.x_req_id_qr:
            raise ValueError("Нет данных для повторного запроса QR")
        if not self._qr_is_alive(attempt):
            raise ValueError("QR-код уже недействителен")
        qr_data = await self.sbp.create_qr(
            attempt.provider_order_id,
            attempt.x_req_id_qr,
        )
        qr_payload = self._extract_qr_payload(qr_data)
        qr_status = str(qr_data.get("status") or "")
        if qr_status:
            await self._apply_provider_status_to_attempt(
                attempt.id, qr_status, callback_at=None
            )
        fresh = await self.order_crud.get_payment_attempt_by_id(attempt.id)
        if fresh is None:
            raise ValueError("Платёжная попытка не найдена")
        if not qr_payload:
            raise ValueError(
                "Не удалось получить QR-код. Попробуйте открыть оплату "
                "через несколько секунд."
            )
        return self._accept_live_qr_payload(fresh, qr_payload)

    # Принимает живой QR-код.
    def _accept_live_qr_payload(
        self,
        attempt: OrderPaymentAttempt,
        qr_payload: str | None,
    ) -> str | None:
        if not qr_payload:
            return None
        status = str(attempt.provider_status or "").upper()
        if status == PAYMENT_ACCEPTED_STATUS or attempt.paid_at is not None:
            return None
        if status in PAYMENT_FAILED_STATUSES:
            return None
        if not self._qr_is_alive(attempt):
            return None
        return qr_payload

    # Обновляет попытку оплаты из провайдера.
    async def _refresh_attempt_from_provider(
        self, attempt_id: int
    ) -> PaymentSideEffect | None:
        attempt = await self.order_crud.get_payment_attempt_by_id(attempt_id)
        if not attempt or not attempt.provider_order_id:
            return None
        provider_order = await self.sbp.get_order(
            attempt.provider_order_id,
            new_provider_get_x_req_id(),
        )
        status = str(provider_order.get("status") or "")
        if status:
            return await self._apply_provider_status_to_attempt(
                attempt_id, status, callback_at=None
            )
        return None

    # Ставит TG-уведомления об оплате в outbox (в той же транзакции).
    async def _schedule_payment_notifications(self, notify: PaymentSideEffect) -> None:
        customer = CustomerNotificationService(self.session)
        if isinstance(notify, PaymentFailedCustomerNotify):
            await customer.notify_payment_failed(
                notify.order_id,
                notify.attempt_id,
            )
            return
        admin_notify = AdminNotificationService(self.session)
        if isinstance(notify, DuplicatePaymentNotify):
            await admin_notify.send_payment_duplicate(
                notify.order_id,
                notify.attempt_id,
            )
            return
        if isinstance(notify, LateNotify):
            await admin_notify.send_late_payment_after_auto_cancel(
                notify.order_id,
                notify.attempt_id,
            )
            await customer.notify_payment_late_received(
                notify.order_id,
                notify.attempt_id,
            )
            return
        await admin_notify.send_order_payment_accepted(
            notify.order_id,
            notify.attempt_id,
        )
        await customer.notify_payment_received(notify.order_id)

    # Завершает инициализацию оплаты заказа.
    async def _commit_init_return(
        self,
        order: Order,
        attempt: OrderPaymentAttempt | None,
        qr_payload: str | None = None,
        payment_state: str | None = None,
        schedule_awaiting: bool = False,
    ) -> PaymentInitSchema:
        if schedule_awaiting:
            await CustomerNotificationService(self.session).notify_payment_awaiting(
                order.id
            )
        await self.session.commit()
        await self.session.refresh(order)
        if attempt is not None:
            await self.session.refresh(attempt)
        return self._build_init_schema(
            order, attempt, qr_payload=qr_payload, payment_state=payment_state
        )

    # Получает внешний идентификатор заказа из провайдера.
    def _provider_external_order_id(self, provider_order: dict[str, Any]) -> str | None:
        for key in ("externalOrderId", "external_order_id"):
            value = provider_order.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return None

    # Извлекает QR-код из ответа провайдера.
    def _extract_qr_payload(self, provider_order: dict[str, Any]) -> str | None:
        for path in (
            ("payload",),
            ("qrcData", "payload"),
            ("qrcData", "qrcPayload"),
            ("qrc", "payload"),
        ):
            node: Any = provider_order
            for key in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(key)
            if node is None:
                continue
            text = str(node).strip()
            if text:
                return text
        return None

    # Проверяет, жив ли QR-код.
    def _qr_is_alive(self, attempt: OrderPaymentAttempt) -> bool:
        return attempt_qr_alive(attempt)

    # Извлекает QR-код из попытки оплаты.
    def _qr_payload_from_attempt(self, attempt: OrderPaymentAttempt) -> str | None:
        if not self._qr_is_alive(attempt):
            return None
        return None

    # Проверяет, соответствует ли payload попытке оплаты.
    def _callback_payload_matches_attempt(
        self,
        attempt: OrderPaymentAttempt,
        order_data: dict[str, Any],
    ) -> bool:
        merchant_id = str(order_data.get("merchantOrderId") or "")
        if not merchant_id or merchant_id != attempt.merchant_order_id:
            logger.warning(
                "SBP callback: merchantOrderId mismatch attempt_id=%s exp=%s got=%s",
                attempt.id,
                attempt.merchant_order_id,
                merchant_id or None,
            )
            return False
        payment_amount = order_data.get("paymentAmount")
        if payment_amount is None:
            logger.warning(
                "SBP callback: отсутствует paymentAmount attempt_id=%s",
                attempt.id,
            )
            return False
        if int(payment_amount) != int(attempt.payment_amount_minor):
            logger.warning(
                "SBP callback: amount mismatch attempt_id=%s exp=%s got=%s",
                attempt.id,
                attempt.payment_amount_minor,
                payment_amount,
            )
            return False
        payment_currency = order_data.get("paymentCurrency")
        expected = str(attempt.payment_currency or "RUB").upper()
        if not payment_currency or str(payment_currency).upper() != expected:
            logger.warning(
                "SBP callback: валюта mismatch attempt_id=%s exp=%s got=%s",
                attempt.id,
                expected,
                payment_currency,
            )
            return False
        return True

    # Проверяет, соответствует ли payload попытке оплаты.
    def _ensure_init_window_for_attempt(self, attempt: OrderPaymentAttempt) -> None:
        if attempt.init_state != INIT_STATE_CREATING:
            return
        if attempt.created_at is None:
            return
        if utc_now_naive() - attempt.created_at <= X_REQ_ID_WINDOW:
            return
        raise SBPPaymentReconciliationError(
            "Инициализация оплаты зависла. Обратитесь в поддержку для проверки платежа."
        )

    def _validate_amount_minor(self, amount_minor: int) -> None:
        if amount_minor < settings.SBP_MIN_PAYMENT_AMOUNT_MINOR:
            raise ValueError(
                f"Сумма заказа ниже минимума для оплаты "
                f"({settings.SBP_MIN_PAYMENT_AMOUNT_MINOR // 100} ₽)"
            )
        if amount_minor > settings.SBP_MAX_PAYMENT_AMOUNT_MINOR:
            raise ValueError(
                f"Сумма заказа выше максимума для оплаты "
                f"({settings.SBP_MAX_PAYMENT_AMOUNT_MINOR // 100} ₽)"
            )

    # Проверяет, доступна ли оплата для заказа.
    def _ensure_payment_allowed(
        self, order: Order, latest_attempt: OrderPaymentAttempt | None = None
    ) -> None:
        if payment_deadline_blocks_payment(order.payment_due_at, latest_attempt):
            raise ValueError("Срок оплаты заказа истёк")
        if not OrderService.compute_payment_allowed(
            order, latest_attempt=latest_attempt
        ):
            availability = str(
                order.availability_confirmation_status or "not_required"
            ).lower()
            if availability == AvailabilityConfirmationStatus.PENDING:
                raise ValueError(
                    f"Оплата недоступна: {OrderService.AVAILABILITY_PENDING_MESSAGE}"
                )
            if availability == AvailabilityConfirmationStatus.UNAVAILABLE:
                raise ValueError(
                    "Оплата недоступна: "
                    f"{OrderService.AVAILABILITY_UNAVAILABLE_MESSAGE}"
                )
            raise ValueError("Оплата для этого заказа сейчас недоступна")

    # Строит схему инициализации оплаты заказа.
    def _payment_attempts_meta(
        self,
        used: int,
        latest_attempt: OrderPaymentAttempt | None = None,
        order: Order | None = None,
    ) -> dict[str, int | bool]:
        limit = settings.ORDER_MAX_PAYMENT_ATTEMPTS
        exhausted = payment_attempts_exhausted(used, limit, latest_attempt)
        if order is not None and order.payment_paid_at is not None:
            exhausted = False
        return {
            "payment_attempts_used": used,
            "payment_attempts_limit": limit,
            "payment_attempts_remaining": (0 if exhausted else max(0, limit - used)),
            "payment_attempts_exhausted": exhausted,
        }

    # Строит схему инициализации оплаты заказа.
    def _build_init_schema(
        self,
        order: Order,
        attempt: OrderPaymentAttempt | None,
        qr_payload: str | None = None,
        payment_state: str | None = None,
        payment_attempts_used: int | None = None,
    ) -> PaymentInitSchema:
        used = (
            payment_attempts_used
            if payment_attempts_used is not None
            else (attempt.attempt_number if attempt else 0)
        )
        display = normalize_order_payment_from_attempt(
            payment_paid_at=order.payment_paid_at,
            latest_attempt=attempt,
            payment_provider=order.payment_provider or PAYMENT_PROVIDER,
        )
        state = payment_state or display.payment_state
        return PaymentInitSchema(
            order_id=order.id,
            provider=PAYMENT_PROVIDER,
            payment_attempt_id=attempt.id if attempt else 0,
            payment_state=state,
            payment_qr_payload=qr_payload,
            qr_expires_at=attempt.qr_expires_at if attempt else None,
            is_paid=order.payment_paid_at is not None,
            is_test_mode=settings.SBP_TEST_MODE,
            **self._payment_attempts_meta(used, attempt, order),
        )

    def _build_status_schema(
        self,
        order: Order,
        attempt: OrderPaymentAttempt,
        payment_attempts_used: int | None = None,
    ) -> PaymentStatusSchema:
        used = (
            payment_attempts_used
            if payment_attempts_used is not None
            else attempt.attempt_number
        )
        display = normalize_order_payment_from_attempt(
            payment_paid_at=order.payment_paid_at,
            latest_attempt=attempt,
            payment_provider=order.payment_provider,
        )
        state = display.payment_state
        if payment_attempts_exhausted(
            used, settings.ORDER_MAX_PAYMENT_ATTEMPTS, attempt
        ):
            if (
                order.payment_paid_at is None
                and str(attempt.provider_status or "").upper() == "DECLINED"
            ):
                state = "exhausted"
        return PaymentStatusSchema(
            order_id=order.id,
            status=order.status,
            payment_attempt_id=attempt.id,
            payment_state=state,
            is_paid=order.payment_paid_at is not None,
            qr_expires_at=attempt.qr_expires_at,
            **self._payment_attempts_meta(used, attempt, order),
        )

    # Восстанавливает outbox для payment_accepted без admin payment.accepted.
    async def recover_missing_payment_notifications(
        self,
        limit: int = 500,
    ) -> dict[str, int]:
        outbox = NotificationOutboxRepo(self.session)
        stmt = (
            select(OrderEvent)
            .where(OrderEvent.event_type == PAYMENT_EVENT_TYPE)
            .order_by(OrderEvent.created_at.desc())
            .limit(limit)
        )
        events = list((await self.session.scalars(stmt)).all())
        stats = {"candidates": len(events), "recovered": 0, "skipped": 0}
        for event in events:
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            attempt_raw = payload.get("payment_attempt_id")
            if not isinstance(attempt_raw, int):
                stats["skipped"] += 1
                continue
            admin_key = (
                f"admin:payment.accepted:order:{event.order_id}:attempt:{attempt_raw}"
            )
            if await outbox.exists_idempotency_key(admin_key):
                stats["skipped"] += 1
                continue
            await self._schedule_payment_notifications(
                PaymentAcceptedNotify(
                    order_id=event.order_id,
                    attempt_id=attempt_raw,
                )
            )
            stats["recovered"] += 1
        await self.session.commit()
        return stats

    # Получает заказ для пользователя.
    async def _get_user_order(self, order_id: int, user_id: int) -> Order:
        order = await self.order_crud.get_by_id(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заказ не найден")
        return order
