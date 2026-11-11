from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.client_texts import (
    format_customer_availability_confirmed_message,
    format_customer_availability_unavailable_message,
)
from src.content.supplier_availability_display import enrich_supplier_check_display
from src.core.config import settings
from src.core.order_limits import (
    calculate_customs_duty_rub,
    calculate_supplier_cost_eur,
    customs_duty_notice,
    estimate_supplier_orders,
    is_supplier_unit_storefront_allowed,
    live_supplier_lines,
)
from src.core.stock_display import buyer_stock_badge
from src.models.cart import CartItem
from src.models.order import (
    ACTIVE_UNPAID_ORDER_STATUSES,
    CANCELLATION_REASON_CUSTOMER_REQUEST,
    CANCELLATION_REASON_PAYMENT_TIMEOUT,
    ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
    ORDER_EVENT_CANCELLED_BY_CUSTOMER,
    SYNCABLE_ORDER_STATUSES,
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderItem,
    OrderPaymentAttempt,
    OrderStatus,
    order_item_captured_variant_label,
    variant_label_from_options,
)
from src.models.product import Product, ProductVariant
from src.models.user import User
from src.repositories.cart_repo import CrudCart
from src.repositories.order_repo import CrudOrder
from src.repositories.product_repo import CrudProduct, normalize_product_search_query
from src.schemas.money import format_eur
from src.schemas.order import (
    AdminAvailabilityConfirmationUpdate,
    AdminAvailabilityItemDecision,
    AdminAvailabilityStockCheckUpdate,
    AdminOrderItemAdd,
    AdminOrderItemsUpdate,
    AdminOrderProductSearchItem,
    AdminOrderProductSearchResponse,
    AdminOrderProductSearchVariant,
    AdminOrderStatusUpdate,
    AdminOrderUpdate,
    AdminStartAssemblingUpdate,
    AdminStartDeliveryUpdate,
    CheckoutPreviewSchema,
    DeliveryAddressCreate,
    OrderEventSchema,
    OrderSchema,
    OrderShipmentSchema,
)
from src.services.admin_notification_service import (
    AdminNotificationService,
    sync_order_completed_admin_alert,
)
from src.services.cart_variant_resolve import resolve_cart_variant_id
from src.services.catalog.read.caches import invalidate_if_catalog_boundary_changed
from src.services.catalog.stock.service import CatalogStockService
from src.services.customer_notification_service import (
    CUSTOMER_NOTIFIED_EVENT,
    CustomerNotificationService,
)
from src.services.delivery_profile_service import DeliveryProfileService
from src.services.identity_service import IdentityService
from src.services.notifications.customer_notification_keys import (
    FINALIZE_CUSTOMER_NOTIFY_KEY,
    assembly_notify_key,
    availability_notify_key,
    shipment_delivered_notify_key,
)
from src.services.notifications.dispatch import (
    NotificationChannel,
    NotificationDispatch,
    NotificationOrderEvent,
)
from src.services.notifications.inline_dispatcher import notification_dispatcher
from src.services.orders.shipments import (
    SHIPMENT_CUSTOMER_NOTIFY_ORDER_STATUS,
    build_order_shipment_schemas,
    ensure_shipment_identity_in_message,
    group_lines_by_supplier_order_id,
    group_shipments_by_order_id,
    render_shipment_customer_message,
    shipment_can_notify_customer,
)
from src.services.orders.supplier_availability.queue import (
    enqueue_supplier_availability,
)
from src.services.orders.supplier_availability.service import (
    validate_supplier_snapshot_for_admin_action,
)
from src.services.orders.supplier_orders import SupplierOrderService
from src.services.orders.supplier_tracking import (
    initialize_supplier_tracking,
    initialize_supplier_tracking_schedule,
)
from src.services.pricing_service import PricingService
from src.services.promo_service import PromoService
from src.services.referral_service import ReferralService
from src.utils.datetime_fmt import (
    format_datetime_msk,
    format_datetime_msk_short,
    utc_now_naive,
)
from src.utils.labels import display_product_title, translate_option_value
from src.utils.payment import (
    PAYMENT_EXHAUSTED_LABEL,
    PAYMENT_STATE_LABELS,
    attempt_payment_resumable,
    normalize_order_payment,
    normalize_order_payment_from_attempt,
    payment_attempts_exhausted,
    payment_deadline_blocks_payment,
)

_TERMINAL_CUSTOMER_MESSAGE_STATUSES = frozenset(
    {
        OrderStatus.CANCELLED,
        OrderStatus.COMPLETED,
        OrderStatus.FAILED,
    }
)


# Запрет повторного TG-уведомления при смене статуса без перехода.
def _reject_repeat_status_customer_notify(
    status: str, *, notify_customer: bool
) -> None:
    if not notify_customer:
        return
    normalized = str(status).lower()
    if normalized == OrderStatus.COMPLETED:
        raise ValueError(
            "Заказ уже выполнен — уведомление клиенту через смену статуса недоступно"
        )
    if normalized in {OrderStatus.CANCELLED, OrderStatus.FAILED}:
        raise ValueError(
            "Заказ в финальном статусе — уведомление клиенту через смену статуса "
            "недоступно"
        )


TELEGRAM_REQUIRED_MESSAGE = (
    "Вся коммуникация по заказу будет происходить через Telegram-бота. "
    "Для оформления заказа необходимо привязать личный кабинет "
    "к вашему Telegram-аккаунту."
)

ORDER_FINALIZE_CUSTOMER_NOTIFY_KEY = FINALIZE_CUSTOMER_NOTIFY_KEY


class _PendingAvailabilityTarget(TypedDict):
    order_item: OrderItem
    product_id: int
    variant_id: int | None


class TelegramRequiredError(Exception):
    code = "telegram_required"
    message = TELEGRAM_REQUIRED_MESSAGE

    def __init__(self) -> None:
        super().__init__(self.message)


# Нормализует query status (один или несколько через запятую) для фильтра админки.
def normalize_admin_order_status_filter(status_filter: str | None) -> list[str] | None:
    if not status_filter or not status_filter.strip():
        return None
    valid = {status.value for status in OrderStatus}
    result: list[str] = []
    for part in status_filter.split(","):
        code = part.strip().lower()
        if code in valid and code not in result:
            result.append(code)
    return result or None


class OrderService:
    LEGACY_CENTS_THRESHOLD = Decimal("100000")
    STATUS_LABELS: dict[str, str] = {
        OrderStatus.CREATED: "Заказ создан",
        OrderStatus.PROCESSING: "В обработке",
        OrderStatus.ASSEMBLING: "Ожидает отправки",
        OrderStatus.DELIVERY: "В доставке",
        OrderStatus.COMPLETED: "Выполнен",
        OrderStatus.CANCELLED: "Отменен",
        OrderStatus.FAILED: "Ошибка",
    }
    AVAILABILITY_STATUS_LABELS: dict[str, str] = {
        AvailabilityConfirmationStatus.NOT_REQUIRED: "Не требуется",
        AvailabilityConfirmationStatus.PENDING: "Проверяем наличие",
        AvailabilityConfirmationStatus.CONFIRMED: "Наличие подтверждено",
        AvailabilityConfirmationStatus.UNAVAILABLE: "Товар недоступен",
    }
    AVAILABILITY_PENDING_MESSAGE = (
        "Проверяем наличие. Оплата станет доступна после проверки."
    )
    AVAILABILITY_UNAVAILABLE_MESSAGE = "Часть товаров недоступна."

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)
        self.cart_crud = CrudCart(session=session, model=CartItem)
        self.product_crud = CrudProduct(session=session, model=Product)
        self.pricing_service = PricingService(session=session)
        self.promo_service = PromoService(session=session)

    # Целевой status по availability (created vs processing).
    @staticmethod
    def _status_target_from_availability(availability: str) -> str:
        normalized = str(
            availability or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        if normalized in {
            AvailabilityConfirmationStatus.PENDING,
            AvailabilityConfirmationStatus.UNAVAILABLE,
        }:
            return OrderStatus.PROCESSING
        return OrderStatus.CREATED

    # Синхронизирует status с availability для активных заказов до доставки.
    async def _sync_order_status_from_availability(
        self,
        order: Order,
        created_by: str,
        record_event: bool = True,
    ) -> bool:
        current = str(order.status or "").lower()
        if current not in SYNCABLE_ORDER_STATUSES:
            return False
        target = self._status_target_from_availability(
            str(order.availability_confirmation_status or "")
        )
        if current == target:
            return False
        previous = current
        order.status = target
        if not record_event:
            return True
        reason = (
            "availability_check_required"
            if target == OrderStatus.PROCESSING
            else "availability_resolved"
        )
        await self.order_crud.create_order_event(
            order_id=order.id,
            event_type="status_changed",
            event_message=f"Статус синхронизирован: {previous} → {target}",
            created_by=created_by,
            payload_json={
                "before": previous,
                "after": target,
                "reason": reason,
            },
        )
        return True

    # Допустимые ручные переходы статуса с учётом оплаты и availability.
    def allowed_next_statuses_for_order(self, order: Order | OrderSchema) -> list[str]:
        current = str(order.status or "").lower()
        availability = str(
            order.availability_confirmation_status
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        failed_from = getattr(order, "failed_from_status", None)
        failed_from_status = str(failed_from or "").lower() or None
        allowed: set[str] = set()

        if current in {OrderStatus.CANCELLED, OrderStatus.COMPLETED}:
            return []

        if current == OrderStatus.CREATED:
            allowed.update({OrderStatus.CANCELLED, OrderStatus.FAILED})
        elif current == OrderStatus.PROCESSING:
            allowed.update({OrderStatus.CANCELLED, OrderStatus.FAILED})
        elif current == OrderStatus.ASSEMBLING:
            allowed.add(OrderStatus.FAILED)
        elif current == OrderStatus.DELIVERY:
            allowed.update({OrderStatus.COMPLETED, OrderStatus.FAILED})
        elif current == OrderStatus.FAILED:
            allowed.add(OrderStatus.CANCELLED)
            if failed_from_status == OrderStatus.ASSEMBLING:
                allowed.add(OrderStatus.ASSEMBLING)
            elif failed_from_status == OrderStatus.DELIVERY:
                allowed.add(OrderStatus.DELIVERY)
            elif failed_from_status in {
                OrderStatus.CREATED,
                OrderStatus.PROCESSING,
            }:
                if availability in {
                    AvailabilityConfirmationStatus.CONFIRMED,
                    AvailabilityConfirmationStatus.NOT_REQUIRED,
                }:
                    allowed.add(OrderStatus.CREATED)
                elif availability in {
                    AvailabilityConfirmationStatus.PENDING,
                    AvailabilityConfirmationStatus.UNAVAILABLE,
                }:
                    allowed.add(OrderStatus.PROCESSING)
            else:
                if availability in {
                    AvailabilityConfirmationStatus.CONFIRMED,
                    AvailabilityConfirmationStatus.NOT_REQUIRED,
                }:
                    allowed.add(OrderStatus.CREATED)
                elif availability in {
                    AvailabilityConfirmationStatus.PENDING,
                    AvailabilityConfirmationStatus.UNAVAILABLE,
                }:
                    allowed.add(OrderStatus.PROCESSING)
        return sorted(allowed)

    # Оплата, статус и availability позволяют assembling (без проверки TP ID).
    @classmethod
    def assembling_preconditions_ok(cls, order: Order | OrderSchema) -> bool:
        status = str(getattr(order, "status", "") or "").lower()
        if status not in {
            OrderStatus.CREATED,
            OrderStatus.PROCESSING,
            OrderStatus.ASSEMBLING,
        }:
            return False
        payment_state = str(getattr(order, "payment_state", "") or "").lower()
        paid = getattr(order, "payment_paid_at", None) is not None or payment_state in {
            "paid",
            "late_paid_after_cancel",
        }
        if not paid:
            return False
        availability = str(
            getattr(order, "availability_confirmation_status", None)
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        return availability in {
            AvailabilityConfirmationStatus.CONFIRMED,
            AvailabilityConfirmationStatus.NOT_REQUIRED,
        }

    # True если packing-счётчик — положительное int.
    @staticmethod
    def _positive_pack_count(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    # Можно ли передать оплаченный заказ в сборку у поставщика.
    @classmethod
    def can_start_assembling(
        cls,
        order: Order | OrderSchema,
        *,
        supplier_orders: Sequence[object] | None = None,
        packing: Mapping[str, object] | None = None,
    ) -> bool:
        if getattr(order, "supplier_order_id", None):
            return False
        if supplier_orders:
            return False
        if packing and (
            packing.get("can_create")
            or cls._positive_pack_count(packing.get("placed_count"))
            or cls._positive_pack_count(packing.get("placeable_count"))
        ):
            return False
        return cls.assembling_preconditions_ok(order)

    # Пишет assembling + tracking + event; без commit (для place SO и формы).
    async def _apply_assembling_transition(
        self,
        order: Order,
        supplier_order_id: str,
        created_by: str,
        event_message: str | None,
        supplier_delivery_json: dict | None = None,
        *,
        write_legacy_tp: bool = True,
    ) -> None:
        previous_status = order.status
        if write_legacy_tp and not str(order.supplier_order_id or "").strip():
            order.supplier_order_id = supplier_order_id
        delivery_snapshot = supplier_delivery_json
        if delivery_snapshot is None:
            delivery_snapshot = order.delivery_data_json
        order.supplier_delivery_json = delivery_snapshot
        order.status = OrderStatus.ASSEMBLING
        if write_legacy_tp:
            initialize_supplier_tracking(order)
        else:
            initialize_supplier_tracking_schedule(order)
        await self.order_crud.create_order_event(
            order_id=order.id,
            event_type="assembly_started",
            event_message=event_message or "Заказ передан в сборку",
            created_by=created_by,
            payload_json={
                "before": previous_status,
                "after": OrderStatus.ASSEMBLING,
                "supplier_order_id": supplier_order_id,
            },
        )

    # Первый placed SO: assembling, если guards позволяют и статус ещё не assembling.
    async def apply_assembling_after_first_place(
        self, order: Order, supplier_order_id: str
    ) -> None:
        if str(order.status or "").lower() == OrderStatus.ASSEMBLING:
            return
        if not self.assembling_preconditions_ok(order):
            return
        await self._apply_assembling_transition(
            order,
            supplier_order_id,
            created_by="admin",
            event_message=None,
            write_legacy_tp=False,
        )

    # Клиентский лейбл этапа (ЛК/TG): учитывает оплату при status=created.
    @classmethod
    def resolve_customer_status_label(cls, order: Order | OrderSchema) -> str:
        status = str(order.status or "").lower()
        availability = str(
            getattr(order, "availability_confirmation_status", None)
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        paid = getattr(order, "payment_paid_at", None) is not None

        if status == OrderStatus.CREATED:
            return "Оформляем у поставщика" if paid else "Ожидает оплаты"
        if status == OrderStatus.PROCESSING:
            if availability == AvailabilityConfirmationStatus.PENDING:
                return "Проверяем наличие"
            return cls.STATUS_LABELS.get(status, status)
        if status == OrderStatus.ASSEMBLING:
            return "Готовится к отправке"
        if status == OrderStatus.DELIVERY:
            return "В пути"
        if status == OrderStatus.COMPLETED:
            return "Доставлен"
        return cls.STATUS_LABELS.get(status, status)

    # Лейбл этапа для админки (pill в карточке заказа).
    @classmethod
    def resolve_admin_status_label(cls, order: Order | OrderSchema) -> str:
        status = str(order.status or "").lower()
        availability = str(
            getattr(order, "availability_confirmation_status", None)
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        paid = getattr(order, "payment_paid_at", None) is not None

        if status == OrderStatus.CREATED:
            return "Оплачен · ожидает TP" if paid else "Ожидает оплаты"
        if status == OrderStatus.PROCESSING:
            if availability == AvailabilityConfirmationStatus.PENDING:
                return "Проверка наличия"
            return cls.STATUS_LABELS.get(status, status)
        return cls.STATUS_LABELS.get(status, status)

    # Варианты select «Статус заказа» и подсказка для админки.
    @classmethod
    def admin_status_select_context(
        cls,
        order: Order | OrderSchema,
        allowed: list[str],
    ) -> tuple[list[str], str | None]:
        choices = sorted({str(order.status or "").lower(), *allowed})
        hint: str | None = None
        if cls.can_start_assembling(order):
            choices = sorted(allowed)
            hint = "Следующий шаг — блок «Сборка» ниже."
        return choices, hint

    # Нормализует доступный остаток: None/отрицательные → 0.
    @staticmethod
    def normalize_available_quantity(raw: int | None) -> int:
        if raw is None:
            return 0
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    # Пограничный остаток: доступно меньше порога STOCK_LOW_MIN_QTY.
    @staticmethod
    def is_borderline_available(available: int | None) -> bool:
        qty = OrderService.normalize_available_quantity(available)
        return qty > 0 and qty < settings.STOCK_LOW_MIN_QTY

    # Статус подтверждения наличия по списку пограничных позиций.
    @staticmethod
    def resolve_availability_status(
        low_stock_items: Sequence[object] | None,
    ) -> str:
        if low_stock_items:
            return AvailabilityConfirmationStatus.PENDING
        return AvailabilityConfirmationStatus.NOT_REQUIRED

    # Крайний срок оплаты от текущего момента.
    @staticmethod
    def payment_deadline_from_now() -> datetime:
        return utc_now_naive() + timedelta(hours=settings.ORDER_PAYMENT_DEADLINE_HOURS)

    # Можно ли инициировать оплату по статусу заказа и подтверждению наличия.
    @staticmethod
    def compute_payment_allowed(
        order: Order,
        latest_attempt=None,
    ) -> bool:
        status = str(order.status or "").lower()
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.FAILED,
            OrderStatus.COMPLETED,
            OrderStatus.ASSEMBLING,
            OrderStatus.DELIVERY,
        }:
            return False
        if order.payment_paid_at is not None:
            return False
        availability = str(
            order.availability_confirmation_status
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        if availability in {
            AvailabilityConfirmationStatus.PENDING,
            AvailabilityConfirmationStatus.UNAVAILABLE,
        }:
            return False
        if payment_deadline_blocks_payment(order.payment_due_at, latest_attempt):
            return False
        return True

    # Можно ли клиенту отменить неоплаченный заказ в ЛК.
    @staticmethod
    def evaluate_customer_cancel_allowed(
        order: Order,
        latest_attempt=None,
        now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        if order.payment_paid_at is not None:
            return False, None
        status = str(order.status or "").lower()
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.COMPLETED,
            OrderStatus.FAILED,
        }:
            return False, None
        if status not in ACTIVE_UNPAID_ORDER_STATUSES:
            return False, None
        check_at = now or utc_now_naive()
        if attempt_payment_resumable(latest_attempt, check_at):
            return (
                False,
                "Сейчас идёт оплата. Отменить можно после истечения QR-кода "
                "или если оплата не пройдёт.",
            )
        return True, None

    # Сообщение клиенту по статусу подтверждения наличия.
    @classmethod
    def availability_message_for_status(cls, status: str | None) -> str | None:
        normalized = str(status or AvailabilityConfirmationStatus.NOT_REQUIRED).lower()
        if normalized == AvailabilityConfirmationStatus.PENDING:
            return cls.AVAILABILITY_PENDING_MESSAGE
        if normalized == AvailabilityConfirmationStatus.UNAVAILABLE:
            return cls.AVAILABILITY_UNAVAILABLE_MESSAGE
        return None

    # Создает заказ из корзины и очищает корзину после создания.
    async def create_order(
        self,
        user_id: int,
        idempotency_key: str | None,
        delivery_payload: dict[str, str | None] | None = None,
        promo_code: str | None = None,
        notification_channels: list[str] | None = None,
        notification_email: str | None = None,
    ) -> OrderSchema:
        existing_order = await self.order_crud.get_by_idempotency_key(idempotency_key)
        if existing_order:
            order_items = await self._build_order_items(existing_order.id)
            return await self._build_order_schema_async(existing_order, order_items)

        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError("Пользователь не найден")
        channels = sorted(
            {str(item).strip().lower() for item in (notification_channels or [])}
        )
        if not channels or any(item not in {"telegram", "email"} for item in channels):
            raise ValueError("Выберите канал уведомлений")
        identity = IdentityService(self.session)
        telegram_id = await identity.get_telegram_id_for_user(user)
        if "telegram" in channels and telegram_id is None:
            raise TelegramRequiredError()
        normalized_email = (notification_email or "").strip().lower() or None
        if "email" in channels:
            email_identity = await identity.identity_repo.get_email_by_address(
                normalized_email or ""
            )
            if email_identity is None or email_identity.user_id != user.id:
                raise ValueError("Сначала подтвердите email")

        delivery_model: DeliveryAddressCreate | None = None
        if delivery_payload is not None:
            validated_delivery = DeliveryAddressCreate.model_validate(delivery_payload)
            delivery_model = validated_delivery
            delivery_payload = validated_delivery.model_dump()

        cart_items = await self.cart_crud.get_user_cart(user_id=user_id)
        if not cart_items:
            raise ValueError("Корзина пуста")
        products_map, variant_map = await self._load_checkout_products_context(
            cart_items
        )
        supplier_cost_eur = calculate_supplier_cost_eur(cart_items, products_map)
        pricing_settings = await self.pricing_service.get_settings()
        eur_rate = Decimal(pricing_settings.eur_rate)
        estimate = estimate_supplier_orders(
            supplier_cost_eur,
            Decimal(pricing_settings.delivery_fee_eur),
            len(cart_items),
            supplier_lines=live_supplier_lines(cart_items, products_map),
        )
        reserved_map = await self.order_crud.get_reserved_quantities(
            [item.product_id for item in cart_items]
        )

        await self._validate_cart_items_stock(
            cart_items, products_map, variant_map, reserved_map
        )
        low_stock_items = await self._collect_low_stock_items(
            cart_items, products_map, variant_map, reserved_map
        )
        availability_status = self.resolve_availability_status(low_stock_items)
        initial_status = (
            OrderStatus.PROCESSING
            if availability_status == AvailabilityConfirmationStatus.PENDING
            else OrderStatus.CREATED
        )

        now = utc_now_naive()
        active_unpaid = await self.order_crud.count_active_unpaid_orders(user_id, now)
        if active_unpaid >= settings.ORDER_MAX_ACTIVE_UNPAID_ORDERS_PER_USER:
            raise ValueError(
                "У вас уже есть несколько активных неоплаченных заказов. "
                "Оплатите или дождитесь отмены существующих заказов."
            )

        payload: list[dict[str, int | Decimal | str | None]] = []
        items_subtotal = Decimal("0")
        for item in cart_items:
            product = products_map.get(item.product_id)
            effective_variant_id = (
                resolve_cart_variant_id(product, item.variant_id)
                if product is not None
                else item.variant_id
            )
            variant = (
                variant_map.get(effective_variant_id)
                if effective_variant_id is not None
                else None
            )
            normalized_unit_price = self._normalize_price_snapshot(
                value=(
                    Decimal(product.sale_price)
                    if product is not None
                    else Decimal(item.price_snapshot)
                ),
            )
            row = self._build_order_item_payload(
                cart_item=item,
                unit_price=normalized_unit_price,
                product=product,
                variant=variant,
            )
            if effective_variant_id is not None:
                row["variant_id"] = effective_variant_id
            payload.append(row)
            items_subtotal += normalized_unit_price * item.quantity

        discount_amount, promo = await self.promo_service.calculate_discount(
            promo_code=promo_code,
            items_subtotal=items_subtotal,
            user_id=user_id,
        )
        delivery_fee_rub = self.pricing_service.calculate_delivery_rub(
            delivery_fee_eur=estimate.client_shipping_eur,
            eur_rate=eur_rate,
        )
        total_amount = items_subtotal - discount_amount + delivery_fee_rub

        customer_data_json = await self._build_customer_data_json(
            user_id, delivery_model
        )
        delivery_data_json: dict[str, object] | None = (
            dict(delivery_payload) if isinstance(delivery_payload, dict) else None
        )

        order = await self.order_crud.create_order_with_items(
            user_id=user_id,
            total_amount=total_amount,
            items_subtotal_amount=items_subtotal,
            discount_items_amount=discount_amount,
            delivery_fee_eur_snapshot=estimate.client_shipping_eur,
            delivery_fee_amount=delivery_fee_rub,
            eur_rate_snapshot=eur_rate,
            supplier_cost_eur_snapshot=supplier_cost_eur,
            promo_code_applied=promo.code if promo else None,
            items_payload=payload,
            idempotency_key=idempotency_key,
            delivery_payload=delivery_payload,
            customer_data_json=customer_data_json,
            delivery_data_json=delivery_data_json,
            availability_confirmation_status=availability_status,
            payment_due_at=None,
            status=initial_status,
            notification_channels=channels,
            notification_email=normalized_email,
        )
        if availability_status != AvailabilityConfirmationStatus.PENDING:
            base = order.created_at or utc_now_naive()
            order.payment_due_at = base + timedelta(
                hours=settings.ORDER_PAYMENT_DEADLINE_HOURS
            )
        await self.promo_service.register_usage(
            promo=promo, order_id=order.id, user_id=user_id
        )
        await self.order_crud.create_order_event(
            order_id=order.id,
            event_type="order_created",
            event_message="Заказ принят в обработку",
            created_by="system",
        )
        if low_stock_items:
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="availability_confirmation_requested",
                event_message="Требуется подтверждение наличия",
                created_by="system",
                payload_json={"items": low_stock_items},
            )
        admin_notify = AdminNotificationService(self.session)
        await admin_notify.send_order_created(order.id)
        await admin_notify.send_availability_review_required(order.id)
        product_ids = [int(item.product_id) for item in cart_items]
        stock_result = await CatalogStockService(self.session).refresh_products(
            product_ids
        )
        await self.session.commit()
        await self.session.refresh(order)
        if availability_status == AvailabilityConfirmationStatus.PENDING:
            enqueue_supplier_availability(order.id)
        invalidate_if_catalog_boundary_changed(
            stock_result.boundary_flipped_ids,
            reason="order_stock_boundary",
        )
        order_items = await self._build_order_items(order.id)
        await self.cart_crud.clear_user_cart(user_id=user_id)
        if delivery_model is not None:
            await DeliveryProfileService(self.session).upsert_from_delivery(
                user_id,
                delivery_model,
                auto_commit=True,
            )
        return await self._build_order_schema_async(order, order_items)

    # Собирает снимок контактов клиента на момент заказа.
    async def _build_customer_data_json(
        self,
        user_id: int,
        delivery: DeliveryAddressCreate | None,
    ) -> dict[str, object] | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        identity_svc = IdentityService(self.session)
        telegram_id = await identity_svc.get_telegram_id_for_user(user)
        telegram_username = await identity_svc.get_telegram_username_for_user(user)
        return {
            "email": user.email,
            "name": user.name,
            "phone": delivery.phone if delivery else None,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
        }

    # Проверяет наличие и остатки позиций корзины перед checkout.
    async def _validate_cart_items_stock(
        self,
        cart_items: list[CartItem],
        products_map: dict[int, Product],
        variant_map: dict[int, ProductVariant],
        reserved_map: dict[int, int],
    ) -> None:
        variant_ids: list[int] = []
        for item in cart_items:
            product = products_map.get(item.product_id)
            if product is None:
                continue
            effective_variant_id = resolve_cart_variant_id(product, item.variant_id)
            if effective_variant_id is not None:
                variant_ids.append(effective_variant_id)
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        for item in cart_items:
            product = products_map.get(item.product_id)
            if not product or not product.is_active:
                raise ValueError("Товар недоступен")
            if not is_supplier_unit_storefront_allowed(product.supplier_price_eur):
                raise ValueError("Товар недоступен")
            effective_variant_id = resolve_cart_variant_id(product, item.variant_id)
            if product.variants and effective_variant_id is None:
                raise ValueError("Выберите вариант товара")
            if effective_variant_id is not None:
                variant = variant_map.get(effective_variant_id)
                if not variant or variant.product_id != item.product_id:
                    raise ValueError("Вариант товара недоступен")
                if not variant.available:
                    raise ValueError("Выбранный вариант недоступен")
                reserved = variant_reserved_map.get(effective_variant_id, 0)
                available = self.normalize_available_quantity(
                    int(variant.inventory_quantity) - reserved
                )
            else:
                reserved = reserved_map.get(item.product_id, 0)
                available = self.normalize_available_quantity(
                    int(product.stock) - reserved
                )
            if item.quantity > available:
                raise ValueError("Недостаточно товара на складе")

    # Собирает позиции корзины с пограничным остатком для ручного подтверждения.
    async def _collect_low_stock_items(
        self,
        cart_items: list[CartItem],
        products_map: dict[int, Product],
        variant_map: dict[int, ProductVariant],
        reserved_map: dict[int, int],
    ) -> list[dict[str, object]]:
        variant_ids: list[int] = []
        for item in cart_items:
            product = products_map.get(item.product_id)
            if product is None:
                continue
            effective_variant_id = resolve_cart_variant_id(product, item.variant_id)
            if effective_variant_id is not None:
                variant_ids.append(effective_variant_id)
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        low_stock_items: list[dict[str, object]] = []
        for item in cart_items:
            product = products_map.get(item.product_id)
            if not product:
                continue
            effective_variant_id = resolve_cart_variant_id(product, item.variant_id)
            if effective_variant_id is not None:
                variant = variant_map.get(effective_variant_id)
                if not variant:
                    continue
                reserved = variant_reserved_map.get(effective_variant_id, 0)
                available = self.normalize_available_quantity(
                    int(variant.inventory_quantity) - reserved
                )
            else:
                reserved = reserved_map.get(item.product_id, 0)
                available = self.normalize_available_quantity(
                    int(product.stock) - reserved
                )
            if not self.is_borderline_available(available):
                continue
            title = product.title or f"Товар #{item.product_id}"
            variant_label: str | None = None
            if effective_variant_id is not None:
                variant = variant_map.get(effective_variant_id)
                if variant is not None:
                    variant_label = variant_label_from_options(
                        variant.option1,
                        variant.option2,
                        variant.option3,
                    )
            badge = buyer_stock_badge(
                available,
                ok_from_qty=settings.STOCK_OK_FROM_QTY,
                low_min_qty=settings.STOCK_LOW_MIN_QTY,
                label_in_stock="в наличии",
                label_low="мало",
                label_last="последний",
                label_out="нет",
            )
            low_stock_items.append(
                {
                    "product_id": item.product_id,
                    "variant_id": effective_variant_id,
                    "product_title": title,
                    "variant_label": variant_label,
                    "quantity": item.quantity,
                    "available": available,
                    "stock_badge": badge.text,
                }
            )
        return low_stock_items

    # Флаги видимости товара на витрине для строки проверки остатка.
    @staticmethod
    def _storefront_visibility_for_item(
        product: Product | None,
        variant: ProductVariant | None,
        effective_variant_id: int | None,
    ) -> dict[str, bool | None]:
        if product is None:
            return {
                "is_active": False,
                "catalog_in_stock": False,
                "variant_available": None,
                "is_on_storefront": False,
                "is_removed_from_storefront": True,
            }
        is_active = bool(product.is_active)
        catalog_in_stock = bool(product.catalog_in_stock)
        variant_available: bool | None = None
        if effective_variant_id is not None and variant is not None:
            variant_available = bool(variant.available)
            is_on_storefront = is_active and variant_available
        else:
            is_on_storefront = is_active
        return {
            "is_active": is_active,
            "catalog_in_stock": catalog_in_stock,
            "variant_available": variant_available,
            "is_on_storefront": is_on_storefront,
            "is_removed_from_storefront": not is_on_storefront,
        }

    # Собирает название товара для админки: #id и полный title как в карточке товара.
    @staticmethod
    def _admin_product_display_name(
        product: Product | None,
        fallback_title: str,
        variant_label: str | None,
    ) -> str:
        name = (product.title if product and product.title else fallback_title).strip()
        if not variant_label:
            return name
        needle = variant_label.strip()
        if needle and needle.lower() not in name.lower():
            return f"{name} - {needle}"
        return name

    # Собирает подпись варианта для админского picker.
    @staticmethod
    def _admin_variant_label(variant: ProductVariant) -> str | None:
        parts = [
            translate_option_value(opt)
            for opt in (variant.option1, variant.option2, variant.option3)
            if opt
        ]
        return " · ".join(parts) if parts else None

    # Ищет товары для добавления в заказ (id, название, SKU).
    async def search_products_for_admin_pick(
        self,
        q: str,
        limit: int = 12,
    ) -> AdminOrderProductSearchResponse:
        query = normalize_product_search_query(q)
        if not query:
            return AdminOrderProductSearchResponse()
        page_size = max(1, min(limit, 20))
        products, _, _ = await self.product_crud.paginate_products(
            page=1,
            page_size=page_size,
            q=query,
            include_out_of_stock=True,
            count_total=False,
            load_product_images=False,
        )
        items: list[AdminOrderProductSearchItem] = []
        for stub in products:
            product = await self.product_crud.get_by_id_with_related(stub.id)
            if product is None:
                continue
            variants: list[AdminOrderProductSearchVariant] = []
            product_price = (
                Decimal(product.sale_price) if product.sale_price is not None else None
            )
            for variant in product.variants or []:
                variant_price = (
                    Decimal(variant.price)
                    if variant.price is not None
                    else product_price
                )
                variants.append(
                    AdminOrderProductSearchVariant(
                        id=int(variant.id),
                        label=self._admin_variant_label(variant),
                        sale_price=variant_price,
                        sku=variant.sku,
                    )
                )
            items.append(
                AdminOrderProductSearchItem(
                    id=int(product.id),
                    title=display_product_title(product.title),
                    sale_price=product_price,
                    variants=variants,
                )
            )
        return AdminOrderProductSearchResponse(items=items)

    # Собирает позиции заказа с остатками для ручной проверки в админке.
    async def build_availability_stock_rows(
        self, order_id: int
    ) -> list[dict[str, object]]:
        pending_targets = await self._resolve_pending_availability_rows(order_id)
        if not pending_targets:
            return []
        product_ids = list({row["product_id"] for row in pending_targets})
        products = await self.product_crud.get_by_ids(product_ids)
        products_map = {product.id: product for product in products}
        reserved_map = await self.order_crud.get_reserved_quantities(product_ids)
        variant_ids = [
            row["variant_id"]
            for row in pending_targets
            if row["variant_id"] is not None
        ]
        variant_reserved_map = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )
        variant_map = await self._get_variants_by_ids(variant_ids)
        rows: list[dict[str, object]] = []
        order = await self.order_crud.get_by_id(order_id)
        supplier_snapshot = (
            dict(order.supplier_availability_json or {})
            if order is not None and isinstance(order.supplier_availability_json, dict)
            else {}
        )
        supplier_items = {
            int(row["order_item_id"]): row
            for row in (supplier_snapshot.get("items") or [])
            if isinstance(row, dict) and isinstance(row.get("order_item_id"), int)
        }
        for target in pending_targets:
            item = target["order_item"]
            product = products_map.get(item.product_id)
            title = getattr(item, "product_title", None) or (
                product.title if product else f"Товар #{item.product_id}"
            )
            variant_label = variant_label_from_options(
                getattr(item, "variant_option1", None),
                getattr(item, "variant_option2", None),
                getattr(item, "variant_option3", None),
            )
            effective_variant_id = target.get("variant_id")
            variant: ProductVariant | None = (
                variant_map.get(int(effective_variant_id))
                if effective_variant_id is not None
                else None
            )
            inventory: int | None = None
            available: int | None = None
            if product is not None:
                if effective_variant_id is not None and variant is not None:
                    inventory = int(variant.inventory_quantity)
                    reserved = variant_reserved_map.get(int(effective_variant_id), 0)
                    available = self.normalize_available_quantity(inventory - reserved)
                else:
                    inventory = int(product.stock)
                    reserved = reserved_map.get(item.product_id, 0)
                    available = self.normalize_available_quantity(inventory - reserved)
            storefront = self._storefront_visibility_for_item(
                product, variant, effective_variant_id
            )
            admin_product_name = self._admin_product_display_name(
                product, title, variant_label
            )
            supplier_product_url = (
                str(product.product_url).strip()
                if product is not None and product.product_url
                else None
            )
            supplier_row = supplier_items.get(int(item.id))
            if isinstance(supplier_row, dict):
                supplier_row = enrich_supplier_check_display(supplier_row)
            rows.append(
                {
                    "order_item_id": item.id,
                    "variant_id": effective_variant_id,
                    "product_id": item.product_id,
                    "product_title": title,
                    "admin_product_name": admin_product_name,
                    "variant_label": variant_label,
                    "quantity": item.quantity,
                    "inventory": inventory,
                    "available": available,
                    "admin_product_url": (
                        f"/internal/admin/products?id={item.product_id}"
                    ),
                    "supplier_product_url": supplier_product_url,
                    "supplier_check": supplier_row,
                    **storefront,
                }
            )
        return rows

    # Рассчитывает summary checkout с учетом промокода без создания заказа.
    async def preview_checkout(
        self, user_id: int, promo_code: str | None = None
    ) -> CheckoutPreviewSchema:
        cart_items = await self.cart_crud.get_user_cart(user_id=user_id)
        if not cart_items:
            raise ValueError("Корзина пуста")
        products, variant_map = await self._load_checkout_products_context(cart_items)
        supplier_cost_eur = calculate_supplier_cost_eur(cart_items, products)
        pricing_settings = await self.pricing_service.get_settings()
        eur_rate = Decimal(pricing_settings.eur_rate)
        estimate = estimate_supplier_orders(
            supplier_cost_eur,
            Decimal(pricing_settings.delivery_fee_eur),
            len(cart_items),
            supplier_lines=live_supplier_lines(cart_items, products),
        )
        reserved_map = await self.order_crud.get_reserved_quantities(
            [item.product_id for item in cart_items]
        )
        await self._validate_cart_items_stock(
            cart_items, products, variant_map, reserved_map
        )
        low_stock_items = await self._collect_low_stock_items(
            cart_items, products, variant_map, reserved_map
        )
        items_subtotal = self._calculate_items_subtotal(
            cart_items, products, variant_map
        )
        discount_amount, promo = await self.promo_service.calculate_discount(
            promo_code=promo_code,
            items_subtotal=items_subtotal,
            user_id=user_id,
        )
        delivery_fee_rub = self.pricing_service.calculate_delivery_rub(
            delivery_fee_eur=estimate.client_shipping_eur,
            eur_rate=eur_rate,
        )
        customs_duty_amount = calculate_customs_duty_rub(supplier_cost_eur, eur_rate)
        discounted_items_subtotal = items_subtotal - discount_amount
        total_amount = discounted_items_subtotal + delivery_fee_rub
        return CheckoutPreviewSchema(
            items_subtotal_amount=items_subtotal,
            discounted_items_subtotal_amount=discounted_items_subtotal,
            discount_items_amount=discount_amount,
            delivery_fee_amount=delivery_fee_rub,
            total_amount=total_amount,
            promo_code_applied=promo.code if promo else None,
            supplier_cost_eur=supplier_cost_eur,
            customs_duty_amount=customs_duty_amount,
            customs_duty_notice=customs_duty_notice(customs_duty_amount, eur_rate),
            eur_rate=eur_rate,
            requires_availability_confirmation=bool(low_stock_items),
            availability_message_ru=(
                self.AVAILABILITY_PENDING_MESSAGE if low_stock_items else None
            ),
        )

    # Возвращает последние заказы пользователя с позициями.
    async def list_orders(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 10,
    ) -> list[OrderSchema]:
        now = utc_now_naive()
        offset = (page - 1) * page_size
        orders = await self.order_crud.list_by_user_for_storefront(
            user_id=user_id, now=now, limit=page_size, offset=offset
        )
        attempt_map = await self.order_crud.get_latest_payment_attempts_for_orders(
            [order.id for order in orders]
        )
        order_ids = [order.id for order in orders]
        attempts_map = await self.order_crud.count_payment_attempts_for_orders(
            order_ids
        )
        shipment_rows = await self.order_crud.list_shipments_for_order_ids(order_ids)
        so_ids = [
            int(row.supplier_order_id)
            for row in shipment_rows
            if row.supplier_order_id is not None
        ]
        line_rows = await self.order_crud.list_supplier_order_lines_for_ids(so_ids)
        lines_by_so_id = group_lines_by_supplier_order_id(line_rows)
        shipments_by_order_id = group_shipments_by_order_id(shipment_rows)
        result: list[OrderSchema] = []
        for order in orders:
            items = await self._build_order_items(order.id)
            result.append(
                self._build_order_schema(
                    order,
                    items,
                    latest_attempt=attempt_map.get(order.id),
                    payment_attempts_used=attempts_map.get(order.id, 0),
                    shipments=build_order_shipment_schemas(
                        shipments_by_order_id.get(order.id, []),
                        lines_by_so_id,
                        items,
                    ),
                )
            )
        return result

    # Количество заказов пользователя в ЛК.
    async def count_user_orders(self, user_id: int) -> int:
        return await self.order_crud.count_by_user_for_storefront(
            user_id, utc_now_naive()
        )

    # Количество всех заказов для набора клиентов админки.
    async def count_orders_by_user_ids(self, user_ids: list[int]) -> dict[int, int]:
        return await self.order_crud.count_by_user_ids(user_ids)

    # Автоотмена просроченных неоплаченных заказов (batch для job).
    async def expire_unpaid_orders(self, limit: int = 50) -> dict[str, int]:
        now = utc_now_naive()
        candidates = await self.order_crud.find_orders_for_payment_expiration(
            now, limit=limit
        )
        cancelled = 0
        skipped = 0
        for order in candidates:
            result = await self.expire_unpaid_order(order.id, now=now)
            if result == "cancelled":
                cancelled += 1
            elif result == "skipped":
                skipped += 1
        return {
            "candidates": len(candidates),
            "cancelled": cancelled,
            "skipped": skipped,
        }

    # Автоотмена одного просроченного неоплаченного заказа (идемпотентно).
    async def expire_unpaid_order(
        self,
        order_id: int,
        now: datetime | None = None,
    ) -> str:
        check_at = now or utc_now_naive()
        order = await self.order_crud.get_by_id_for_update(order_id)
        if not order:
            return "skipped"
        if order.payment_paid_at is not None:
            return "skipped"
        if str(order.status or "").lower() not in ACTIVE_UNPAID_ORDER_STATUSES:
            return "skipped"
        if order.payment_due_at is None:
            return "skipped"
        if check_at < order.payment_due_at:
            return "skipped"

        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        if attempt_payment_resumable(latest, check_at):
            return "skipped"

        await self._apply_order_cancellation(
            order,
            cancellation_reason=CANCELLATION_REASON_PAYMENT_TIMEOUT,
            event_type=ORDER_EVENT_AUTO_CANCELLED_PAYMENT_TIMEOUT,
            event_message="Заказ автоматически отменён: срок оплаты истёк",
            created_by="system",
        )
        return "cancelled"

    # Отменяет неоплаченный заказ по запросу клиента из ЛК.
    async def cancel_order_by_customer(
        self,
        order_id: int,
        user_id: int,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id_for_update(order_id)
        if not order or order.user_id != user_id:
            raise ValueError("Заказ не найден")
        if str(order.status or "").lower() == OrderStatus.CANCELLED:
            raise ValueError("Заказ уже отменён")
        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        allowed, blocked_reason = self.evaluate_customer_cancel_allowed(
            order,
            latest_attempt=latest,
        )
        if not allowed:
            if blocked_reason:
                raise ValueError(blocked_reason)
            raise ValueError("Этот заказ нельзя отменить")
        await self._apply_order_cancellation(
            order,
            cancellation_reason=CANCELLATION_REASON_CUSTOMER_REQUEST,
            event_type=ORDER_EVENT_CANCELLED_BY_CUSTOMER,
            event_message="Заказ отменён клиентом",
            created_by=f"user:{user_id}",
        )
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return self._build_order_schema(
            order,
            items,
            user=user,
            latest_attempt=latest,
            payment_attempts_used=await self.order_crud.count_payment_attempts(
                order_id
            ),
        )

    # Общая финализация отмены заказа: статус, событие, остатки.
    async def _apply_order_cancellation(
        self,
        order: Order,
        cancellation_reason: str,
        event_type: str,
        event_message: str,
        created_by: str,
    ) -> None:
        if (
            str(order.availability_confirmation_status or "").lower()
            == AvailabilityConfirmationStatus.PENDING
        ):
            order.availability_confirmation_status = (
                AvailabilityConfirmationStatus.NOT_REQUIRED
            )
        order.status = OrderStatus.CANCELLED
        order.cancellation_reason = cancellation_reason
        await self.order_crud.create_order_event(
            order_id=order.id,
            event_type=event_type,
            event_message=event_message,
            created_by=created_by,
        )
        stock_result = await CatalogStockService(self.session).refresh_for_order(
            order.id
        )
        await self.order_crud.commit_order(order)
        await self.session.commit()
        invalidate_if_catalog_boundary_changed(
            stock_result.boundary_flipped_ids,
            reason="order_stock_boundary",
        )

    # Количество выполненных заказов пользователя.
    async def count_completed_user_orders(self, user_id: int) -> int:
        return await self.order_crud.count_by_user_status(
            user_id,
            OrderStatus.COMPLETED.value,
        )

    # Удаляет незавершённые заказы пользователя (все, кроме completed).
    async def delete_non_completed_orders_for_user(self, user_id: int) -> int:
        product_ids = (
            await (
                self.order_crud.list_product_ids_for_user_non_completed_orders(user_id)
            )
        )
        deleted = await self.order_crud.delete_non_completed_for_user(user_id)
        if deleted and product_ids:
            stock_result = await CatalogStockService(self.session).refresh_products(
                product_ids
            )
            await self.session.commit()
            invalidate_if_catalog_boundary_changed(
                stock_result.boundary_flipped_ids,
                reason="order_stock_boundary",
            )
        return deleted

    # Возвращает последние заказы всех пользователей с позициями.
    async def list_all_orders(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> list[OrderSchema]:
        listed = await self.list_admin_orders(
            page=page, page_size=page_size, status_filter=None
        )
        items = listed["items"]
        assert isinstance(items, list)
        return items

    # Список заказов для админки с фильтром и total.
    async def list_admin_orders(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: str | None = None,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
        queue: str | None = None,
    ) -> dict[str, object]:
        normalized_statuses = normalize_admin_order_status_filter(status_filter)
        normalized_q = q.strip() if q else None
        normalized_queue = queue.strip().lower() if queue else None
        offset = (page - 1) * page_size
        total = await self.order_crud.count_all(
            status=normalized_statuses,
            q=normalized_q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
            queue=normalized_queue,
        )
        orders = await self.order_crud.list_all(
            limit=page_size,
            offset=offset,
            status=normalized_statuses,
            q=normalized_q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
            queue=normalized_queue,
        )
        attempt_map = await self.order_crud.get_latest_payment_attempts_for_orders(
            [order.id for order in orders]
        )
        attempts_map = await self.order_crud.count_payment_attempts_for_orders(
            [order.id for order in orders]
        )
        result: list[OrderSchema] = []
        for order in orders:
            items = await self._build_order_items(order.id)
            user = await self.session.get(User, order.user_id)
            result.append(
                await self._build_order_schema_with_user(
                    order,
                    items,
                    user,
                    latest_attempt=attempt_map.get(order.id),
                    payment_attempts_used=attempts_map.get(order.id, 0),
                )
            )
        return {
            "items": result,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # Счётчики очередей действий для карточек админки.
    async def get_admin_orders_queues(self) -> dict[str, int]:
        return await self.order_crud.admin_orders_queues()

    # Счётчики заказов по status для pill-фильтров админки (один GROUP BY).
    async def get_admin_orders_status_counts(
        self,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
    ) -> dict[str, int]:
        normalized_q = q.strip() if q else None
        grouped = await self.order_crud.count_grouped_by_status(
            q=normalized_q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
        )
        counts: dict[str, int] = {
            status.value: grouped.get(status.value, 0) for status in OrderStatus
        }
        counts[""] = sum(grouped.values())
        return counts

    # Безвозвратно удаляет выбранные заказы.
    async def admin_delete_orders_by_ids(self, order_ids: list[int]) -> int:
        unique_ids = sorted(
            {int(order_id) for order_id in order_ids if int(order_id) > 0}
        )
        if not unique_ids:
            raise ValueError("Не выбраны заказы")
        return await self.order_crud.delete_orders_by_ids(unique_ids)

    # Формирует строку с информацией о пользователе, который совершил действие.
    async def _build_admin_created_by(
        self, payload_created_by: str | None, actor: User | None
    ) -> str:
        if actor is not None:
            identity_svc = IdentityService(self.session)
            telegram_id = await identity_svc.get_telegram_id_for_user(actor)
            telegram_username = await identity_svc.get_telegram_username_for_user(actor)
            parts: list[str] = []
            if actor.name:
                parts.append(actor.name)
            if telegram_username:
                parts.append(f"@{telegram_username}")
            if telegram_id:
                parts.append(f"tg:{telegram_id}")
            if parts:
                return " · ".join(parts)
            return f"user:{actor.id}"
        return payload_created_by or "system"

    # Read-only: позиции заказа с product/variant полями для UI и уведомлений.
    async def list_order_items_enriched(self, order_id: int):
        return await self._build_order_items(order_id)

    # Собирает позиции заказа с данными товара для UI.
    async def _build_order_items(self, order_id: int):
        items = await self.order_crud.get_order_items(order_id)
        products = await self.product_crud.get_by_ids(
            [item.product_id for item in items]
        )
        products_map = {product.id: product for product in products}
        variant_ids = [item.variant_id for item in items if item.variant_id is not None]
        variants_map = await self._get_variants_by_ids(variant_ids)
        for item in items:
            product = products_map.get(item.product_id)
            variant = (
                variants_map.get(item.variant_id)
                if item.variant_id is not None
                else None
            )
            setattr(
                item,
                "product_title",
                item.product_title_captured or (product.title if product else None),
            )
            setattr(item, "product_image_url", product.image_url if product else None)
            setattr(
                item,
                "product_url",
                (
                    str(product.product_url).strip()
                    if product is not None and product.product_url
                    else None
                ),
            )
            setattr(
                item,
                "variant_sku",
                item.variant_sku_captured or (variant.sku if variant else None),
            )
            setattr(
                item,
                "variant_option1",
                item.variant_option1_captured or (variant.option1 if variant else None),
            )
            setattr(
                item,
                "variant_option2",
                item.variant_option2_captured or (variant.option2 if variant else None),
            )
            setattr(
                item,
                "variant_option3",
                item.variant_option3_captured or (variant.option3 if variant else None),
            )
            setattr(
                item,
                "product_external_id",
                item.product_external_id_captured
                or (product.external_id if product else None),
            )
            setattr(
                item,
                "variant_external_id",
                item.variant_external_id_captured
                or (variant.variant_external_id if variant else None),
            )
            setattr(item, "category_l2", item.category_l2_captured)
            setattr(item, "category_l3", item.category_l3_captured)
        return items

    # English L2/L3 snapshot с Product на момент создания позиции.
    @staticmethod
    def _product_category_snapshot(
        product: Product | None,
    ) -> tuple[str | None, str | None]:
        if product is None:
            return None, None
        l2 = str(product.category_l2 or "").strip() or None
        l3 = str(product.category_l3 or "").strip() or None
        return l2, l3

    # Формирует payload позиции заказа с зафиксированными данными для интеграций.
    def _build_order_item_payload(
        self,
        cart_item: CartItem,
        unit_price: Decimal,
        product: Product | None,
        variant: ProductVariant | None,
    ) -> dict[str, int | Decimal | str | None]:
        category_l2, category_l3 = self._product_category_snapshot(product)
        return {
            "product_id": cart_item.product_id,
            "variant_id": cart_item.variant_id,
            "quantity": cart_item.quantity,
            "unit_price": unit_price,
            "product_title_captured": product.title if product else None,
            "product_external_id_captured": product.external_id if product else None,
            "variant_external_id_captured": (
                variant.variant_external_id if variant else None
            ),
            "variant_sku_captured": variant.sku if variant else None,
            "variant_option1_captured": variant.option1 if variant else None,
            "variant_option2_captured": variant.option2 if variant else None,
            "variant_option3_captured": variant.option3 if variant else None,
            "supplier_price_eur_captured": (
                Decimal(str(product.supplier_price_eur or 0))
                if product
                else Decimal("0")
            ),
            "category_l2_captured": category_l2,
            "category_l3_captured": category_l3,
        }

    # Нормализует исторический snapshot цены, если значение сохранено в "центах".
    @classmethod
    def _normalize_price_snapshot(
        cls, value: Decimal, reference_price: Decimal | None = None
    ) -> Decimal:
        normalized = (
            value / Decimal("100") if value >= cls.LEGACY_CENTS_THRESHOLD else value
        )
        if reference_price is None:
            return normalized
        normalized_reference = (
            reference_price / Decimal("100")
            if reference_price >= cls.LEGACY_CENTS_THRESHOLD
            else reference_price
        )
        maybe_scaled = normalized * Decimal("100")
        if (
            normalized > 0
            and normalized < Decimal("1000")
            and normalized_reference >= Decimal("1000")
            and abs(maybe_scaled - normalized_reference) <= Decimal("1")
        ):
            return maybe_scaled
        return normalized

    # Загружает варианты для позиций корзины.
    async def _get_variants_map(
        self, cart_items: list[CartItem]
    ) -> dict[int, ProductVariant]:
        variant_ids = [
            item.variant_id for item in cart_items if item.variant_id is not None
        ]
        return await self._get_variants_by_ids(variant_ids)

    # Загружает товары и варианты для расчета checkout.
    async def _load_checkout_products_context(
        self, cart_items: list[CartItem]
    ) -> tuple[dict[int, Product], dict[int, ProductVariant]]:
        product_ids = list({item.product_id for item in cart_items})
        products_map: dict[int, Product] = {}
        for product_id in product_ids:
            product = await self.product_crud.get_by_id_with_related(product_id)
            if product is not None:
                products_map[product_id] = product
        variant_ids: list[int] = []
        for item in cart_items:
            product = products_map.get(item.product_id)
            if product is None:
                continue
            resolved = resolve_cart_variant_id(product, item.variant_id)
            if resolved is not None:
                variant_ids.append(resolved)
        variant_map = await self._get_variants_by_ids(variant_ids)
        return products_map, variant_map

    # Считает сумму товаров в корзине для checkout.
    def _calculate_items_subtotal(
        self,
        cart_items: list[CartItem],
        products_map: dict[int, Product],
        variant_map: dict[int, ProductVariant],
    ) -> Decimal:
        items_subtotal = Decimal("0")
        for item in cart_items:
            product = products_map.get(item.product_id)
            normalized_unit_price = self._normalize_price_snapshot(
                value=(
                    Decimal(product.sale_price)
                    if product is not None
                    else Decimal(item.price_snapshot)
                ),
            )
            items_subtotal += normalized_unit_price * item.quantity
        return items_subtotal

    # Загружает варианты по списку идентификаторов.
    async def _get_variants_by_ids(
        self, variant_ids: list[int]
    ) -> dict[int, ProductVariant]:
        if not variant_ids:
            return {}
        result = await self.session.scalars(
            select(ProductVariant).where(ProductVariant.id.in_(variant_ids))
        )
        variants = list(result.all())
        return {variant.id: variant for variant in variants}

    # Собирает API-схему заказа из ORM-модели.
    async def _telegram_fields_for_user(
        self,
        user: User | None,
    ) -> tuple[int | None, str | None]:
        if user is None:
            return None, None
        identity_svc = IdentityService(self.session)
        return (
            await identity_svc.get_telegram_id_for_user(user),
            await identity_svc.get_telegram_username_for_user(user),
        )

    async def _user_phone_for_user(self, user: User | None) -> str | None:
        if user is None:
            return None
        phone = await IdentityService(self.session).get_phone_e164_for_user(user)
        if phone:
            return phone
        profile = await DeliveryProfileService(self.session).get_profile(user.id)
        if profile is None:
            return None
        profile_phone = str(profile.phone or "").strip()
        return profile_phone or None

    # Собирает OrderSchema с telegram-полями из identities.
    async def _build_order_schema_with_user(
        self,
        order: Order,
        items: list,
        user: User | None,
        latest_attempt=None,
        payment_attempts_used: int | None = None,
    ) -> OrderSchema:
        telegram_id, telegram_username = await self._telegram_fields_for_user(user)
        user_phone = await self._user_phone_for_user(user)
        if payment_attempts_used is None:
            payment_attempts_used = await self.order_crud.count_payment_attempts(
                order.id
            )
        # После commit ORM-поля могут быть expired. Все async lookup завершены;
        # обновляем заказ прямо перед синхронной сборкой OrderSchema.
        await self.session.refresh(order)
        return self._build_order_schema(
            order,
            items,
            user=user,
            user_telegram_id=telegram_id,
            user_telegram_username=telegram_username,
            user_phone=user_phone,
            latest_attempt=latest_attempt,
            payment_attempts_used=payment_attempts_used,
        )

    async def _build_order_schema_async(
        self,
        order: Order,
        items: list,
        user: User | None = None,
        user_telegram_id: int | None = None,
        user_telegram_username: str | None = None,
        user_phone: str | None = None,
        latest_attempt=None,
        payment_attempts_used: int | None = None,
    ) -> OrderSchema:
        if payment_attempts_used is None:
            payment_attempts_used = await self.order_crud.count_payment_attempts(
                order.id
            )
        if user is None:
            user = await self.session.get(User, order.user_id)
        if user_telegram_id is None and user_telegram_username is None:
            (
                user_telegram_id,
                user_telegram_username,
            ) = await self._telegram_fields_for_user(user)
        if user_phone is None:
            user_phone = await self._user_phone_for_user(user)
        return self._build_order_schema(
            order,
            items,
            user=user,
            user_telegram_id=user_telegram_id,
            user_telegram_username=user_telegram_username,
            user_phone=user_phone,
            latest_attempt=latest_attempt,
            payment_attempts_used=payment_attempts_used,
        )

    def _build_order_schema(
        self,
        order: Order,
        items: list,
        user: User | None = None,
        user_telegram_id: int | None = None,
        user_telegram_username: str | None = None,
        user_phone: str | None = None,
        latest_attempt=None,
        payment_attempts_used: int = 0,
        shipments: list[OrderShipmentSchema] | None = None,
    ) -> OrderSchema:
        status_label = self.resolve_customer_status_label(order)
        availability_status = str(
            order.availability_confirmation_status
            or AvailabilityConfirmationStatus.NOT_REQUIRED
        ).lower()
        availability_label = self.AVAILABILITY_STATUS_LABELS.get(
            availability_status,
            availability_status,
        )
        payment_meta = order.payment_meta_json or {}
        if latest_attempt is not None:
            payment_display = normalize_order_payment_from_attempt(
                payment_paid_at=order.payment_paid_at,
                latest_attempt=latest_attempt,
                payment_provider=order.payment_provider,
            )
        else:
            payment_display = normalize_order_payment(
                payment_paid_at=order.payment_paid_at,
                payment_status=order.payment_status,
                payment_qr_id=order.payment_qr_id,
                payment_qr_payload=order.payment_qr_payload,
                payment_provider=order.payment_provider,
                payment_order_id=order.payment_order_id,
                payment_init_state=payment_meta.get("init_state"),
            )
        payment_paid_at_short_display = (
            format_datetime_msk_short(order.payment_paid_at)
            if payment_display.payment_state == "paid"
            else None
        )
        attempts_limit = settings.ORDER_MAX_PAYMENT_ATTEMPTS
        attempts_remaining = max(0, attempts_limit - payment_attempts_used)
        attempts_exhausted_flag = payment_attempts_exhausted(
            payment_attempts_used,
            attempts_limit,
            latest_attempt,
        )
        if order.payment_paid_at is not None:
            attempts_exhausted_flag = False
        if attempts_exhausted_flag:
            attempts_remaining = 0
        late_payment_after_auto_cancel = (
            order.payment_paid_at is not None
            and str(order.status or "").lower() == OrderStatus.CANCELLED
        )
        payment_state = payment_display.payment_state
        payment_label = payment_display.payment_label
        if late_payment_after_auto_cancel:
            payment_state = "late_paid_after_cancel"
            payment_label = PAYMENT_STATE_LABELS["paid"]
        elif attempts_exhausted_flag and order.payment_paid_at is None:
            payment_state = "exhausted"
            payment_label = PAYMENT_EXHAUSTED_LABEL
        elif availability_status == AvailabilityConfirmationStatus.PENDING:
            payment_label = self.AVAILABILITY_STATUS_LABELS[
                AvailabilityConfirmationStatus.PENDING
            ]
        payment_allowed = (
            self.compute_payment_allowed(order, latest_attempt=latest_attempt)
            and not attempts_exhausted_flag
            and not late_payment_after_auto_cancel
        )
        customer_cancel_allowed, customer_cancel_blocked_reason = (
            self.evaluate_customer_cancel_allowed(order, latest_attempt=latest_attempt)
        )
        return OrderSchema(
            id=order.id,
            user_id=order.user_id,
            status=order.status,
            status_label=status_label,
            availability_confirmation_status=availability_status,
            availability_confirmation_status_label=availability_label,
            availability_message_ru=self.availability_message_for_status(
                availability_status
            ),
            payment_allowed=payment_allowed,
            payment_gateway_enabled=settings.SBP_ENABLED,
            customer_cancel_allowed=customer_cancel_allowed,
            customer_cancel_blocked_reason=customer_cancel_blocked_reason,
            payment_due_at=order.payment_due_at,
            payment_due_at_display=(
                format_datetime_msk(order.payment_due_at)
                if order.payment_due_at is not None
                else None
            ),
            cancellation_reason=order.cancellation_reason,
            payment_attempts_used=payment_attempts_used,
            payment_attempts_limit=attempts_limit,
            payment_attempts_remaining=attempts_remaining,
            payment_attempts_exhausted=attempts_exhausted_flag,
            late_payment_after_auto_cancel=late_payment_after_auto_cancel,
            total_amount=order.total_amount,
            items_subtotal_amount=order.items_subtotal_amount,
            discount_items_amount=order.discount_items_amount,
            delivery_fee_amount=order.delivery_fee_amount,
            eur_rate_snapshot=order.eur_rate_snapshot,
            promo_code_applied=order.promo_code_applied,
            last_name=order.last_name,
            first_name=order.first_name,
            street=order.street,
            house=order.house,
            apartment=order.apartment,
            city=order.city,
            postal_code=order.postal_code,
            phone=order.phone,
            notification_channels=list(order.notification_channels or []),
            notification_email=order.notification_email,
            payment_provider=order.payment_provider,
            payment_order_id=order.payment_order_id,
            payment_status=order.payment_status,
            payment_paid_at=order.payment_paid_at,
            payment_state=payment_state,
            payment_label=payment_label,
            payment_method_label=payment_display.payment_method_label,
            payment_paid_at_short_display=payment_paid_at_short_display,
            user_name=user.name if user else None,
            user_email=user.email if user else None,
            user_phone=user_phone,
            user_telegram_id=user_telegram_id,
            user_telegram_username=user_telegram_username,
            created_at=order.created_at,
            updated_at=order.updated_at,
            supplier_order_id=order.supplier_order_id,
            supplier_tracking_id=order.supplier_tracking_id,
            failed_from_status=order.failed_from_status,
            items=items,
            shipments=list(shipments or []),
        )

    # Возвращает заказ по id для административной страницы.
    async def get_order(self, order_id: int) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        latest_attempt = await self.order_crud.get_latest_payment_attempt(order_id)
        return await self._build_order_schema_async(
            order, items, user, latest_attempt=latest_attempt
        )

    # Возвращает платёжные попытки заказа для админки.
    async def list_payment_attempts(self, order_id: int) -> list:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        return await self.order_crud.list_payment_attempts_for_order(order_id)

    # Возвращает события истории заказа.
    async def get_order_events(self, order_id: int) -> list[OrderEventSchema]:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        events = await self.order_crud.get_order_events(order_id)
        return [self._build_order_event_schema(event) for event in events]

    # Проверяет, что выбранные каналы заказа доступны перед notify.
    async def _ensure_customer_notify(self, order: Order) -> None:
        channels = set(order.notification_channels or [])
        if not channels:
            channels = {"telegram"}
        if "telegram" in channels:
            if not settings.TG_BOT_SHOP:
                raise ValueError("Telegram-бот не настроен")
            user = await self.session.get(User, order.user_id)
            telegram_id = await IdentityService(self.session).get_telegram_id_for_user(
                user
            )
            if not user or telegram_id is None:
                raise ValueError("У клиента нет Telegram — уведомление не отправлено")
        if "email" in channels and not order.notification_email:
            raise ValueError("У заказа нет подтверждённого email")

    # Подтверждает наличие товара админом для заказа с пограничным остатком.
    async def confirm_availability(
        self,
        order_id: int,
        payload: AdminAvailabilityConfirmationUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        current = str(order.availability_confirmation_status or "").lower()
        if current == AvailabilityConfirmationStatus.CONFIRMED:
            items = await self._build_order_items(order_id)
            user = await self.session.get(User, order.user_id)
            return await self._build_order_schema_with_user(order, items, user)
        if current != AvailabilityConfirmationStatus.PENDING:
            raise ValueError("Подтверждение наличия не требуется")
        if payload.notify_customer:
            await self._ensure_customer_notify(order)

        locked = await self.order_crud.get_by_id_for_update(order_id)
        if not locked:
            raise ValueError("Заказ не найден")
        current = str(locked.availability_confirmation_status or "").lower()
        if current == AvailabilityConfirmationStatus.CONFIRMED:
            items = await self._build_order_items(order_id)
            user = await self.session.get(User, locked.user_id)
            await self.session.commit()
            return await self._build_order_schema_with_user(locked, items, user)
        if current != AvailabilityConfirmationStatus.PENDING:
            raise ValueError("Подтверждение наличия не требуется")
        items_for_snapshot = await self.order_crud.get_order_items(order_id)
        validate_supplier_snapshot_for_admin_action(locked, items_for_snapshot)
        previous = locked.availability_confirmation_status
        locked.availability_confirmation_status = (
            AvailabilityConfirmationStatus.CONFIRMED
        )
        locked.payment_due_at = self.payment_deadline_from_now()
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="availability_confirmed",
            event_message=payload.event_message or "Наличие подтверждено",
            created_by=created_by,
            payload_json={
                "before": previous,
                "after": locked.availability_confirmation_status,
            },
        )
        await self._sync_order_status_from_availability(locked, created_by=created_by)
        await self.order_crud.commit_order(locked)
        await self.session.commit()
        if payload.notify_customer:
            notify_user = await self.session.get(User, order.user_id)
            success = await CustomerNotificationService(
                self.session
            ).notify_order_status(
                order_id=order_id,
                custom_message=format_customer_availability_confirmed_message(
                    order_id,
                    customer_name=notify_user.name if notify_user else None,
                    fmt="plain",
                ),
                created_by=created_by,
                idempotency_key=availability_notify_key(order_id),
            )
            if not success:
                raise ValueError("Не удалось отправить сообщение в Telegram")
            await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Отклоняет наличие товара админом для заказа с пограничным остатком.
    async def mark_availability_unavailable(
        self,
        order_id: int,
        payload: AdminAvailabilityConfirmationUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        current = str(order.availability_confirmation_status or "").lower()
        if current == AvailabilityConfirmationStatus.UNAVAILABLE:
            items = await self._build_order_items(order_id)
            user = await self.session.get(User, order.user_id)
            return await self._build_order_schema_with_user(order, items, user)
        if current != AvailabilityConfirmationStatus.PENDING:
            raise ValueError("Подтверждение наличия не требуется")
        if payload.notify_customer:
            await self._ensure_customer_notify(order)

        locked = await self.order_crud.get_by_id_for_update(order_id)
        if not locked:
            raise ValueError("Заказ не найден")
        current = str(locked.availability_confirmation_status or "").lower()
        if current == AvailabilityConfirmationStatus.UNAVAILABLE:
            items = await self._build_order_items(order_id)
            user = await self.session.get(User, locked.user_id)
            await self.session.commit()
            return await self._build_order_schema_with_user(locked, items, user)
        if current != AvailabilityConfirmationStatus.PENDING:
            raise ValueError("Подтверждение наличия не требуется")
        items_for_snapshot = await self.order_crud.get_order_items(order_id)
        validate_supplier_snapshot_for_admin_action(locked, items_for_snapshot)
        previous = locked.availability_confirmation_status
        locked.availability_confirmation_status = (
            AvailabilityConfirmationStatus.UNAVAILABLE
        )
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="availability_rejected",
            event_message=payload.event_message or "Товар недоступен",
            created_by=created_by,
            payload_json={
                "before": previous,
                "after": locked.availability_confirmation_status,
            },
        )
        await self._sync_order_status_from_availability(locked, created_by=created_by)
        await self.order_crud.commit_order(locked)
        await self.session.commit()
        if payload.notify_customer:
            notify_user = await self.session.get(User, order.user_id)
            success = await CustomerNotificationService(
                self.session
            ).notify_order_status(
                order_id=order_id,
                custom_message=format_customer_availability_unavailable_message(
                    order_id,
                    customer_name=notify_user.name if notify_user else None,
                    fmt="plain",
                ),
                created_by=created_by,
                idempotency_key=availability_notify_key(order_id),
            )
            if not success:
                raise ValueError("Не удалось отправить сообщение в Telegram")
            await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Передаёт оплаченный заказ в сборку у поставщика.
    async def start_order_assembling(
        self,
        order_id: int,
        payload: AdminStartAssemblingUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id_for_update(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        if not self.can_start_assembling(order, supplier_orders=headers):
            raise ValueError("Заказ нельзя передать в сборку")
        supplier_order_id = payload.supplier_order_id.strip()
        if not supplier_order_id:
            raise ValueError("Укажите номер заказа у поставщика")
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self._apply_assembling_transition(
            order,
            supplier_order_id,
            created_by=created_by,
            event_message=payload.event_message,
            supplier_delivery_json=payload.supplier_delivery_json,
        )
        await self.order_crud.commit_order(order)
        await self.session.commit()
        if payload.notify_customer:
            await CustomerNotificationService(self.session).notify_order_status(
                order_id=order_id,
                custom_message=payload.custom_message,
                created_by=created_by,
                idempotency_key=assembly_notify_key(order_id),
            )
            await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Передаёт собранный заказ в доставку после получения трек-номера.
    async def start_order_delivery(
        self,
        order_id: int,
        payload: AdminStartDeliveryUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id_for_update(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        if str(order.status or "").lower() != OrderStatus.ASSEMBLING:
            raise ValueError("В доставку можно передать только заказ в сборке")
        tracking_id = payload.supplier_tracking_id.strip()
        if not tracking_id:
            raise ValueError("Укажите трек-номер поставщика")
        order.supplier_tracking_id = tracking_id
        order.status = OrderStatus.DELIVERY
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="delivery_started",
            event_message=payload.event_message or "Заказ передан в доставку",
            created_by=created_by,
            payload_json={
                "before": OrderStatus.ASSEMBLING,
                "after": OrderStatus.DELIVERY,
                "supplier_tracking_id": tracking_id,
            },
        )
        await self.order_crud.commit_order(order)
        await self.session.commit()
        if payload.notify_customer:
            await CustomerNotificationService(self.session).notify_order_status(
                order_id=order_id,
                custom_message=payload.custom_message,
                created_by=created_by,
            )
        await AdminNotificationService(self.session).send_order_delivery_started(
            order_id
        )
        await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Добавляет внутренний комментарий в историю заказа без смены статуса.
    async def add_admin_order_comment(
        self,
        order_id: int,
        message: str,
        actor: User | None = None,
    ) -> None:
        text = message.strip()
        if not text:
            raise ValueError("Введите комментарий")
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        created_by = await self._build_admin_created_by(None, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="admin_comment",
            event_message=text,
            created_by=created_by,
            payload_json={"status": str(order.status or "").lower()},
        )
        await self.session.commit()

    # Единственный переход delivery → completed (stock, referral, outbox).
    # Сейчас вызывает admin; будущий auto-complete — этот же метод.
    async def finalize_order_delivery(
        self,
        order_id: int,
        event_message: str | None,
        created_by: str,
        notify_customer: bool,
        custom_message: str | None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id_for_update(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        user_id = order.user_id
        current_status = str(order.status or "").lower()
        if current_status == OrderStatus.COMPLETED:
            if notify_customer:
                raise ValueError(
                    "Заказ уже выполнен — уведомление клиенту через смену статуса "
                    "недоступно"
                )
            return await self._build_order_schema_for_user(order_id, user_id)
        if current_status != OrderStatus.DELIVERY:
            raise ValueError("Завершить можно только заказ в доставке")

        order.status = OrderStatus.COMPLETED
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="delivered_to_customer",
            event_message=event_message or "Заказ выполнен",
            created_by=created_by,
            payload_json={
                "before": OrderStatus.DELIVERY,
                "after": OrderStatus.COMPLETED,
            },
        )
        stock_result = await CatalogStockService(self.session).refresh_for_order(
            order_id
        )
        await ReferralService(self.session).accrue_for_order(order)
        if notify_customer:
            await CustomerNotificationService(self.session).notify_order_status(
                order_id=order_id,
                custom_message=custom_message,
                created_by=created_by,
                idempotency_key=ORDER_FINALIZE_CUSTOMER_NOTIFY_KEY.format(
                    order_id=order_id
                ),
            )
        await self.session.commit()
        invalidate_if_catalog_boundary_changed(
            stock_result.boundary_flipped_ids,
            reason="order_stock_boundary",
        )
        await sync_order_completed_admin_alert(
            order_id,
            utc_now_naive(),
        )
        return await self._build_order_schema_for_user(order_id, user_id)

    # Собирает OrderSchema после commit — без доступа к протухшему ORM order.
    async def _build_order_schema_for_user(
        self,
        order_id: int,
        user_id: int,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Обновляет статус заказа админом.
    async def update_order_status(
        self,
        order_id: int,
        payload: AdminOrderStatusUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        next_status = str(payload.status).strip().lower()
        if next_status not in {status.value for status in OrderStatus}:
            raise ValueError("Недопустимый статус заказа")
        if next_status == OrderStatus.COMPLETED:
            current_status = str(order.status or "").lower()
            if current_status == OrderStatus.COMPLETED:
                _reject_repeat_status_customer_notify(
                    current_status,
                    notify_customer=payload.notify_customer,
                )
            created_by = await self._build_admin_created_by(payload.created_by, actor)
            return await self.finalize_order_delivery(
                order_id=order_id,
                event_message=payload.event_message,
                created_by=created_by,
                notify_customer=payload.notify_customer,
                custom_message=payload.custom_message,
            )
        current_status = str(order.status or "").lower()
        allowed = self.allowed_next_statuses_for_order(order)
        if next_status != current_status and next_status not in allowed:
            raise ValueError("Недопустимый переход статуса")
        previous_status = current_status
        if previous_status == next_status:
            comment = (payload.event_message or "").strip()
            _reject_repeat_status_customer_notify(
                previous_status,
                notify_customer=payload.notify_customer,
            )
            if not comment and not payload.notify_customer:
                items = await self._build_order_items(order_id)
                user = await self.session.get(User, order.user_id)
                return await self._build_order_schema_with_user(order, items, user)

            if comment:
                await self.add_admin_order_comment(
                    order_id,
                    comment,
                    actor=actor,
                )
            if payload.notify_customer:
                created_by = await self._build_admin_created_by(
                    payload.created_by, actor
                )
                await CustomerNotificationService(self.session).notify_order_status(
                    order_id=order_id,
                    custom_message=payload.custom_message,
                    created_by=created_by,
                )
                await self._commit_enqueued_notifications()
            items = await self._build_order_items(order_id)
            user = await self.session.get(User, order.user_id)
            return await self._build_order_schema_with_user(order, items, user)

        availability_before: str | None = None
        availability_after: str | None = None
        if (
            next_status == OrderStatus.CANCELLED
            and str(order.availability_confirmation_status or "").lower()
            == AvailabilityConfirmationStatus.PENDING
        ):
            availability_before = order.availability_confirmation_status
            order.availability_confirmation_status = (
                AvailabilityConfirmationStatus.NOT_REQUIRED
            )
            availability_after = order.availability_confirmation_status

        if next_status == OrderStatus.FAILED:
            order.failed_from_status = previous_status
        elif previous_status == OrderStatus.FAILED:
            order.failed_from_status = None

        # Обновляем статус заказа.
        order.status = next_status
        event_type = "status_changed"
        if next_status == OrderStatus.DELIVERY:
            event_type = "delivery_started"
        elif next_status == OrderStatus.CANCELLED:
            event_type = "order_cancelled"
        elif next_status == OrderStatus.FAILED:
            event_type = "order_failed"
        # Создаем событие истории заказа.
        event_payload: dict[str, object] = {
            "before": previous_status,
            "after": next_status,
        }
        if availability_before is not None and availability_after is not None:
            event_payload["availability_before"] = availability_before
            event_payload["availability_after"] = availability_after
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type=event_type,
            event_message=payload.event_message or f"Статус изменен на {next_status}",
            created_by=created_by,
            payload_json=event_payload,
        )
        await self.order_crud.commit_order(order)
        stock_result = await CatalogStockService(self.session).refresh_for_order(
            order_id
        )
        await self.session.commit()
        invalidate_if_catalog_boundary_changed(
            stock_result.boundary_flipped_ids,
            reason="order_stock_boundary",
        )
        if payload.notify_customer:
            await CustomerNotificationService(self.session).notify_order_status(
                order_id=order_id,
                custom_message=payload.custom_message,
                created_by=created_by,
            )
        if next_status == OrderStatus.FAILED:
            await AdminNotificationService(self.session).send_order_technical_problem(
                order_id
            )
        if payload.notify_customer or next_status == OrderStatus.FAILED:
            await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Отправляет произвольное сообщение клиенту в Telegram (без смены статуса).
    async def send_customer_telegram_message(
        self,
        order_id: int,
        message: str,
        actor: User | None = None,
    ) -> None:
        await self.send_customer_message(
            order_id=order_id,
            message=message,
            channel="telegram",
            actor=actor,
        )

    # Отправляет ручное сообщение клиенту в выбранные каналы.
    async def send_customer_message(
        self,
        order_id: int,
        message: str,
        channel: str,
        actor: User | None = None,
    ) -> None:
        text = message.strip()
        if not text:
            raise ValueError("Введите текст сообщения")
        if channel not in {"email", "telegram", "both"}:
            raise ValueError("Выберите канал отправки")
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        if str(order.status or "").lower() in _TERMINAL_CUSTOMER_MESSAGE_STATUSES:
            raise ValueError(
                "Заказ в финальном статусе — отправка сообщений недоступна"
            )
        user = await self.session.get(User, order.user_id)
        email = order.notification_email or (user.email if user is not None else None)
        if channel in {"email", "both"} and not email:
            raise ValueError("У заказа нет подтверждённого email")
        if channel in {"telegram", "both"}:
            telegram_id = await IdentityService(self.session).get_telegram_id_for_user(
                user
            )
            if telegram_id is None:
                raise ValueError("У заказа нет привязанного Telegram")
        created_by = await self._build_admin_created_by(None, actor)
        dispatcher = notification_dispatcher()
        channels = ["email", "telegram"] if channel == "both" else [channel]
        for selected in channels:
            dispatch = NotificationDispatch(
                channel=NotificationChannel.CUSTOMER,
                template="customer.manual",
                payload={
                    "order_id": order_id,
                    "message": text,
                    "force_channel": selected,
                },
                created_by=created_by,
                idempotency_key=f"admin:manual:{order_id}:{selected}:{uuid4().hex}",
                record_order_event=NotificationOrderEvent(
                    event_type=CUSTOMER_NOTIFIED_EVENT,
                    event_message="Ручное сообщение клиенту",
                    payload_json={"manual": True, "channel": selected},
                ),
            )
            if not await dispatcher.enqueue(self.session, dispatch):
                raise ValueError(f"Не удалось поставить сообщение в канал: {selected}")
        await self._commit_enqueued_notifications()

    # Customer B для выбранных Shipment. Не complete и не finalize.
    async def notify_shipments_delivered(
        self,
        order_id: int,
        shipment_ids: Sequence[int],
        custom_message: str | None,
        actor: User | None = None,
    ) -> int:
        unique_ids: list[int] = []
        seen: set[int] = set()
        for raw_id in shipment_ids:
            shipment_id = int(raw_id)
            if shipment_id in seen:
                continue
            seen.add(shipment_id)
            unique_ids.append(shipment_id)
        if not unique_ids:
            raise ValueError("Выберите посылку")
        rows = await self.order_crud.list_shipments_for_order(order_id)
        by_id = {int(row.id): row for row in rows}
        headers = await self.order_crud.list_placed_supplier_orders(order_id)
        seq_by_so = {
            int(header.id): int(getattr(header, "seq", 0) or 0) for header in headers
        }
        created_by = await self._build_admin_created_by(None, actor)
        notifier = CustomerNotificationService(self.session)
        queued = 0
        for index, shipment_id in enumerate(unique_ids, start=1):
            row = by_id.get(shipment_id)
            if row is None or int(row.order_id) != int(order_id):
                raise ValueError("Посылка не найдена")
            if not shipment_can_notify_customer(row):
                raise ValueError(
                    "Уведомить можно только доставленную или завершённую посылку"
                )
            so_id = (
                int(row.supplier_order_id) if row.supplier_order_id is not None else 0
            )
            seq = seq_by_so.get(so_id) or index
            cj = str(row.supplier_tracking_number or "").strip() or None
            text = render_shipment_customer_message(custom_message, order_id, seq, cj)
            if len(unique_ids) > 1:
                text = ensure_shipment_identity_in_message(
                    text, custom_message, seq, cj
                )
            ok = await notifier.notify_order_status(
                order_id=order_id,
                custom_message=text,
                created_by=created_by,
                idempotency_key=shipment_delivered_notify_key(order_id, shipment_id),
                order_status=SHIPMENT_CUSTOMER_NOTIFY_ORDER_STATUS,
            )
            if ok:
                queued += 1
        await self._commit_enqueued_notifications()
        return queued

    # Обновляет данные доставки заказа админом.
    async def update_order_delivery(
        self,
        order_id: int,
        payload: AdminOrderUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        patch_raw = payload.model_dump(exclude_unset=True)
        patch_payload = {
            key: value
            for key, value in patch_raw.items()
            if key
            in {
                "last_name",
                "first_name",
                "street",
                "house",
                "apartment",
                "city",
                "postal_code",
                "phone",
            }
        }
        if not patch_payload:
            items = await self._build_order_items(order_id)
            return self._build_order_schema(order, items)
        # Сохраняем предыдущие значения полей доставки.
        before = {field: getattr(order, field, None) for field in patch_payload}
        # Обновляем данные доставки заказа.
        await self.order_crud.update_order(order, patch_payload)
        # Создаем событие истории заказа.
        event_payload = {"before": before, "after": patch_payload}
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="delivery_address_edited",
            event_message=payload.event_message or "Адрес доставки обновлен",
            created_by=created_by,
            payload_json=event_payload,
        )
        await self.order_crud.commit_order(order)
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return await self._build_order_schema_with_user(order, items, user)

    # Ключ сопоставления low-stock позиции с order_item.
    @staticmethod
    def _availability_match_key(
        product_id: int, variant_id: int | None
    ) -> tuple[int, int | None]:
        return (int(product_id), int(variant_id) if variant_id is not None else None)

    # Сопоставляет order_item с low-stock из availability_confirmation_requested.
    async def _resolve_pending_availability_rows(
        self, order_id: int
    ) -> list[_PendingAvailabilityTarget]:
        events = await self.order_crud.get_order_events(order_id)
        pending_payload: list[dict[str, object]] = []
        for event in events:
            if event.event_type != "availability_confirmation_requested":
                continue
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            raw_items = payload.get("items")
            if isinstance(raw_items, list):
                pending_payload = [row for row in raw_items if isinstance(row, dict)]
            break
        if not pending_payload:
            return []
        order_items = await self._build_order_items(order_id)
        if not order_items:
            return []
        product_ids = list({item.product_id for item in order_items})
        products_map: dict[int, Product] = {}
        for product_id in product_ids:
            product = await self.product_crud.get_by_id_with_related(product_id)
            if product is not None:
                products_map[product.id] = product
        by_key: dict[tuple[int, int | None], list[OrderItem]] = {}
        for item in order_items:
            product = products_map.get(item.product_id)
            effective_variant_id = (
                resolve_cart_variant_id(product, item.variant_id)
                if product is not None
                else item.variant_id
            )
            key = self._availability_match_key(item.product_id, effective_variant_id)
            by_key.setdefault(key, []).append(item)
        rows: list[_PendingAvailabilityTarget] = []
        for pending in pending_payload:
            product_id_raw = pending.get("product_id")
            if not isinstance(product_id_raw, int):
                continue
            variant_id_raw = pending.get("variant_id")
            variant_id = variant_id_raw if isinstance(variant_id_raw, int) else None
            key = self._availability_match_key(product_id_raw, variant_id)
            candidates = by_key.get(key)
            if not candidates:
                continue
            item = candidates.pop(0)
            rows.append(
                {
                    "order_item": item,
                    "product_id": product_id_raw,
                    "variant_id": variant_id,
                }
            )
        return rows

    # Ключ резерва позиции заказа: product_id + effective variant.
    @staticmethod
    def _order_item_reserve_key(
        product: Product | None, item: OrderItem
    ) -> tuple[int, int | None] | None:
        if product is None:
            return None
        effective_variant_id = resolve_cart_variant_id(product, item.variant_id)
        return (int(item.product_id), effective_variant_id)

    # Суммирует quantity позиций заказа по ключу резерва.
    @staticmethod
    def _aggregate_reserve_quantities_by_key(
        items: Sequence[OrderItem],
        products_map: dict[int, Product],
    ) -> dict[tuple[int, int | None], int]:
        totals: dict[tuple[int, int | None], int] = {}
        for item in items:
            key = OrderService._order_item_reserve_key(
                products_map.get(item.product_id), item
            )
            if key is None:
                continue
            totals[key] = totals.get(key, 0) + int(item.quantity)
        return totals

    # Доступный остаток по ключам резерва без учёта резерва текущего заказа.
    async def _available_by_reserve_key_excluding_order(
        self,
        order_id: int,
        items: Sequence[OrderItem],
    ) -> tuple[
        dict[tuple[int, int | None], int], dict[int, Product], dict[int, ProductVariant]
    ]:
        product_ids = list({int(item.product_id) for item in items})
        products_map: dict[int, Product] = {}
        variant_map: dict[int, ProductVariant] = {}
        variant_ids: list[int] = []
        for product_id in product_ids:
            product = await self.product_crud.get_by_id_with_related(product_id)
            if product is None:
                continue
            products_map[product.id] = product
            for variant in product.variants or []:
                variant_map[variant.id] = variant
                variant_ids.append(int(variant.id))

        own_by_key = self._aggregate_reserve_quantities_by_key(items, products_map)
        reserved_product = await self.order_crud.get_reserved_quantities(product_ids)
        reserved_variant = await self.order_crud.get_reserved_quantities_by_variant(
            variant_ids
        )

        available_by_key: dict[tuple[int, int | None], int] = {}
        for key, own_qty in own_by_key.items():
            product_id, effective_variant_id = key
            product = products_map.get(product_id)
            if product is None:
                available_by_key[key] = 0
                continue
            if effective_variant_id is not None:
                variant = variant_map.get(effective_variant_id)
                if variant is None:
                    available_by_key[key] = 0
                    continue
                reserved = reserved_variant.get(effective_variant_id, 0) - own_qty
                raw = int(variant.inventory_quantity) - max(0, reserved)
            else:
                reserved = reserved_product.get(product_id, 0) - own_qty
                raw = int(product.stock) - max(0, reserved)
            available_by_key[key] = self.normalize_available_quantity(raw)
        return available_by_key, products_map, variant_map

    # Проверяет, что суммарный резерв по ключу не превышает доступный остаток.
    async def _validate_order_items_stock(
        self, order_id: int, items: Sequence[OrderItem]
    ) -> None:
        if not items:
            return
        (
            available_by_key,
            products_map,
            _variant_map,
        ) = await self._available_by_reserve_key_excluding_order(order_id, items)
        requested_by_key = self._aggregate_reserve_quantities_by_key(
            items, products_map
        )
        for key, requested in requested_by_key.items():
            available = available_by_key.get(key, 0)
            if requested > available:
                raise ValueError("Недостаточно товара на складе")

    # Сигнатура low-stock позиций для дедупликации событий.
    @staticmethod
    def _low_stock_signature(
        items: Sequence[dict[str, object]],
    ) -> list[tuple[int, int | None, int]]:
        signature: list[tuple[int, int | None, int]] = []
        for row in items:
            product_id = row.get("product_id")
            quantity = row.get("quantity")
            if not isinstance(product_id, int) or not isinstance(quantity, int):
                continue
            variant_raw = row.get("variant_id")
            variant_id = int(variant_raw) if isinstance(variant_raw, int) else None
            signature.append((product_id, variant_id, quantity))
        return sorted(signature)

    # Сигнатура из последнего availability_confirmation_requested.
    async def _last_availability_requested_signature(
        self, order_id: int
    ) -> list[tuple[int, int | None, int]] | None:
        events = await self.order_crud.get_order_events(order_id)
        for event in events:
            if event.event_type != "availability_confirmation_requested":
                continue
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            raw_items = payload.get("items")
            if not isinstance(raw_items, list):
                return None
            dict_items = [row for row in raw_items if isinstance(row, dict)]
            return self._low_stock_signature(dict_items)
        return None

    # Собирает low-stock позиции заказа после проверки остатков.
    async def _collect_low_stock_items_for_order(
        self,
        order_id: int,
        items: Sequence[OrderItem],
        available_by_key: dict[tuple[int, int | None], int],
        products_map: dict[int, Product],
        variant_map: dict[int, ProductVariant],
    ) -> list[dict[str, object]]:
        low_stock_items: list[dict[str, object]] = []
        for item in items:
            product = products_map.get(item.product_id)
            if product is None:
                continue
            key = self._order_item_reserve_key(product, item)
            if key is None:
                continue
            available = available_by_key.get(key, 0)
            if not self.is_borderline_available(available):
                continue
            effective_variant_id = key[1]
            title = product.title or f"Товар #{item.product_id}"
            variant_label: str | None = None
            if effective_variant_id is not None:
                variant = variant_map.get(effective_variant_id)
                if variant is not None:
                    variant_label = variant_label_from_options(
                        variant.option1,
                        variant.option2,
                        variant.option3,
                    )
            badge = buyer_stock_badge(
                available,
                ok_from_qty=settings.STOCK_OK_FROM_QTY,
                low_min_qty=settings.STOCK_LOW_MIN_QTY,
                label_in_stock="в наличии",
                label_low="мало",
                label_last="последний",
                label_out="нет",
            )
            low_stock_items.append(
                {
                    "product_id": item.product_id,
                    "variant_id": effective_variant_id,
                    "product_title": title,
                    "variant_label": variant_label,
                    "quantity": item.quantity,
                    "available": available,
                    "stock_badge": badge.text,
                }
            )
        return low_stock_items

    # Пересчитывает availability_confirmation_status после изменения состава.
    async def _recompute_order_availability(
        self,
        order: Order,
        items: Sequence[OrderItem],
    ) -> tuple[str | None, str | None]:
        previous = str(order.availability_confirmation_status or "").lower()
        availability_before: str | None = None
        availability_after: str | None = None

        (
            available_by_key,
            products_map,
            variant_map,
        ) = await self._available_by_reserve_key_excluding_order(order.id, items)
        low_stock_items = await self._collect_low_stock_items_for_order(
            order.id, items, available_by_key, products_map, variant_map
        )

        if not low_stock_items:
            if previous in {
                AvailabilityConfirmationStatus.PENDING,
                AvailabilityConfirmationStatus.UNAVAILABLE,
            }:
                availability_before = order.availability_confirmation_status
                order.availability_confirmation_status = (
                    AvailabilityConfirmationStatus.NOT_REQUIRED
                )
                order.payment_due_at = self.payment_deadline_from_now()
                availability_after = order.availability_confirmation_status
            await self._sync_order_status_from_availability(order, created_by="system")
            return availability_before, availability_after

        availability_before = order.availability_confirmation_status
        order.availability_confirmation_status = AvailabilityConfirmationStatus.PENDING
        order.payment_due_at = None
        availability_after = order.availability_confirmation_status

        new_signature = self._low_stock_signature(low_stock_items)
        last_signature = await self._last_availability_requested_signature(order.id)
        if new_signature != last_signature:
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="availability_confirmation_requested",
                event_message="Требуется подтверждение наличия",
                created_by="system",
                payload_json={"items": low_stock_items},
            )
        await self._sync_order_status_from_availability(order, created_by="system")
        return availability_before, availability_after

    # Изменились ли резервируемые позиции (не только цена).
    @staticmethod
    def _reserve_positions_changed(
        added: Sequence[dict[str, object]],
        removed: Sequence[dict[str, object]],
        changed: Sequence[dict[str, object]],
    ) -> bool:
        if added or removed:
            return True
        reserve_fields = ("product_id", "variant_id", "quantity")
        for row in changed:
            before = row.get("before")
            after = row.get("after")
            if not isinstance(before, dict) or not isinstance(after, dict):
                continue
            for field in reserve_fields:
                if before.get(field) != after.get(field):
                    return True
        return False

    # Можно ли редактировать состав в админке (политика для UI и backend).
    @classmethod
    def composition_edit_state(
        cls,
        order: Order,
        latest_attempt: OrderPaymentAttempt | None,
        now: datetime | None = None,
    ) -> tuple[bool, str | None, datetime | None]:
        if order.payment_paid_at is not None:
            return False, "Нельзя изменить оплаченный заказ", None
        status = str(order.status or "").lower()
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.COMPLETED,
            OrderStatus.FAILED,
        }:
            return (
                False,
                "Нельзя изменить состав завершённого или отменённого заказа",
                None,
            )
        if attempt_payment_resumable(latest_attempt, now):
            qr_expires_at = latest_attempt.qr_expires_at if latest_attempt else None
            return (
                False,
                "Нельзя изменить состав: по заказу действует платёж. "
                "Повторите после истечения QR-кода.",
                qr_expires_at,
            )
        return True, None, None

    # Проверяет, можно ли менять состав заказа.
    def _ensure_order_composition_editable(
        self, order: Order, *, new_total: Decimal | None = None
    ) -> None:
        if order.payment_paid_at is not None:
            raise ValueError("Нельзя изменить оплаченный заказ")
        status = str(order.status or "").lower()
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.COMPLETED,
            OrderStatus.FAILED,
        }:
            raise ValueError(
                "Нельзя изменить состав завершённого или отменённого заказа"
            )
        if new_total is not None and order.payment_order_id:
            if new_total != Decimal(order.total_amount or 0):
                raise ValueError("Нельзя изменить сумму: создан платёж у провайдера")

    # Снимок позиции заказа для audit diff.
    @staticmethod
    def _snapshot_order_item_for_audit(item: OrderItem) -> dict[str, object]:
        return {
            "order_item_id": item.id,
            "product_id": item.product_id,
            "variant_id": item.variant_id,
            "title": item.product_title_captured or f"Товар #{item.product_id}",
            "variant_label": order_item_captured_variant_label(item),
            "quantity": item.quantity,
            "unit_price": str(item.unit_price),
        }

    # Человекочитаемое название позиции для уведомлений.
    @staticmethod
    def _order_item_line_label(snapshot: dict[str, object]) -> str:
        title = str(snapshot.get("title") or "Товар")
        variant_label = snapshot.get("variant_label")
        qty = snapshot.get("quantity")
        if variant_label:
            return f"{title}, {variant_label}, {qty} шт."
        return f"{title}, {qty} шт."

    # Закупочная EUR позиции для админ-оценки: snapshot, иначе текущая цена товара.
    @staticmethod
    def _item_supplier_unit_eur(item: object, products_map: dict) -> Decimal:
        captured = getattr(item, "supplier_price_eur_captured", None)
        if captured is not None and Decimal(str(captured)) > 0:
            return Decimal(str(captured))
        product = products_map.get(int(getattr(item, "product_id", 0) or 0))
        if product is None:
            return Decimal("0")
        return Decimal(str(getattr(product, "supplier_price_eur", 0) or 0))

    # Оценка TP для админки: себестоимость, N, доставка клиента и EUR по строкам.
    @staticmethod
    def _supplier_order_estimate_display(
        tracking_admin: object | None,
        order_items: list | None = None,
        products_map: dict | None = None,
    ) -> dict[str, object]:
        goods = Decimal(
            str(getattr(tracking_admin, "supplier_cost_eur_snapshot", 0) or 0)
        )
        client_shipping = Decimal(
            str(getattr(tracking_admin, "delivery_fee_eur_snapshot", 0) or 0)
        )
        products_map = products_map or {}
        item_eur_by_id: dict[str | int, str] = {}
        goods_from_items = Decimal("0.00")
        parcel_lines: list[tuple[int, int, Decimal]] = []
        for item in order_items or []:
            qty = int(getattr(item, "quantity", 0) or 0)
            unit = OrderService._item_supplier_unit_eur(item, products_map)
            line_eur = unit * qty
            goods_from_items += line_eur
            item_id = getattr(item, "id", None)
            if item_id is not None and qty > 0:
                parcel_lines.append((int(item_id), qty, unit))
            if item_id is None or line_eur <= 0:
                continue
            formatted = format_eur(line_eur)
            item_eur_by_id[str(item_id)] = formatted
            item_eur_by_id[item_id] = formatted
        supplier_lines = None
        if goods_from_items > 0:
            goods = goods_from_items
            supplier_lines = parcel_lines or None
        estimate = estimate_supplier_orders(
            goods,
            Decimal("0"),
            supplier_lines=supplier_lines,
        )
        return {
            "goods_cost_eur": format_eur(goods),
            "minimum_orders": estimate.minimum_orders,
            "client_shipping_eur": format_eur(client_shipping),
            "item_eur_by_id": item_eur_by_id,
        }

    # Собирает оценку TP для карточки заказа без пересчёта snapshot.
    async def get_supplier_order_estimate_display(
        self,
        tracking_admin: object | None,
        order_id: int,
    ) -> dict[str, object]:
        order_items = await self.order_crud.get_order_items(order_id)
        products = await self.product_crud.get_by_ids(
            [int(item.product_id) for item in order_items]
        )
        products_map = {int(product.id): product for product in products}
        return self._supplier_order_estimate_display(
            tracking_admin, order_items, products_map
        )

    # Дописывает закупочную EUR в позиции, если snapshot пустой.
    async def _backfill_missing_supplier_eur(self, items: list[OrderItem]) -> None:
        missing = [
            item
            for item in items
            if item.supplier_price_eur_captured is None
            or Decimal(str(item.supplier_price_eur_captured or 0)) <= 0
        ]
        if not missing:
            return
        products = await self.product_crud.get_by_ids(
            [int(item.product_id) for item in missing]
        )
        products_map = {int(product.id): product for product in products}
        for item in missing:
            product = products_map.get(int(item.product_id))
            if product is None:
                continue
            item.supplier_price_eur_captured = Decimal(
                str(product.supplier_price_eur or 0)
            )
            self.session.add(item)

    # Считает snapshot закупки EUR по позициям заказа.
    @staticmethod
    def _supplier_cost_eur_from_items(items: list[OrderItem]) -> Decimal:
        total = Decimal("0")
        for item in items:
            unit = PricingService.normalize_supplier_eur(
                Decimal(str(item.supplier_price_eur_captured or 0))
            )
            total += unit * int(item.quantity)
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Пересчитывает subtotal/discount/total заказа с учётом промокода.
    async def _recalculate_order_totals(self, order: Order) -> bool:
        items = await self.order_crud.get_order_items(order.id)
        await self._backfill_missing_supplier_eur(items)
        subtotal = sum(
            (item.unit_price * item.quantity for item in items),
            start=Decimal("0"),
        )
        order.supplier_cost_eur_snapshot = self._supplier_cost_eur_from_items(items)
        promo_removed = False
        discount = Decimal("0")
        if order.promo_code_applied:
            (
                discount,
                promo,
                promo_removed,
            ) = await self.promo_service.calculate_discount_for_order_edit(
                promo_code=order.promo_code_applied,
                items_subtotal=subtotal,
            )
            if promo_removed:
                await self.promo_service.release_promo_for_order(order.id)
                order.promo_code_applied = None
                order.discount_items_amount = Decimal("0")
            else:
                order.discount_items_amount = discount
        order.items_subtotal_amount = subtotal
        order.total_amount = (
            subtotal
            - Decimal(order.discount_items_amount or 0)
            + Decimal(order.delivery_fee_amount or 0)
        )
        self.session.add(order)
        return promo_removed

    # Формирует payload новой позиции заказа для админки.
    async def _build_admin_add_item_payload(
        self, add_item: AdminOrderItemAdd
    ) -> dict[str, int | Decimal | str | None]:
        product = await self.product_crud.get_by_id_with_related(add_item.product_id)
        if product is None:
            raise ValueError(f"Товар #{add_item.product_id} не найден")
        has_variants = bool(product.variants)
        variant: ProductVariant | None = None
        if has_variants:
            if add_item.variant_id is None:
                raise ValueError("Для вариативного товара нужен variant_id")
            variant = next(
                (v for v in product.variants if v.id == add_item.variant_id),
                None,
            )
            if variant is None:
                raise ValueError("Вариант не принадлежит выбранному товару")
        elif add_item.variant_id is not None:
            raise ValueError("У товара без вариантов variant_id не нужен")
        unit_price = add_item.unit_price
        if unit_price is None:
            unit_price = self._normalize_price_snapshot(Decimal(product.sale_price))
        category_l2, category_l3 = self._product_category_snapshot(product)
        return {
            "product_id": add_item.product_id,
            "variant_id": add_item.variant_id,
            "quantity": add_item.quantity,
            "unit_price": unit_price,
            "product_title_captured": product.title,
            "product_external_id_captured": product.external_id,
            "variant_external_id_captured": (
                variant.variant_external_id if variant else None
            ),
            "variant_sku_captured": variant.sku if variant else None,
            "variant_option1_captured": variant.option1 if variant else None,
            "variant_option2_captured": variant.option2 if variant else None,
            "variant_option3_captured": variant.option3 if variant else None,
            "supplier_price_eur_captured": Decimal(
                str(product.supplier_price_eur or 0)
            ),
            "category_l2_captured": category_l2,
            "category_l3_captured": category_l3,
        }

    # Валидирует решения по low-stock позициям.
    async def _validate_availability_decisions(
        self,
        order_id: int,
        decisions: list[AdminAvailabilityItemDecision],
    ) -> dict[int, AdminAvailabilityItemDecision]:
        pending_rows = await self._resolve_pending_availability_rows(order_id)
        expected_ids = {int(row["order_item"].id) for row in pending_rows}
        if not expected_ids:
            raise ValueError("Подтверждение наличия не требуется")
        seen: set[int] = set()
        decision_map: dict[int, AdminAvailabilityItemDecision] = {}
        for decision in decisions:
            item_id = int(decision.order_item_id)
            if item_id in seen:
                raise ValueError("Дублирующийся order_item_id в проверке наличия")
            seen.add(item_id)
            if item_id not in expected_ids:
                raise ValueError("Позиция не входит в список проверки наличия")
            decision_map[item_id] = decision
        if seen != expected_ids:
            raise ValueError("Нужно указать решение для каждой проверяемой позиции")
        return decision_map

    # Сохраняет notification_outbox после enqueue вне основной транзакции.
    async def _commit_enqueued_notifications(self) -> None:
        await self.session.commit()

    # Записывает событие ошибки Telegram-уведомления отдельным commit.
    async def _record_customer_notify_failed(
        self,
        order_id: int,
        error_text: str,
        created_by: str,
    ) -> None:
        await self.order_crud.create_order_event(
            order_id=order_id,
            event_type="customer_notify_failed",
            event_message="Не удалось отправить сообщение в Telegram",
            created_by=created_by,
            payload_json={"error": error_text},
        )
        order = await self.order_crud.get_by_id(order_id)
        if order:
            await self.order_crud.commit_order(order)

    # Обновление позиций заказа админом.
    async def update_order_items(
        self,
        order_id: int,
        payload: AdminOrderItemsUpdate,
        actor: User | None = None,
    ) -> OrderSchema:
        order_schema, _warning = await self.edit_order_composition(
            order_id=order_id,
            payload=payload,
            actor=actor,
        )
        return order_schema

    # Полное редактирование состава заказа админом в одной транзакции.
    async def edit_order_composition(
        self,
        order_id: int,
        payload: AdminOrderItemsUpdate,
        actor: User | None = None,
        *,
        allow_empty_cancel: bool = False,
    ) -> tuple[OrderSchema, str | None]:
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if not order:
                raise ValueError("Заказ не найден")
            latest_attempt = await self.order_crud.get_latest_payment_attempt(order_id)
            allowed, block_reason, _qr_expires_at = self.composition_edit_state(
                order,
                latest_attempt,
                now=utc_now_naive(),
            )
            if not allowed:
                raise ValueError(block_reason or "Состав заказа нельзя изменить")
            current_items = await self.order_crud.get_order_items(order_id)
            so_service = SupplierOrderService(self.session)
            await so_service.reject_composition_if_breaks_allocation(
                order_id,
                {item.id: item.quantity for item in payload.items or []},
                {int(item_id) for item_id in (payload.remove_item_ids or [])},
            )
            snapshots_before = {
                item.id: self._snapshot_order_item_for_audit(item)
                for item in current_items
            }
            totals_before = {
                "subtotal": str(order.items_subtotal_amount or 0),
                "discount": str(order.discount_items_amount or 0),
                "total": str(order.total_amount or 0),
            }
            removed_snapshots: list[dict[str, object]] = []
            if payload.remove_item_ids:
                remove_ids = sorted(
                    {int(item_id) for item_id in payload.remove_item_ids}
                )
                for item in current_items:
                    if item.id in remove_ids:
                        removed_snapshots.append(
                            self._snapshot_order_item_for_audit(item)
                        )
                await self.order_crud.delete_order_items_by_ids(order_id, remove_ids)
            if payload.items:
                patch_ids = {item.id for item in payload.items}
                existing_ids = {item.id for item in current_items}
                foreign = patch_ids - existing_ids
                if foreign:
                    raise ValueError("Позиция не принадлежит этому заказу")
                await self.order_crud.update_order_items(
                    order_id,
                    [item.model_dump() for item in payload.items],
                )
            added_snapshots: list[dict[str, object]] = []
            if payload.add_items:
                add_payloads = []
                for add_item in payload.add_items:
                    add_payloads.append(
                        await self._build_admin_add_item_payload(add_item)
                    )
                created_rows = await self.order_crud.create_order_items(
                    order_id, add_payloads
                )
                for row in created_rows:
                    added_snapshots.append(self._snapshot_order_item_for_audit(row))
            all_items = await self.order_crud.get_order_items(order_id)
            if not all_items and not allow_empty_cancel:
                raise ValueError("Нельзя сохранить заказ без позиций")
            await self._recalculate_order_totals(order)
            await so_service.sync_unpaid_client_delivery(order)
            self._ensure_order_composition_editable(
                order, new_total=Decimal(order.total_amount or 0)
            )
            snapshots_after = {
                item.id: self._snapshot_order_item_for_audit(item) for item in all_items
            }
            changed: list[dict[str, object]] = []
            for item_id, before in snapshots_before.items():
                if item_id not in snapshots_after:
                    continue
                after = snapshots_after[item_id]
                if before != after:
                    changed.append({"before": before, "after": after})
            reserve_changed = self._reserve_positions_changed(
                added_snapshots, removed_snapshots, changed
            )
            availability_before: str | None = None
            availability_after: str | None = None
            if reserve_changed:
                await self._validate_order_items_stock(order_id, all_items)
                (
                    availability_before,
                    availability_after,
                ) = await self._recompute_order_availability(order, all_items)
            totals_after = {
                "subtotal": str(order.items_subtotal_amount or 0),
                "discount": str(order.discount_items_amount or 0),
                "total": str(order.total_amount or 0),
            }
            event_payload: dict[str, object] = {
                "added": added_snapshots,
                "removed": removed_snapshots,
                "changed": changed,
                "totals_before": totals_before,
                "totals_after": totals_after,
            }
            if (
                availability_before is not None
                and availability_after is not None
                and availability_before != availability_after
            ):
                event_payload["availability_before"] = availability_before
                event_payload["availability_after"] = availability_after
            await self.order_crud.create_order_event(
                order_id=order_id,
                event_type="order_items_edited",
                event_message=payload.event_message or "Позиции заказа обновлены",
                created_by=created_by,
                payload_json=event_payload,
            )
            stock_result = await CatalogStockService(self.session).refresh_for_order(
                order_id
            )
            await self.order_crud.commit_order(order)
            invalidate_if_catalog_boundary_changed(
                stock_result.boundary_flipped_ids,
                reason="order_stock_boundary",
            )
        except Exception:
            await self.session.rollback()
            raise
        warning: str | None = None
        if payload.notify_customer:
            notify_ok = await CustomerNotificationService(
                self.session
            ).notify_order_composition_changed(
                order_id=order_id,
                diff={
                    "added": added_snapshots,
                    "removed": removed_snapshots,
                    "changed": changed,
                },
                new_total=Decimal(order.total_amount or 0),
                created_by=created_by,
            )
            if not notify_ok:
                warning = "Изменения сохранены, но Telegram-уведомление не отправлено"
                await self._record_customer_notify_failed(
                    order_id,
                    warning,
                    created_by,
                )
            else:
                await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return (
            await self._build_order_schema_with_user(order, items, user),
            warning,
        )

    # Сохраняет результат проверки наличия по low-stock позициям.
    async def save_availability_stock_check(
        self,
        order_id: int,
        payload: AdminAvailabilityStockCheckUpdate,
        actor: User | None = None,
    ) -> tuple[OrderSchema, str | None]:
        created_by = await self._build_admin_created_by(payload.created_by, actor)
        removed_snapshots: list[dict[str, object]] = []
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if not order:
                raise ValueError("Заказ не найден")
            current = str(order.availability_confirmation_status or "").lower()
            if current != AvailabilityConfirmationStatus.PENDING:
                raise ValueError("Подтверждение наличия не требуется")
            self._ensure_order_composition_editable(order)
            decision_map = await self._validate_availability_decisions(
                order_id, payload.items
            )
            current_items = await self.order_crud.get_order_items(order_id)
            remove_ids = [
                item_id
                for item_id, decision in decision_map.items()
                if not decision.confirmed
            ]
            so_service = SupplierOrderService(self.session)
            await so_service.reject_composition_if_breaks_allocation(
                order_id, {}, set(remove_ids)
            )
            for item in current_items:
                if item.id in remove_ids:
                    removed_snapshots.append(self._snapshot_order_item_for_audit(item))
            if remove_ids:
                await self.order_crud.delete_order_items_by_ids(order_id, remove_ids)
            remaining = await self.order_crud.get_order_items(order_id)
            if remaining:
                order.availability_confirmation_status = (
                    AvailabilityConfirmationStatus.CONFIRMED
                )
                order.payment_due_at = self.payment_deadline_from_now()
                await self._sync_order_status_from_availability(
                    order, created_by=created_by
                )
            else:
                order.availability_confirmation_status = (
                    AvailabilityConfirmationStatus.UNAVAILABLE
                )
                order.status = OrderStatus.CANCELLED
            await self._recalculate_order_totals(order)
            await SupplierOrderService(self.session).sync_unpaid_client_delivery(order)
            if remaining:
                self._ensure_order_composition_editable(
                    order, new_total=Decimal(order.total_amount or 0)
                )
            await self.order_crud.create_order_event(
                order_id=order_id,
                event_type="availability_stock_check_saved",
                event_message=payload.event_message
                or "Результат проверки наличия сохранён",
                created_by=created_by,
                payload_json={
                    "removed": removed_snapshots,
                    "remaining_count": len(remaining),
                },
            )
            stock_result = await CatalogStockService(self.session).refresh_for_order(
                order_id
            )
            await self.order_crud.commit_order(order)
            invalidate_if_catalog_boundary_changed(
                stock_result.boundary_flipped_ids,
                reason="order_stock_boundary",
            )
        except Exception:
            await self.session.rollback()
            raise
        warning: str | None = None
        if payload.notify_customer:
            customer_notify = CustomerNotificationService(self.session)
            if remaining:
                notify_ok = await customer_notify.notify_availability_check_result(
                    order_id=order_id,
                    removed_items=removed_snapshots,
                    new_total=Decimal(order.total_amount or 0),
                    created_by=created_by,
                )
            else:
                notify_ok = await customer_notify.notify_order_status(
                    order_id=order_id,
                    created_by=created_by,
                    idempotency_key=availability_notify_key(order_id),
                )
            if not notify_ok:
                warning = "Изменения сохранены, но Telegram-уведомление не отправлено"
                await self._record_customer_notify_failed(
                    order_id,
                    warning,
                    created_by,
                )
            else:
                await self._commit_enqueued_notifications()
        items = await self._build_order_items(order_id)
        user = await self.session.get(User, order.user_id)
        return (
            await self._build_order_schema_with_user(order, items, user),
            warning,
        )

    # Возвращает снимок адреса доставки (JSON или плоские колонки).
    def _delivery_snapshot_from_order(self, order: Order) -> dict[str, object | None]:
        if isinstance(order.delivery_data_json, dict):
            return order.delivery_data_json
        return {
            "last_name": order.last_name,
            "first_name": order.first_name,
            "phone": order.phone,
            "street": order.street,
            "house": order.house,
            "apartment": order.apartment,
            "city": order.city,
            "postal_code": order.postal_code,
        }

    # Собирает payload заказа для отправки поставщику.
    async def build_supplier_order_payload(
        self, order_id: int
    ) -> dict[str, int | str | None | dict | list]:
        order = await self.order_crud.get_by_id(order_id)
        if not order:
            raise ValueError("Заказ не найден")
        order_items = await self.order_crud.get_order_items(order_id)
        product_ids = list({item.product_id for item in order_items})
        products_map = {
            product.id: product
            for product in await self.product_crud.get_by_ids(product_ids)
        }
        supplier_items: list[dict[str, int | str | Decimal | None]] = []
        for item in order_items:
            product = products_map.get(item.product_id)
            supplier_price_eur = (
                Decimal(str(product.supplier_price_eur))
                if product is not None
                else None
            )
            supplier_items.append(
                {
                    "product_id": item.product_id,
                    "product_external_id": item.product_external_id_captured,
                    "product_title": item.product_title_captured,
                    "variant_id": item.variant_id,
                    "variant_external_id": item.variant_external_id_captured,
                    "variant_sku": item.variant_sku_captured,
                    "option1": item.variant_option1_captured,
                    "option2": item.variant_option2_captured,
                    "option3": item.variant_option3_captured,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "supplier_price_eur": supplier_price_eur,
                }
            )
        return {
            "order": {
                "id": order.id,
                "status": order.status,
                "created_at": (
                    order.created_at.isoformat() if order.created_at else None
                ),
                "total_amount": order.total_amount,
                "eur_rate_snapshot": order.eur_rate_snapshot,
            },
            "customer_delivery": self._delivery_snapshot_from_order(order),
            "customer_data": order.customer_data_json or {},
            "items": supplier_items,
        }

    # Собирает API-схему события заказа из ORM-модели.
    def _build_order_event_schema(self, event: OrderEvent) -> OrderEventSchema:
        return OrderEventSchema(
            id=event.id,
            order_id=event.order_id,
            event_type=event.event_type,
            event_message=event.event_message,
            created_by=event.created_by,
            payload_json=event.payload_json,
            created_at=event.created_at,
        )
