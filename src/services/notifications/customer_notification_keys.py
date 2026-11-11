from collections.abc import Sequence

# Стабильные idempotency keys клиентских TG-уведомлений по заказу.

FINALIZE_CUSTOMER_NOTIFY_KEY = (
    "customer:order_status:order:{order_id}:event:delivered_to_customer"
)


# Ключ idempotency для TG-уведомления об оплате заказа.
def payment_received_key(order_id: int) -> str:
    return f"customer:payment.received:order:{order_id}"


# Ключ idempotency для TG о поздней оплате после отмены.
def payment_late_received_key(order_id: int, attempt_id: int) -> str:
    return f"customer:payment.late.received:order:{order_id}:attempt:{attempt_id}"


# Ключ idempotency для TG после подтверждения/отклонения наличия.
def availability_notify_key(order_id: int) -> str:
    return f"customer:availability.notify:order:{order_id}"


# Ключ idempotency для TG при переводе заказа в сборку.
def assembly_notify_key(order_id: int) -> str:
    return f"customer:assembly.notify:order:{order_id}"


# Ключ packing: одно письмо на оформленную посылку (SO), не на весь заказ.
def assembly_parcel_notify_key(order_id: int, supplier_order_id: int) -> str:
    return (
        f"customer:assembly.notify:order:{order_id}:supplier_order:{supplier_order_id}"
    )


# Ключ idempotency для TG при завершении доставки.
def finalize_notify_key(order_id: int) -> str:
    return FINALIZE_CUSTOMER_NOTIFY_KEY.format(order_id=order_id)


# Ключ idempotency customer B для одной Shipment. Не A и не finalize.
def shipment_delivered_notify_key(order_id: int, shipment_id: int) -> str:
    return (
        f"customer:order_status:order:{order_id}:shipment:{shipment_id}:event:delivered"
    )


# Order-level ключи. Per-shipment B сюда не входит — нет shipment_id.
def all_customer_outbox_keys(order_id: int) -> list[str]:
    return [
        payment_received_key(order_id),
        availability_notify_key(order_id),
        assembly_notify_key(order_id),
        finalize_notify_key(order_id),
    ]


# Order-level + per-shipment B. Для Journey и загрузки outbox, не для карточки.
def customer_outbox_keys_for_journey(
    order_id: int,
    shipment_ids: Sequence[int] = (),
) -> list[str]:
    keys = list(all_customer_outbox_keys(order_id))
    seen = set(keys)
    for shipment_id in shipment_ids:
        key = shipment_delivered_notify_key(order_id, int(shipment_id))
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys
