import asyncio
import logging

from src.models.order import Order, OrderStatus, Shipment, ShipmentStatus
from src.repositories.order_repo import CrudOrder
from src.repositories.session import async_session_maker
from src.services.admin_notification_service import (
    AdminNotificationService,
    delivered_alert_needs_retry,
    delivered_alert_retry_is_due,
    shipment_delivered_alert_retry_is_due,
    sync_shipment_delivered_alert,
)
from src.services.orders.supplier_tracking_shape import has_terminal_delivered_signal
from src.utils.datetime_fmt import utc_now_naive

logger = logging.getLogger(__name__)


# Legacy order-level A retry: только без Shipment и status=delivery. Не C.
async def run_delivered_alert_retry(order_id: int) -> dict:
    async with async_session_maker() as session:
        order = await session.get(Order, order_id)
        if order is None:
            return {"status": "not_found", "order_id": order_id}

        crud = CrudOrder(session=session, model=Order)
        if await crud.list_shipments_for_order(order_id):
            return {
                "status": "skipped",
                "reason": "has_shipments",
                "order_id": order_id,
            }

        status = str(order.status or "").lower()
        if status != OrderStatus.DELIVERY:
            return {"status": "skipped", "reason": "status", "order_id": order_id}

        tracking = dict(order.supplier_tracking_json or {})
        if not has_terminal_delivered_signal(
            tracking
        ) and not delivered_alert_needs_retry(order):
            return {"status": "skipped", "reason": "no_signal", "order_id": order_id}

        if not delivered_alert_retry_is_due(order):
            return {"status": "skipped", "reason": "not_due", "order_id": order_id}

        ok = await AdminNotificationService(session).sync_delivered_alert(
            order_id,
            checked_at=utc_now_naive(),
        )
        logger.info(
            "Очередь повторных отправлений оповещений о доставке заказа: "
            "заказ=%s ok=%s",
            order_id,
            ok,
        )
        return {
            "status": "ok" if ok else "retry_pending",
            "order_id": order_id,
        }


def run_delivered_alert_retry_job(order_id: int) -> dict:
    return asyncio.run(run_delivered_alert_retry(order_id))


# Повторная отправка PLACED delivered alert одной посылки.
async def run_shipment_delivered_alert_retry(shipment_id: int) -> dict:
    async with async_session_maker() as session:
        row = await session.get(Shipment, shipment_id)
        if row is None:
            return {"status": "not_found", "shipment_id": shipment_id}
        if str(row.status or "") != ShipmentStatus.DELIVERED:
            return {
                "status": "skipped",
                "reason": "status",
                "shipment_id": shipment_id,
            }
        if not shipment_delivered_alert_retry_is_due(row):
            return {
                "status": "skipped",
                "reason": "not_due",
                "shipment_id": shipment_id,
            }

    ok = await sync_shipment_delivered_alert(shipment_id, utc_now_naive())
    logger.info(
        "Очередь повторных отправлений оповещений о доставке посылки: "
        "shipment_id=%s ok=%s",
        shipment_id,
        ok,
    )
    return {
        "status": "ok" if ok else "retry_pending",
        "shipment_id": shipment_id,
    }


def run_shipment_delivered_alert_retry_job(shipment_id: int) -> dict:
    return asyncio.run(run_shipment_delivered_alert_retry(shipment_id))
