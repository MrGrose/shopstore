import logging
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.order import Order
from src.repositories.order_repo import CrudOrder
from src.services.notifications import (
    CUSTOMER_PAYMENT_FAILED_EVENT,
    NotificationChannel,
    NotificationDispatch,
    NotificationOrderEvent,
    notification_dispatcher,
)
from src.services.notifications.customer_notification_keys import (
    payment_late_received_key,
    payment_received_key,
)

logger = logging.getLogger(__name__)

CUSTOMER_NOTIFIED_EVENT = "customer_notified"


class CustomerNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)
        self.dispatcher = notification_dispatcher()

    @property
    def telegram_client(self):
        return self.dispatcher.telegram_client

    # Базовый dispatch клиентского уведомления по заказу.
    async def _dispatch(
        self,
        dispatch: NotificationDispatch,
    ) -> bool:
        return await self.dispatcher.enqueue(self.session, dispatch)

    # Отправляет клиенту уведомление об обновлении статуса заказа.
    async def notify_order_status(
        self,
        order_id: int,
        custom_message: str | None = None,
        created_by: str | None = None,
        idempotency_key: str | None = None,
        order_status: str | None = None,
    ) -> bool:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            return False
        resolved_key = idempotency_key or (
            f"customer:order_status:order:{order_id}:event:{uuid.uuid4()}"
        )
        resolved_status = (order_status or str(order.status or "")).strip()
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="order_status",
                payload={
                    "order_id": order_id,
                    "custom_message": custom_message,
                    "order_status": resolved_status,
                },
                created_by=created_by or "system",
                idempotency_key=resolved_key,
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Клиент уведомлён",
                ),
            )
        )

    # Уведомляет клиента об успешной оплате.
    async def notify_payment_received(
        self,
        order_id: int,
        created_by: str = "sbp",
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="payment.received",
                payload={"order_id": order_id},
                created_by=created_by,
                idempotency_key=payment_received_key(order_id),
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Клиент уведомлён об оплате",
                ),
            )
        )

    # Уведомляет клиента о поздней оплате после отмены заказа.
    async def notify_payment_late_received(
        self,
        order_id: int,
        attempt_id: int,
        created_by: str = "sbp",
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="payment.late.received",
                payload={"order_id": order_id, "attempt_id": attempt_id},
                created_by=created_by,
                idempotency_key=payment_late_received_key(order_id, attempt_id),
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Клиент уведомлён о поздней оплате после отмены",
                    payload_json={"payment_attempt_id": attempt_id},
                ),
            )
        )

    # Уведомляет клиента об ожидании оплаты (один раз на заказ).
    async def notify_payment_awaiting(
        self,
        order_id: int,
        created_by: str = "sbp",
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="payment.awaiting",
                payload={"order_id": order_id},
                created_by=created_by,
                idempotency_key=f"customer:payment.awaiting:order:{order_id}",
                record_order_event=NotificationOrderEvent(
                    event_type="customer_payment_awaiting_notified",
                    event_message="Клиент уведомлён об ожидании оплаты",
                ),
            )
        )

    # Уведомляет клиента о неуспешной оплате.
    async def notify_payment_failed(
        self,
        order_id: int,
        payment_attempt_id: int,
        created_by: str = "sbp",
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="payment.failed",
                payload={
                    "order_id": order_id,
                    "payment_attempt_id": payment_attempt_id,
                },
                created_by=created_by,
                idempotency_key=(
                    "customer:payment.failed:"
                    f"order:{order_id}:attempt:{payment_attempt_id}"
                ),
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_PAYMENT_FAILED_EVENT,
                    event_message="Клиент уведомлён о неуспешной оплате",
                    payload_json={"payment_attempt_id": payment_attempt_id},
                ),
            )
        )

    # Уведомляет клиента об изменении состава заказа.
    async def notify_order_composition_changed(
        self,
        order_id: int,
        diff: dict[str, object],
        new_total: Decimal,
        created_by: str | None = None,
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="composition.changed",
                payload={
                    "order_id": order_id,
                    "diff": diff,
                    "new_total": str(new_total),
                },
                created_by=created_by or "system",
                idempotency_key=(
                    "customer:composition.changed:"
                    f"order:{order_id}:event:{uuid.uuid4()}"
                ),
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Клиент уведомлён",
                ),
            )
        )

    # Уведомляет клиента после проверки наличия.
    async def notify_availability_check_result(
        self,
        order_id: int,
        removed_items: list[dict[str, object]],
        new_total: Decimal,
        created_by: str | None = None,
    ) -> bool:
        return await self._dispatch(
            NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="availability.check",
                payload={
                    "order_id": order_id,
                    "removed_items": removed_items,
                    "new_total": str(new_total),
                },
                created_by=created_by or "system",
                idempotency_key=(
                    f"customer:availability.check:order:{order_id}:event:{uuid.uuid4()}"
                ),
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Клиент уведомлён",
                ),
            )
        )
