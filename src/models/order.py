from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.repositories.database import Base


# Cтатусы заказа.
class OrderStatus(StrEnum):
    CREATED = "created"  # Созданный заказ, ожидающий оплаты.
    PROCESSING = "processing"  # Заказ в процессе сборки.
    ASSEMBLING = "assembling"  # Заказ собран и ожидает доставки.
    DELIVERY = "delivery"  # Заказ в процессе доставки.
    COMPLETED = "completed"  # Заказ выполнен.
    CANCELLED = "cancelled"  # Заказ отменен.
    FAILED = "failed"  # Заказ не выполнен из-за ошибки.


# Статус ручного подтверждения наличия при пограничном остатке.
class AvailabilityConfirmationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    UNAVAILABLE = "unavailable"


# Заказы в checkout-flow, где ещё ожидается оплата.
ACTIVE_UNPAID_ORDER_STATUSES: tuple[str, ...] = (
    OrderStatus.CREATED,
    OrderStatus.PROCESSING,
)

# Статусы, между которыми sync выставляет status по availability.
SYNCABLE_ORDER_STATUSES: frozenset[str] = frozenset(
    {OrderStatus.CREATED, OrderStatus.PROCESSING}
)

# Причина отмены: истёк срок оплаты.
CANCELLATION_REASON_PAYMENT_TIMEOUT = "payment_timeout"

# Причина отмены: клиент отменил заказ в ЛК.
CANCELLATION_REASON_CUSTOMER_REQUEST = "customer_request"

# Событие: автоотмена по таймауту оплаты.
ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT = "order_auto_cancelled_payment_timeout"

# Событие: клиент отменил неоплаченный заказ в ЛК.
ORDER_EVENT_CANCELLED_BY_CUSTOMER = "order_cancelled_by_customer"

# Событие: оплата после автоотмены.
ORDER_EVENT_LATE_PAYMENT_AFTER_AUTO_CANCEL = "late_payment_after_auto_cancel"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_order_idempotency"),
        Index("ix_orders_status_payment_due_at", "status", "payment_due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)  # Внутренний идентификатор заказа
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )  # Идентификатор клиента
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )  # Итоговая сумма заказа
    items_subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )  # Сумма товаров без доставки
    discount_items_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )  # Скидка по промокоду только на товары
    delivery_fee_eur_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("30")
    )  # Доставка в EUR на момент заказа
    paid_supplier_order_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Оплаченное число SO; None до оплаты
    delivery_fee_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )  # Доставка в RUB на момент заказа
    eur_rate_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )  # Курс EUR на момент заказа
    supplier_cost_eur_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )  # Себестоимость товаров в EUR на момент заказа
    promo_code_applied: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Промокод, примененный к заказу
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OrderStatus.CREATED
    )  # Текущий статус заказа
    availability_confirmation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AvailabilityConfirmationStatus.NOT_REQUIRED,
    )  # Подтверждение наличия при пограничном остатке
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Ключ защиты от повторного создания
    payment_provider: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # Провайдер оплаты
    payment_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )  # Идентификатор заказа в платежном провайдере
    payment_external_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Внешний идентификатор заказа в платежном провайдере
    payment_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )  # Текущий платежный статус у провайдера
    payment_qr_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Идентификатор QR-кода в СБП
    payment_qr_payload: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Payload для генерации QR-кода
    payment_meta_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Технические данные платежной интеграции
    payment_last_callback_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Время последнего callback от провайдера
    payment_paid_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Время подтверждения оплаты
    payment_due_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )  # Крайний срок оплаты заказа
    cancellation_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Причина отмены (payment_timeout и др.)

    last_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Фамилия получателя
    first_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Имя получателя
    street: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Улица доставки
    house: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Номер дома
    apartment: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Номер квартиры
    city: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Город доставки
    postal_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # Почтовый индекс
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # Телефон получателя
    notification_channels: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )  # Каналы уведомлений на момент оформления
    notification_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Email-снимок для уведомлений
    customer_data_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Снимок контактов клиента на момент заказа
    delivery_data_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Снимок адреса доставки на момент заказа
    supplier_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Номер заказа у поставщика
    supplier_tracking_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Трек-номер поставщика
    supplier_delivery_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Снимок адреса для поставщика
    supplier_tracking_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Нормализованный таймлайн доставки поставщика
    supplier_tracking_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    supplier_tracking_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    supplier_tracking_next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    supplier_tracking_last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    supplier_tracking_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    supplier_tracking_sync_state: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    supplier_availability_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Snapshot автопроверки наличия у поставщика
    failed_from_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # Статус до failed для восстановления

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )  # Время создания заказа
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now(), onupdate=func.now()
    )  # Время последнего обновления заказа


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )  # Внутренний идентификатор позиции
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), index=True, nullable=False
    )  # Ссылка на заказ
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=False
    )  # Ссылка на товар
    variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_variants.id"), index=True, nullable=True
    )  # Ссылка на вариант товара
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)  # Количество
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )  # Цена за единицу

    product_title_captured: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Зафиксированное название товара
    product_external_id_captured: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Зафиксированный внешний ID товара
    variant_external_id_captured: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Зафиксированный внешний ID варианта
    variant_sku_captured: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Зафиксированный SKU варианта
    variant_option1_captured: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Зафиксированная опция варианта 1
    variant_option2_captured: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Зафиксированная опция варианта 2
    variant_option3_captured: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Зафиксированная опция варианта 3
    supplier_price_eur_captured: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )  # Закупочная цена EUR за единицу на момент заказа
    category_l2_captured: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # L2 на момент создания позиции
    category_l3_captured: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # L3 на момент создания позиции


# Подпись варианта из option1/2/3 (один separator на все call sites).
def variant_label_from_options(
    *options: str | None,
    separator: str = " · ",
) -> str | None:
    parts = [
        str(option).strip() for option in options if option and str(option).strip()
    ]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return separator.join(parts)


# Подпись варианта из captured snapshot позиции заказа.
def order_item_captured_variant_label(
    item: OrderItem,
    *,
    separator: str = " · ",
) -> str | None:
    return variant_label_from_options(
        item.variant_option1_captured,
        item.variant_option2_captured,
        item.variant_option3_captured,
        separator=separator,
    )


class OrderPaymentAttempt(Base):
    __tablename__ = "order_payment_attempts"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_number", name="uq_order_payment_attempt"),
        UniqueConstraint("provider_order_id", name="uq_payment_attempt_provider_order"),
        UniqueConstraint("merchant_order_id", name="uq_payment_attempt_merchant_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), index=True, nullable=False
    )
    # Номер попытки оплаты
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Провайдер оплаты
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # Merchant order ID
    merchant_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # x-req-id order
    x_req_id_order: Mapped[str] = mapped_column(String(128), nullable=False)
    # x-req-id QR
    x_req_id_qr: Mapped[str] = mapped_column(String(128), nullable=False)
    # Сумма оплаты в minor units
    payment_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    # Валюта оплаты
    payment_currency: Mapped[str] = mapped_column(
        String(8), nullable=False, default="RUB"
    )
    # Начальное состояние попытки
    init_state: Mapped[str] = mapped_column(String(32), nullable=False)
    # Идентификатор заказа в провайдере
    provider_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Внешний идентификатор заказа в провайдере
    provider_external_order_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    # Текущий статус попытки в провайдере
    provider_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    # Время создания QR
    qr_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Время истечения QR
    qr_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    # Время оплаты
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Время последнего callback от провайдера
    last_callback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Время создания попытки
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
    # Время последнего обновления попытки
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now(), onupdate=func.now()
    )


class OrderEvent(Base):
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )  # Внутренний идентификатор события
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), index=True, nullable=False
    )  # Ссылка на заказ
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # Тип события
    event_message: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )  # Сообщение события
    created_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # Кто создал событие
    payload_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Дополнительные данные события
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )  # Время создания события


# Статус заказа у поставщика (закупка, не клиентский Order.status).
class SupplierOrderStatus(StrEnum):
    DRAFT = "draft"
    PLACED = "placed"
    CANCELLED = "cancelled"


# Заказ у Supplier-Demo: header закупки, не customer-facing shipment.
class SupplierOrder(Base):
    __tablename__ = "supplier_orders"
    __table_args__ = (
        UniqueConstraint("order_id", "seq", name="uq_supplier_orders_order_id_seq"),
        UniqueConstraint("external_id", name="uq_supplier_orders_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SupplierOrderStatus.DRAFT
    )
    goods_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    supplier_shipping_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("29.99")
    )
    placed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    placed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now(), onupdate=func.now()
    )


# Allocation: qty OrderItem внутри одного SupplierOrder.
class SupplierOrderLine(Base):
    __tablename__ = "supplier_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "supplier_order_id",
            "order_item_id",
            name="uq_supplier_order_lines_so_item",
        ),
        CheckConstraint(
            "quantity > 0", name="ck_supplier_order_lines_quantity_positive"
        ),
        Index("ix_supplier_order_lines_order_item_id", "order_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_order_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_supplier_eur: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )


# Клиентская посылка (fulfillment), не закупка SupplierOrder.
class ShipmentStatus(StrEnum):
    PREPARING = "preparing"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


# Customer-facing shipment; MVP 1 placed SO → 1 row.
class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("supplier_order_id", name="uq_shipments_supplier_order_id"),
        CheckConstraint(
            "status IN ('preparing', 'in_transit', 'delivered')",
            name="ck_shipments_status",
        ),
        Index("ix_shipments_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # INT FK на supplier_orders.id; не путать с Order.supplier_order_id (string TP).
    supplier_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_orders.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ShipmentStatus.PREPARING
    )
    supplier_carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_tracking_number: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    supplier_tracking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_carrier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer_tracking_number: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    customer_tracking_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_alert: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Admin fulfillment; не tracking delivered и не A.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=True, server_default=func.now(), onupdate=func.now()
    )
