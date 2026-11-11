from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, cast, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification_outbox import NotificationOutbox
from src.models.order import (
    ACTIVE_UNPAID_ORDER_STATUSES,
    AvailabilityConfirmationStatus,
    Order,
    OrderEvent,
    OrderItem,
    OrderPaymentAttempt,
    OrderStatus,
    Shipment,
    ShipmentStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.models.pricing import (
    PricingSettings,
    PromoCodeUsage,
    ReferralEarning,
    ServiceCommissionHistory,
)
from src.models.support import SupportTicket
from src.models.user import User
from src.repositories.base_repo import CRUDBase

RESERVED_ORDER_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.PROCESSING,
    OrderStatus.ASSEMBLING,
    OrderStatus.DELIVERY,
)

# asyncpg: не больше 32767 bind-параметров на запрос.
_SQL_IN_CHUNK = 8000


# Optional captured-строка из payload позиции заказа.
def _captured_text(item: Mapping[str, object], key: str) -> str | None:
    raw = item.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


class CrudOrder(CRUDBase):
    # Инициализирует репозиторий заказов.
    def __init__(self, session: AsyncSession, model: type[Order]) -> None:
        self.model = model
        self.session = session
        self.reserved_statuses = list(RESERVED_ORDER_STATUSES)

    # Приводит значение к int и валидирует обязательное поле.
    @staticmethod
    def _to_required_int(value: int | Decimal | str | None, field_name: str) -> int:
        if value is None:
            raise ValueError(f"Поле {field_name} обязательно")
        return int(value)

    # Ищет заказ по ключу идемпотентности.
    async def get_by_idempotency_key(self, idempotency_key: str | None) -> Order | None:
        if not idempotency_key:
            return None
        result = await self.session.scalars(
            select(self.model).where(self.model.idempotency_key == idempotency_key)
        )
        return result.first()

    # Возвращает заказ по первичному ключу.
    async def get_by_id(self, order_id: int) -> Order | None:
        return await self.session.get(self.model, order_id)

    # Возвращает заказ с блокировкой строки FOR UPDATE.
    async def get_by_id_for_update(self, order_id: int) -> Order | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.id == order_id).with_for_update()
        )
        return result.first()

    # Ищет заказ по идентификатору в платежном провайдере.
    async def get_by_payment_order_id(self, payment_order_id: str) -> Order | None:
        result = await self.session.scalars(
            select(self.model).where(self.model.payment_order_id == payment_order_id)
        )
        return result.first()

    # Создает заказ и его позиции в одной транзакции.
    async def create_order_with_items(
        self,
        user_id: int,
        total_amount: Decimal,
        items_subtotal_amount: Decimal,
        discount_items_amount: Decimal,
        delivery_fee_eur_snapshot: Decimal,
        delivery_fee_amount: Decimal,
        eur_rate_snapshot: Decimal,
        promo_code_applied: str | None,
        items_payload: list[dict[str, int | Decimal | str | None]],
        idempotency_key: str | None = None,
        delivery_payload: dict[str, str | None] | None = None,
        customer_data_json: dict[str, object] | None = None,
        delivery_data_json: dict[str, object] | None = None,
        availability_confirmation_status: str | None = None,
        payment_due_at: datetime | None = None,
        status: str | None = None,
        supplier_cost_eur_snapshot: Decimal = Decimal("0"),
        notification_channels: list[str] | None = None,
        notification_email: str | None = None,
    ) -> Order:
        payload = delivery_payload or {}
        order = self.model(
            user_id=user_id,
            total_amount=total_amount,
            items_subtotal_amount=items_subtotal_amount,
            discount_items_amount=discount_items_amount,
            delivery_fee_eur_snapshot=delivery_fee_eur_snapshot,
            delivery_fee_amount=delivery_fee_amount,
            eur_rate_snapshot=eur_rate_snapshot,
            promo_code_applied=promo_code_applied,
            status=status or OrderStatus.CREATED,
            availability_confirmation_status=(
                availability_confirmation_status
                or AvailabilityConfirmationStatus.NOT_REQUIRED
            ),
            idempotency_key=idempotency_key,
            last_name=payload.get("last_name"),
            first_name=payload.get("first_name"),
            street=payload.get("street"),
            house=payload.get("house"),
            apartment=payload.get("apartment"),
            city=payload.get("city"),
            postal_code=payload.get("postal_code"),
            phone=payload.get("phone"),
            customer_data_json=customer_data_json,
            delivery_data_json=delivery_data_json,
            payment_due_at=payment_due_at,
            supplier_cost_eur_snapshot=supplier_cost_eur_snapshot,
            notification_channels=notification_channels or [],
            notification_email=notification_email,
        )
        self.session.add(order)
        await self.session.flush()

        for item in items_payload:
            product_id = self._to_required_int(item.get("product_id"), "product_id")
            quantity = self._to_required_int(item.get("quantity"), "quantity")
            variant_raw = item.get("variant_id")
            self.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product_id,
                    variant_id=int(variant_raw) if variant_raw is not None else None,
                    quantity=quantity,
                    unit_price=Decimal(str(item["unit_price"])),
                    product_title_captured=(
                        str(item["product_title_captured"])
                        if item.get("product_title_captured") is not None
                        else None
                    ),
                    product_external_id_captured=(
                        str(item["product_external_id_captured"])
                        if item.get("product_external_id_captured") is not None
                        else None
                    ),
                    variant_external_id_captured=(
                        str(item["variant_external_id_captured"])
                        if item.get("variant_external_id_captured") is not None
                        else None
                    ),
                    variant_sku_captured=(
                        str(item["variant_sku_captured"])
                        if item.get("variant_sku_captured") is not None
                        else None
                    ),
                    variant_option1_captured=(
                        str(item["variant_option1_captured"])
                        if item.get("variant_option1_captured") is not None
                        else None
                    ),
                    variant_option2_captured=(
                        str(item["variant_option2_captured"])
                        if item.get("variant_option2_captured") is not None
                        else None
                    ),
                    variant_option3_captured=(
                        str(item["variant_option3_captured"])
                        if item.get("variant_option3_captured") is not None
                        else None
                    ),
                    supplier_price_eur_captured=(
                        Decimal(str(item["supplier_price_eur_captured"]))
                        if item.get("supplier_price_eur_captured") is not None
                        else None
                    ),
                    category_l2_captured=_captured_text(item, "category_l2_captured"),
                    category_l3_captured=_captured_text(item, "category_l3_captured"),
                )
            )
        await self.session.commit()
        await self.session.refresh(order)
        return order

    # Создает запись события в истории заказа.
    async def create_order_event(
        self,
        order_id: int,
        event_type: str,
        event_message: str | None = None,
        created_by: str | None = None,
        payload_json: dict | None = None,
    ) -> OrderEvent:
        event = OrderEvent(
            order_id=order_id,
            event_type=event_type,
            event_message=event_message,
            created_by=created_by,
            payload_json=payload_json,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    # Возвращает позиции заказа.
    async def get_order_items(self, order_id: int) -> list[OrderItem]:
        result = await self.session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.id.asc())
        )
        return list(result.all())

    # Возвращает события истории заказа.
    async def get_order_events(self, order_id: int) -> list[OrderEvent]:
        result = await self.session.scalars(
            select(OrderEvent)
            .where(OrderEvent.order_id == order_id)
            .order_by(OrderEvent.created_at.desc(), OrderEvent.id.desc())
        )
        return list(result.all())

    # Возвращает список заказов пользователя по дате создания.
    async def list_by_user(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Order]:
        result = await self.session.scalars(
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    # Фильтр видимости заказов в ЛК витрины.
    def _storefront_orders_filter(self, user_id: int, now: datetime):
        pending = AvailabilityConfirmationStatus.PENDING
        return (
            self.model.user_id == user_id,
            or_(
                self.model.payment_paid_at.is_not(None),
                self.model.availability_confirmation_status == pending,
                (
                    self.model.payment_paid_at.is_(None)
                    & (self.model.status != OrderStatus.CANCELLED)
                    & (
                        self.model.payment_due_at.is_(None)
                        | (self.model.payment_due_at > now)
                    )
                ),
            ),
        )

    # Список заказов пользователя для ЛК с фильтром видимости.
    async def list_by_user_for_storefront(
        self,
        user_id: int,
        now: datetime,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Order]:
        filters = self._storefront_orders_filter(user_id, now)
        result = await self.session.scalars(
            select(self.model)
            .where(*filters)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    # Количество заказов пользователя для ЛК с тем же фильтром видимости.
    async def count_by_user_for_storefront(self, user_id: int, now: datetime) -> int:
        filters = self._storefront_orders_filter(user_id, now)
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(*filters)
        )
        return int(total or 0)

    # Заказы с позициями указанного товара (для админ-карточки).
    async def count_orders_for_product(self, product_id: int) -> int:
        total = await self.session.scalar(
            select(func.count(func.distinct(self.model.id)))
            .join(OrderItem, OrderItem.order_id == self.model.id)
            .where(OrderItem.product_id == product_id)
        )
        return int(total or 0)

    # Список заказов с позициями указанного товара (для админ-карточки).
    async def list_orders_for_product(
        self,
        product_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict[str, object]]:
        safe_page = max(1, int(page))
        safe_size = max(1, int(page_size))
        offset = (safe_page - 1) * safe_size
        qty = func.sum(OrderItem.quantity)
        line_total = func.sum(OrderItem.quantity * OrderItem.unit_price)
        stmt = (
            select(
                self.model.id,
                self.model.created_at,
                self.model.status,
                qty.label("quantity"),
                line_total.label("line_total"),
            )
            .join(OrderItem, OrderItem.order_id == self.model.id)
            .where(OrderItem.product_id == product_id)
            .group_by(self.model.id, self.model.created_at, self.model.status)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
            .offset(offset)
            .limit(safe_size)
        )
        rows = (await self.session.execute(stmt)).all()
        out: list[dict[str, object]] = []
        for row in rows:
            quantity = int(row.quantity or 0)
            total = Decimal(str(row.line_total or 0))
            unit = (total / quantity) if quantity else Decimal("0")
            out.append(
                {
                    "order_id": int(row.id),
                    "created_at": row.created_at,
                    "status": str(row.status),
                    "quantity": quantity,
                    "unit_price": unit,
                    "line_total": total,
                }
            )
        return out

    # Количество активных неоплаченных заказов пользователя (best-effort лимит).
    async def count_active_unpaid_orders(self, user_id: int, now: datetime) -> int:
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(
                self.model.user_id == user_id,
                self.model.payment_paid_at.is_(None),
                self.model.status.in_(ACTIVE_UNPAID_ORDER_STATUSES),
                or_(
                    self.model.payment_due_at.is_(None),
                    self.model.payment_due_at > now,
                ),
            )
        )
        return int(total or 0)

    # Кандидаты на автоотмену по истечению срока оплаты (грубый prefilter).
    async def find_orders_for_payment_expiration(
        self,
        now: datetime,
        limit: int = 50,
    ) -> list[Order]:
        result = await self.session.scalars(
            select(self.model)
            .where(
                self.model.payment_paid_at.is_(None),
                self.model.payment_due_at.is_not(None),
                self.model.payment_due_at <= now,
                self.model.status.in_(ACTIVE_UNPAID_ORDER_STATUSES),
            )
            .order_by(self.model.payment_due_at.asc(), self.model.id.asc())
            .limit(limit)
        )
        return list(result.all())

    # Количество заказов пользователя.
    async def count_by_user(self, user_id: int) -> int:
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(self.model.user_id == user_id)
        )
        return int(total or 0)

    # Количество заказов сразу для нескольких пользователей.
    async def count_by_user_ids(self, user_ids: list[int]) -> dict[int, int]:
        unique_user_ids = sorted(set(user_ids))
        if not unique_user_ids:
            return {}
        rows = await self.session.execute(
            select(self.model.user_id, func.count(self.model.id))
            .where(self.model.user_id.in_(unique_user_ids))
            .group_by(self.model.user_id)
        )
        return {int(user_id): int(count) for user_id, count in rows.all()}

    # Количество заказов пользователя в указанном статусе.
    async def count_by_user_status(self, user_id: int, status: str) -> int:
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(
                self.model.user_id == user_id,
                self.model.status == status.strip().lower(),
            )
        )
        return int(total or 0)

    # Product id из незавершённых заказов (до удаления).
    async def list_product_ids_for_user_non_completed_orders(
        self,
        user_id: int,
    ) -> list[int]:
        rows = await self.session.scalars(
            select(OrderItem.product_id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.user_id == user_id,
                Order.status != OrderStatus.COMPLETED.value,
                OrderItem.product_id.isnot(None),
            )
            .distinct()
        )
        return [int(pid) for pid in rows.all() if pid]

    # Удаляет все заказы пользователя, кроме выполненных (completed).
    async def delete_non_completed_for_user(self, user_id: int) -> int:
        order_ids = list(
            await self.session.scalars(
                select(self.model.id).where(
                    self.model.user_id == user_id,
                    self.model.status != OrderStatus.COMPLETED.value,
                )
            )
        )
        if not order_ids:
            return 0
        await self.session.execute(
            delete(ReferralEarning).where(ReferralEarning.order_id.in_(order_ids))
        )
        await self.session.execute(
            delete(PromoCodeUsage).where(PromoCodeUsage.order_id.in_(order_ids))
        )
        await self.session.execute(
            delete(OrderEvent).where(OrderEvent.order_id.in_(order_ids))
        )
        await self.session.execute(
            delete(OrderItem).where(OrderItem.order_id.in_(order_ids))
        )
        result = await self.session.execute(
            delete(self.model).where(self.model.id.in_(order_ids))
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    # Фильтр поиска заказов по номеру, клиенту или телефону.
    def _admin_search_filter(self, q: str | None):
        if not q or not q.strip():
            return None
        raw = q.strip()
        if raw.startswith("#"):
            raw = raw[1:].strip()
        if not raw:
            return None
        needle = f"%{raw}%"
        from src.models.auth_identity import AuthIdentity
        from src.repositories.auth_identity_repo import PROVIDER_TELEGRAM

        telegram_user_ids = select(AuthIdentity.user_id).where(
            AuthIdentity.provider == PROVIDER_TELEGRAM,
            AuthIdentity.meta_json["username"].as_string().ilike(needle),
        )
        text_match = or_(
            User.name.ilike(needle),
            User.id.in_(telegram_user_ids),
            self.model.phone.ilike(needle),
            self.model.first_name.ilike(needle),
            self.model.last_name.ilike(needle),
        )
        if raw.isdigit():
            return or_(self.model.id == int(raw), text_match)
        return text_match

    # Фильтры очередей действий на странице заказов в админке.
    def _admin_queue_filters(self, queue: str | None) -> list:
        if not queue or not queue.strip():
            return []
        key = queue.strip().lower()
        if key == "availability":
            return [
                self.model.availability_confirmation_status
                == AvailabilityConfirmationStatus.PENDING,
                self.model.status.in_([OrderStatus.CREATED, OrderStatus.PROCESSING]),
            ]
        if key == "assembling":
            return [
                self.model.status == OrderStatus.CREATED,
                self.model.payment_paid_at.is_not(None),
                self.model.availability_confirmation_status.in_(
                    [
                        AvailabilityConfirmationStatus.CONFIRMED,
                        AvailabilityConfirmationStatus.NOT_REQUIRED,
                    ]
                ),
                or_(
                    self.model.supplier_order_id.is_(None),
                    self.model.supplier_order_id == "",
                ),
            ]
        if key == "tracking":
            return [
                self.model.status == OrderStatus.ASSEMBLING,
                or_(
                    self.model.supplier_tracking_id.is_(None),
                    self.model.supplier_tracking_id == "",
                ),
            ]
        return []

    # Возвращает фильтры для списка всех заказов.
    def _list_all_filters(
        self,
        status: str | list[str] | None,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
        queue: str | None = None,
    ) -> list:
        filters: list = []
        queue_filters = self._admin_queue_filters(queue)
        if queue_filters:
            filters.extend(queue_filters)
        elif status:
            if isinstance(status, list):
                statuses = [
                    item.strip().lower()
                    for item in status
                    if item and str(item).strip()
                ]
            else:
                statuses = [status.strip().lower()]
            if len(statuses) == 1:
                filters.append(self.model.status == statuses[0])
            elif statuses:
                filters.append(self.model.status.in_(statuses))
        search = self._admin_search_filter(q)
        if search is not None:
            filters.append(search)
        if created_from_utc is not None:
            filters.append(self.model.created_at >= created_from_utc)
        if created_to_exclusive_utc is not None:
            filters.append(self.model.created_at < created_to_exclusive_utc)
        if paid_from_utc is not None or paid_to_exclusive_utc is not None:
            filters.append(self.model.payment_paid_at.is_not(None))
        if paid_from_utc is not None:
            filters.append(self.model.payment_paid_at >= paid_from_utc)
        if paid_to_exclusive_utc is not None:
            filters.append(self.model.payment_paid_at < paid_to_exclusive_utc)
        return filters

    # Порядок сортировки списка заказов в админке.
    def _list_all_order_by(
        self,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
    ):
        if paid_from_utc is not None or paid_to_exclusive_utc is not None:
            return (self.model.payment_paid_at.desc(), self.model.id.desc())
        return (self.model.created_at.desc(), self.model.id.desc())

    # Нужен join с User при активном поиске.
    def _list_all_needs_user_join(self, q: str | None) -> bool:
        return self._admin_search_filter(q) is not None

    # Возвращает список всех заказов.
    async def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | list[str] | None = None,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
        queue: str | None = None,
    ) -> list[Order]:
        filters = self._list_all_filters(
            status,
            q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
            queue=queue,
        )
        order_by = self._list_all_order_by(
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
        )
        stmt = select(self.model)
        if self._list_all_needs_user_join(q):
            stmt = stmt.join(User, User.id == self.model.user_id)
        result = await self.session.scalars(
            stmt.where(*filters).order_by(*order_by).offset(offset).limit(limit)
        )
        return list(result.all())

    async def count_all(
        self,
        status: str | list[str] | None = None,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
        queue: str | None = None,
    ) -> int:
        filters = self._list_all_filters(
            status,
            q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
            queue=queue,
        )
        stmt = select(func.count(self.model.id))
        if self._list_all_needs_user_join(q):
            stmt = stmt.select_from(self.model).join(
                User, User.id == self.model.user_id
            )
        else:
            stmt = stmt.select_from(self.model)
        total = await self.session.scalar(stmt.where(*filters))
        return int(total or 0)

    # Считает заказы по status одним GROUP BY с теми же фильтрами, что list/count.
    async def count_grouped_by_status(
        self,
        q: str | None = None,
        created_from_utc: datetime | None = None,
        created_to_exclusive_utc: datetime | None = None,
        paid_from_utc: datetime | None = None,
        paid_to_exclusive_utc: datetime | None = None,
    ) -> dict[str, int]:
        filters = self._list_all_filters(
            None,
            q,
            created_from_utc=created_from_utc,
            created_to_exclusive_utc=created_to_exclusive_utc,
            paid_from_utc=paid_from_utc,
            paid_to_exclusive_utc=paid_to_exclusive_utc,
        )
        stmt = select(self.model.status, func.count(self.model.id))
        if self._list_all_needs_user_join(q):
            stmt = stmt.select_from(self.model).join(
                User, User.id == self.model.user_id
            )
        else:
            stmt = stmt.select_from(self.model)
        rows = await self.session.execute(
            stmt.where(*filters).group_by(self.model.status)
        )
        return {str(row[0]): int(row[1]) for row in rows.all()}

    # Считает заказы в одной операционной очереди админки.
    async def _count_admin_queue(self, queue: str) -> int:
        filters = self._admin_queue_filters(queue)
        if not filters:
            return 0
        total = await self.session.scalar(
            select(func.count(self.model.id)).where(*filters)
        )
        return int(total or 0)

    # Счётчики очередей действий для карточек на странице заказов.
    async def admin_orders_queues(self) -> dict[str, int]:
        availability = await self._count_admin_queue("availability")
        assembling = await self._count_admin_queue("assembling")
        tracking = await self._count_admin_queue("tracking")
        return {
            "availability": availability,
            "assembling": assembling,
            "tracking": tracking,
        }

    # Обновляет заказ.
    async def update_order(
        self, order: Order, patch_payload: dict[str, str | None]
    ) -> Order:
        for field, value in patch_payload.items():
            setattr(order, field, value)
        self.session.add(order)
        await self.session.flush()
        return order

    # Сохраняет данные созданного платежа и QR-кода.
    async def update_order_payment_init(
        self,
        order: Order,
        *,
        payment_provider: str,
        payment_order_id: str,
        payment_external_order_id: str | None,
        payment_status: str | None,
        payment_qr_id: str | None,
        payment_qr_payload: str | None,
        payment_meta_json: dict | None,
    ) -> Order:
        order.payment_provider = payment_provider
        order.payment_order_id = payment_order_id
        order.payment_external_order_id = payment_external_order_id
        order.payment_status = payment_status
        order.payment_qr_id = payment_qr_id
        order.payment_qr_payload = payment_qr_payload
        order.payment_meta_json = payment_meta_json
        self.session.add(order)
        await self.session.flush()
        return order

    # Сохраняет pre-persist meta до обращения к SBP.
    async def save_payment_init_pending(
        self,
        order: Order,
        payment_meta_json: dict,
    ) -> Order:
        order.payment_provider = "sbp"
        order.payment_meta_json = payment_meta_json
        self.session.add(order)
        await self.session.flush()
        return order

    # Атомарно привязывает provider_order_id, если ещё не задан.
    async def try_bind_provider_order_id(
        self,
        order_id: int,
        provider_order_id: str,
    ) -> bool:
        stmt = (
            update(self.model)
            .where(
                self.model.id == order_id,
                self.model.payment_provider == "sbp",
                self.model.payment_order_id.is_(None),
                self.model.payment_paid_at.is_(None),
            )
            .values(payment_order_id=provider_order_id)
            .returning(self.model.id)
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    # Атомарно подтверждает оплату, если ещё не оплачен.
    async def mark_payment_accepted_if_unpaid(
        self,
        order_id: int,
        payment_status: str,
        payment_paid_at: datetime,
        payment_last_callback_at: datetime | None = None,
        paid_supplier_order_count: int | None = None,
    ) -> int | None:
        values: dict[str, object] = {
            "payment_paid_at": payment_paid_at,
            "payment_status": payment_status,
        }
        if payment_last_callback_at is not None:
            values["payment_last_callback_at"] = payment_last_callback_at
        if paid_supplier_order_count is not None:
            values["paid_supplier_order_count"] = paid_supplier_order_count
        stmt = (
            update(self.model)
            .where(
                self.model.id == order_id,
                self.model.payment_paid_at.is_(None),
            )
            .values(**values)
            .returning(self.model.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return int(row[0]) if row else None

    # Обновляет платежный статус заказа по данным провайдера.
    async def update_order_payment_status(
        self,
        order: Order,
        *,
        payment_status: str | None,
        payment_meta_json: dict | None = None,
        payment_last_callback_at: datetime | None = None,
        payment_paid_at: datetime | None = None,
    ) -> Order:
        order.payment_status = payment_status
        if payment_meta_json is not None:
            order.payment_meta_json = payment_meta_json
        if payment_last_callback_at is not None:
            order.payment_last_callback_at = payment_last_callback_at
        if payment_paid_at is not None:
            order.payment_paid_at = payment_paid_at
        self.session.add(order)
        await self.session.flush()
        return order

    # Обновляет выбранные позиции заказа.
    async def update_order_items(
        self, order_id: int, items_patch: list[dict[str, int | Decimal | None]]
    ) -> list[OrderItem]:
        if not items_patch:
            return []
        item_ids = [self._to_required_int(item.get("id"), "id") for item in items_patch]
        existing = await self.session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.id.in_(item_ids),
            )
        )
        existing_items = {item.id: item for item in existing.all()}
        for item_patch in items_patch:
            item_id = self._to_required_int(item_patch.get("id"), "id")
            item = existing_items.get(item_id)
            if not item:
                continue
            item.quantity = self._to_required_int(
                item_patch.get("quantity"), "quantity"
            )
            if item_patch.get("unit_price") is not None:
                item.unit_price = Decimal(str(item_patch["unit_price"]))
            self.session.add(item)
        await self.session.flush()
        return list(existing_items.values())

    # Создаёт новые позиции заказа без commit.
    async def create_order_items(
        self,
        order_id: int,
        items_payload: list[dict[str, int | Decimal | str | None]],
    ) -> list[OrderItem]:
        created: list[OrderItem] = []
        for item in items_payload:
            product_id = self._to_required_int(item.get("product_id"), "product_id")
            quantity = self._to_required_int(item.get("quantity"), "quantity")
            variant_raw = item.get("variant_id")
            row = OrderItem(
                order_id=order_id,
                product_id=product_id,
                variant_id=int(variant_raw) if variant_raw is not None else None,
                quantity=quantity,
                unit_price=Decimal(str(item["unit_price"])),
                product_title_captured=(
                    str(item["product_title_captured"])
                    if item.get("product_title_captured") is not None
                    else None
                ),
                product_external_id_captured=(
                    str(item["product_external_id_captured"])
                    if item.get("product_external_id_captured") is not None
                    else None
                ),
                variant_external_id_captured=(
                    str(item["variant_external_id_captured"])
                    if item.get("variant_external_id_captured") is not None
                    else None
                ),
                variant_sku_captured=(
                    str(item["variant_sku_captured"])
                    if item.get("variant_sku_captured") is not None
                    else None
                ),
                variant_option1_captured=(
                    str(item["variant_option1_captured"])
                    if item.get("variant_option1_captured") is not None
                    else None
                ),
                variant_option2_captured=(
                    str(item["variant_option2_captured"])
                    if item.get("variant_option2_captured") is not None
                    else None
                ),
                variant_option3_captured=(
                    str(item["variant_option3_captured"])
                    if item.get("variant_option3_captured") is not None
                    else None
                ),
                supplier_price_eur_captured=(
                    Decimal(str(item["supplier_price_eur_captured"]))
                    if item.get("supplier_price_eur_captured") is not None
                    else None
                ),
                category_l2_captured=_captured_text(item, "category_l2_captured"),
                category_l3_captured=_captured_text(item, "category_l3_captured"),
            )
            self.session.add(row)
            created.append(row)
        await self.session.flush()
        return created

    # Удаляет позиции заказа по id без commit.
    async def delete_order_items_by_ids(
        self, order_id: int, item_ids: list[int]
    ) -> int:
        if not item_ids:
            return 0
        unique_ids = sorted({int(item_id) for item_id in item_ids})
        existing = await self.session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.id.in_(unique_ids),
            )
        )
        rows = list(existing.all())
        if len(rows) != len(unique_ids):
            raise ValueError("Позиция не принадлежит этому заказу")
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()
        return len(rows)

    # Безвозвратно удаляет заказы и связанные строки.
    async def delete_orders_by_ids(self, order_ids: list[int]) -> int:
        unique_ids = sorted(
            {int(order_id) for order_id in order_ids if int(order_id) > 0}
        )
        if not unique_ids:
            return 0
        # 3A-3E: снять RESTRICT (Shipment → lines → SupplierOrder), затем старые deps.
        await self.session.execute(
            delete(Shipment).where(Shipment.order_id.in_(unique_ids))
        )
        supplier_order_ids = select(SupplierOrder.id).where(
            SupplierOrder.order_id.in_(unique_ids)
        )
        await self.session.execute(
            delete(SupplierOrderLine).where(
                SupplierOrderLine.supplier_order_id.in_(supplier_order_ids)
            )
        )
        await self.session.execute(
            delete(SupplierOrder).where(SupplierOrder.order_id.in_(unique_ids))
        )
        await self.session.execute(
            update(SupportTicket)
            .where(SupportTicket.order_id.in_(unique_ids))
            .values(order_id=None)
        )
        await self.session.execute(
            delete(ReferralEarning).where(ReferralEarning.order_id.in_(unique_ids))
        )
        await self.session.execute(
            delete(PromoCodeUsage).where(PromoCodeUsage.order_id.in_(unique_ids))
        )
        await self.session.execute(
            delete(OrderPaymentAttempt).where(
                OrderPaymentAttempt.order_id.in_(unique_ids)
            )
        )
        await self.session.execute(
            delete(OrderEvent).where(OrderEvent.order_id.in_(unique_ids))
        )
        await self.session.execute(
            delete(OrderItem).where(OrderItem.order_id.in_(unique_ids))
        )
        for order_id in unique_ids:
            await self.session.execute(
                delete(NotificationOutbox).where(
                    or_(
                        NotificationOutbox.idempotency_key.like(f"%:order:{order_id}"),
                        NotificationOutbox.idempotency_key.like(
                            f"%:order:{order_id}:%"
                        ),
                    )
                )
            )
        result = await self.session.execute(
            delete(Order).where(Order.id.in_(unique_ids))
        )
        await self.session.commit()
        return int(result.rowcount or 0)

    # Фиксирует транзакцию по заказу и возвращает обновленный объект.
    async def commit_order(self, order: Order) -> Order:
        await self.session.commit()
        await self.session.refresh(order)
        return order

    # Возвращает суммарный резерв товара в активных заказах.
    async def get_reserved_quantity(
        self, product_id: int, variant_id: int | None = None
    ) -> int:
        filters = [
            OrderItem.product_id == product_id,
            self.model.status.in_(self.reserved_statuses),
            OrderItem.variant_id == variant_id,
        ]
        result = await self.session.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(self.model, self.model.id == OrderItem.order_id)
            .where(*filters)
        )
        return int(result or 0)

    # Возвращает резервы по нескольким товарам.
    async def get_reserved_quantities(self, product_ids: list[int]) -> dict[int, int]:
        unique = sorted({int(pid) for pid in product_ids if pid})
        if not unique:
            return {}
        result: dict[int, int] = {}
        for start in range(0, len(unique), _SQL_IN_CHUNK):
            chunk = unique[start : start + _SQL_IN_CHUNK]
            rows = (
                await self.session.execute(
                    select(OrderItem.product_id, func.sum(OrderItem.quantity))
                    .select_from(OrderItem)
                    .join(self.model, self.model.id == OrderItem.order_id)
                    .where(
                        OrderItem.product_id.in_(chunk),
                        self.model.status.in_(self.reserved_statuses),
                    )
                    .group_by(OrderItem.product_id)
                )
            ).all()
            for product_id, quantity in rows:
                result[int(product_id)] = int(quantity or 0)
        return result

    # Возвращает резервы по списку вариантов.
    async def get_reserved_quantities_by_variant(
        self, variant_ids: list[int]
    ) -> dict[int, int]:
        unique = sorted({int(vid) for vid in variant_ids if vid})
        if not unique:
            return {}
        result: dict[int, int] = {}
        for start in range(0, len(unique), _SQL_IN_CHUNK):
            chunk = unique[start : start + _SQL_IN_CHUNK]
            rows = (
                await self.session.execute(
                    select(OrderItem.variant_id, func.sum(OrderItem.quantity))
                    .select_from(OrderItem)
                    .join(self.model, self.model.id == OrderItem.order_id)
                    .where(
                        OrderItem.variant_id.in_(chunk),
                        self.model.status.in_(self.reserved_statuses),
                    )
                    .group_by(OrderItem.variant_id)
                )
            ).all()
            for variant_id, quantity in rows:
                if variant_id is not None:
                    result[int(variant_id)] = int(quantity or 0)
        return result

    # Создаёт запись платёжной попытки.
    async def create_payment_attempt(
        self,
        order_id: int,
        attempt_number: int,
        provider: str,
        merchant_order_id: str,
        x_req_id_order: str,
        x_req_id_qr: str,
        payment_amount_minor: int,
        payment_currency: str,
        init_state: str,
    ) -> OrderPaymentAttempt:
        attempt = OrderPaymentAttempt(
            order_id=order_id,
            attempt_number=attempt_number,
            provider=provider,
            merchant_order_id=merchant_order_id,
            x_req_id_order=x_req_id_order,
            x_req_id_qr=x_req_id_qr,
            payment_amount_minor=payment_amount_minor,
            payment_currency=payment_currency,
            init_state=init_state,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    # Возвращает попытку по id.
    async def get_payment_attempt_by_id(
        self, attempt_id: int
    ) -> OrderPaymentAttempt | None:
        return await self.session.get(OrderPaymentAttempt, attempt_id)

    # Возвращает попытку по id с блокировкой FOR UPDATE.
    async def get_payment_attempt_by_id_for_update(
        self, attempt_id: int
    ) -> OrderPaymentAttempt | None:
        result = await self.session.scalars(
            select(OrderPaymentAttempt)
            .where(OrderPaymentAttempt.id == attempt_id)
            .with_for_update()
        )
        return result.first()

    # Ищет попытку по provider_order_id.
    async def get_payment_attempt_by_provider_order_id(
        self, provider_order_id: str
    ) -> OrderPaymentAttempt | None:
        result = await self.session.scalars(
            select(OrderPaymentAttempt).where(
                OrderPaymentAttempt.provider_order_id == provider_order_id
            )
        )
        return result.first()

    # Ищет попытку по merchant_order_id.
    async def get_payment_attempt_by_merchant_order_id(
        self, merchant_order_id: str
    ) -> OrderPaymentAttempt | None:
        result = await self.session.scalars(
            select(OrderPaymentAttempt).where(
                OrderPaymentAttempt.merchant_order_id == merchant_order_id
            )
        )
        return result.first()

    # Количество платёжных попыток заказа.
    async def count_payment_attempts(self, order_id: int) -> int:
        total = await self.session.scalar(
            select(func.count(OrderPaymentAttempt.id)).where(
                OrderPaymentAttempt.order_id == order_id
            )
        )
        return int(total or 0)

    # Batch: количество попыток оплаты по заказам.
    async def count_payment_attempts_for_orders(
        self, order_ids: list[int]
    ) -> dict[int, int]:
        if not order_ids:
            return {}
        rows = await self.session.execute(
            select(
                OrderPaymentAttempt.order_id,
                func.count(OrderPaymentAttempt.id),
            )
            .where(OrderPaymentAttempt.order_id.in_(order_ids))
            .group_by(OrderPaymentAttempt.order_id)
        )
        counts = {order_id: 0 for order_id in order_ids}
        for order_id, total in rows.all():
            counts[int(order_id)] = int(total)
        return counts

    # Возвращает все попытки заказа по возрастанию номера.
    async def list_payment_attempts_for_order(
        self, order_id: int
    ) -> list[OrderPaymentAttempt]:
        result = await self.session.scalars(
            select(OrderPaymentAttempt)
            .where(OrderPaymentAttempt.order_id == order_id)
            .order_by(OrderPaymentAttempt.attempt_number.asc())
        )
        return list(result.all())

    # Возвращает последнюю попытку заказа.
    async def get_latest_payment_attempt(
        self, order_id: int
    ) -> OrderPaymentAttempt | None:
        result = await self.session.scalars(
            select(OrderPaymentAttempt)
            .where(OrderPaymentAttempt.order_id == order_id)
            .order_by(OrderPaymentAttempt.attempt_number.desc())
            .limit(1)
        )
        return result.first()

    # Batch: последняя попытка для каждого order_id.
    async def get_latest_payment_attempts_for_orders(
        self, order_ids: list[int]
    ) -> dict[int, OrderPaymentAttempt]:
        unique = sorted({int(oid) for oid in order_ids if oid})
        if not unique:
            return {}
        result: dict[int, OrderPaymentAttempt] = {}
        for start in range(0, len(unique), _SQL_IN_CHUNK):
            chunk = unique[start : start + _SQL_IN_CHUNK]
            subq = (
                select(
                    OrderPaymentAttempt.order_id,
                    func.max(OrderPaymentAttempt.attempt_number).label("max_num"),
                )
                .where(OrderPaymentAttempt.order_id.in_(chunk))
                .group_by(OrderPaymentAttempt.order_id)
                .subquery()
            )
            rows = await self.session.scalars(
                select(OrderPaymentAttempt).join(
                    subq,
                    (OrderPaymentAttempt.order_id == subq.c.order_id)
                    & (OrderPaymentAttempt.attempt_number == subq.c.max_num),
                )
            )
            for attempt in rows.all():
                result[int(attempt.order_id)] = attempt
        return result

    # Следующий номер попытки для заказа.
    async def get_next_payment_attempt_number(self, order_id: int) -> int:
        current = await self.session.scalar(
            select(func.max(OrderPaymentAttempt.attempt_number)).where(
                OrderPaymentAttempt.order_id == order_id
            )
        )
        return int(current or 0) + 1

    # Попытки для reconciliation: QR истёк, статус не финальный.
    async def find_payment_attempts_for_reconciliation(
        self,
        now: datetime,
        limit: int = 50,
    ) -> list[OrderPaymentAttempt]:
        terminal = ("IPS_ACCEPTED", "DECLINED")
        result = await self.session.scalars(
            select(OrderPaymentAttempt)
            .where(
                OrderPaymentAttempt.qr_expires_at.is_not(None),
                OrderPaymentAttempt.qr_expires_at <= now,
                or_(
                    OrderPaymentAttempt.provider_status.is_(None),
                    func.upper(OrderPaymentAttempt.provider_status).not_in(terminal),
                ),
            )
            .order_by(OrderPaymentAttempt.qr_expires_at.asc())
            .limit(limit)
        )
        return list(result.all())

    # Атомарно привязывает provider_order_id к попытке в creating.
    async def try_bind_attempt_provider_order_id(
        self,
        attempt_id: int,
        provider_order_id: str,
        provider_status: str | None,
    ) -> bool:
        stmt = (
            update(OrderPaymentAttempt)
            .where(
                OrderPaymentAttempt.id == attempt_id,
                OrderPaymentAttempt.init_state == "creating",
                OrderPaymentAttempt.provider_order_id.is_(None),
                OrderPaymentAttempt.paid_at.is_(None),
            )
            .values(
                provider_order_id=provider_order_id,
                provider_status=provider_status,
            )
            .returning(OrderPaymentAttempt.id)
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    # Атомарно подтверждает оплату попытки, если ещё не оплачена.
    async def mark_payment_attempt_paid_if_unpaid(
        self,
        attempt_id: int,
        paid_at: datetime,
        provider_status: str,
        last_callback_at: datetime | None = None,
    ) -> int | None:
        values: dict[str, object] = {
            "paid_at": paid_at,
            "provider_status": provider_status,
        }
        if last_callback_at is not None:
            values["last_callback_at"] = last_callback_at
        stmt = (
            update(OrderPaymentAttempt)
            .where(
                OrderPaymentAttempt.id == attempt_id,
                OrderPaymentAttempt.paid_at.is_(None),
            )
            .values(**values)
            .returning(OrderPaymentAttempt.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return int(row[0]) if row else None

    # Синхронизирует агрегированные payment_* поля заказа из попытки.
    async def sync_order_payment_aggregate(
        self,
        order: Order,
        attempt: OrderPaymentAttempt,
        *,
        is_latest_attempt: bool,
    ) -> Order:
        status = str(attempt.provider_status or "").upper()
        order_is_paid = order.payment_paid_at is not None

        if status == "IPS_ACCEPTED":
            order.payment_provider = attempt.provider
            order.payment_order_id = attempt.provider_order_id
            order.payment_status = status
            self.session.add(order)
            await self.session.flush()
            return order

        if order_is_paid:
            self.session.add(order)
            await self.session.flush()
            return order

        if not is_latest_attempt:
            self.session.add(order)
            await self.session.flush()
            return order

        order.payment_provider = attempt.provider
        order.payment_order_id = attempt.provider_order_id
        order.payment_status = attempt.provider_status
        if attempt.last_callback_at is not None:
            order.payment_last_callback_at = attempt.last_callback_at
        self.session.add(order)
        await self.session.flush()
        return order

    # Есть ли другая оплаченная попытка у заказа.
    async def has_paid_payment_attempt_excluding(
        self,
        order_id: int,
        attempt_id: int,
    ) -> bool:
        result = await self.session.scalar(
            select(func.count(OrderPaymentAttempt.id)).where(
                OrderPaymentAttempt.order_id == order_id,
                OrderPaymentAttempt.id != attempt_id,
                OrderPaymentAttempt.paid_at.is_not(None),
            )
        )
        return int(result or 0) > 0

    # Проверяет наличие события заказа по типу.
    async def has_order_event_type(self, order_id: int, event_type: str) -> bool:
        result = await self.session.scalar(
            select(func.count(OrderEvent.id)).where(
                OrderEvent.order_id == order_id,
                OrderEvent.event_type == event_type,
            )
        )
        return int(result or 0) > 0

    # Агрегирует оплаченные заказы для финансового отчёта по bucket MSK.
    async def aggregate_paid_orders_finance(
        self,
        paid_from: datetime,
        paid_to_exclusive: datetime,
        bucket: str,
    ) -> list[dict[str, object]]:
        safe_bucket = bucket if bucket in {"day", "week", "month"} else "day"
        items_qty_subq = (
            select(
                OrderItem.order_id.label("order_id"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("items_qty"),
            ).group_by(OrderItem.order_id)
        ).subquery()
        order_lines = (
            select(
                self.model.id.label("order_id"),
                self.model.payment_paid_at.label("payment_paid_at"),
                self.model.total_amount.label("total_amount"),
                self.model.supplier_cost_eur_snapshot.label(
                    "supplier_cost_eur_snapshot"
                ),
                self.model.eur_rate_snapshot.label("eur_rate_snapshot"),
                self.model.delivery_fee_amount.label("delivery_fee_amount"),
                func.coalesce(items_qty_subq.c.items_qty, 0).label("items_qty"),
            )
            .outerjoin(items_qty_subq, items_qty_subq.c.order_id == self.model.id)
            .where(
                self.model.payment_paid_at.is_not(None),
                self.model.payment_paid_at >= paid_from,
                self.model.payment_paid_at < paid_to_exclusive,
            )
        ).subquery()

        order_paid_msk = func.timezone(
            "Europe/Moscow",
            func.timezone("UTC", order_lines.c.payment_paid_at),
        )
        bucket_expr = func.date_trunc(safe_bucket, order_paid_msk)
        cogs_rub = (
            order_lines.c.supplier_cost_eur_snapshot * order_lines.c.eur_rate_snapshot
        )
        paid_date_msk = func.date(order_paid_msk)
        history_commission_rate = (
            select(ServiceCommissionHistory.commission_percent)
            .where(ServiceCommissionHistory.effective_from <= paid_date_msk)
            .order_by(ServiceCommissionHistory.effective_from.desc())
            .limit(1)
            .correlate(order_lines)
            .scalar_subquery()
        )
        settings_commission_rate = (
            select(PricingSettings.service_commission_percent)
            .limit(1)
            .scalar_subquery()
        )
        commission_rate = func.coalesce(
            history_commission_rate,
            settings_commission_rate,
            Decimal("6.50"),
        )
        commission_rub_line = (
            order_lines.c.total_amount * commission_rate / Decimal("100")
        )

        stmt = (
            select(
                bucket_expr.label("bucket"),
                func.count(order_lines.c.order_id).label("orders_count"),
                func.sum(order_lines.c.items_qty).label("items_count"),
                func.sum(order_lines.c.total_amount).label("turnover"),
                func.sum(cogs_rub).label("cogs_rub"),
                func.sum(order_lines.c.delivery_fee_amount).label("delivery_rub"),
                func.sum(commission_rub_line).label("commission_rub"),
            )
            .select_from(order_lines)
            .group_by(bucket_expr)
            .order_by(bucket_expr.desc())
        )
        result = await self.session.execute(stmt)
        return [dict(row._mapping) for row in result.all()]

    # Возвращает оплаченные заказы за период для разбора финансов.
    async def list_paid_orders_for_finance_detail(
        self,
        paid_from: datetime,
        paid_to_exclusive: datetime,
    ) -> list[Order]:
        result = await self.session.scalars(
            select(self.model)
            .where(
                self.model.payment_paid_at.is_not(None),
                self.model.payment_paid_at >= paid_from,
                self.model.payment_paid_at < paid_to_exclusive,
            )
            .order_by(self.model.payment_paid_at.desc(), self.model.id.desc())
        )
        return list(result.all())

    # Возвращает позиции заказов, сгруппированные по order_id.
    async def list_order_items_grouped(
        self, order_ids: list[int]
    ) -> dict[int, list[OrderItem]]:
        if not order_ids:
            return {}
        result = await self.session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.order_id.asc(), OrderItem.id.asc())
        )
        grouped: dict[int, list[OrderItem]] = {}
        for item in result.all():
            grouped.setdefault(item.order_id, []).append(item)
        return grouped

    # Заказы с непустым legacy TP ID для идемпотентного backfill 3A.
    async def list_orders_with_legacy_supplier_id(
        self, order_id: int | None = None
    ) -> list[Order]:
        filters = [
            self.model.supplier_order_id.is_not(None),
            func.btrim(self.model.supplier_order_id) != "",
        ]
        if order_id is not None:
            filters.append(self.model.id == order_id)
        result = await self.session.scalars(
            select(self.model).where(*filters).order_by(self.model.id.asc())
        )
        return list(result.all())

    # ID заказов, у которых уже есть хотя бы один SupplierOrder.
    async def order_ids_with_supplier_orders(self, order_ids: list[int]) -> set[int]:
        if not order_ids:
            return set()
        result = await self.session.scalars(
            select(SupplierOrder.order_id).where(SupplierOrder.order_id.in_(order_ids))
        )
        return set(result.all())

    # SupplierOrder по глобальному TP number (external_id).
    async def get_supplier_order_by_external_id(
        self, external_id: str
    ) -> SupplierOrder | None:
        result = await self.session.scalar(
            select(SupplierOrder).where(SupplierOrder.external_id == external_id)
        )
        return result

    # SupplierOrder заказа по seq.
    async def list_supplier_orders_for_order(
        self, order_id: int
    ) -> list[SupplierOrder]:
        result = await self.session.scalars(
            select(SupplierOrder)
            .where(SupplierOrder.order_id == order_id)
            .order_by(SupplierOrder.seq.asc(), SupplierOrder.id.asc())
        )
        return list(result.all())

    # SupplierOrder нескольких заказов одним запросом, порядок order_id, seq, id.
    async def list_supplier_orders_for_order_ids(
        self, order_ids: list[int]
    ) -> list[SupplierOrder]:
        if not order_ids:
            return []
        result = await self.session.scalars(
            select(SupplierOrder)
            .where(SupplierOrder.order_id.in_(order_ids))
            .order_by(
                SupplierOrder.order_id.asc(),
                SupplierOrder.seq.asc(),
                SupplierOrder.id.asc(),
            )
        )
        return list(result.all())

    # Lines нескольких SupplierOrder.
    async def list_supplier_order_lines_for_ids(
        self, supplier_order_ids: list[int]
    ) -> list[SupplierOrderLine]:
        if not supplier_order_ids:
            return []
        result = await self.session.scalars(
            select(SupplierOrderLine)
            .where(SupplierOrderLine.supplier_order_id.in_(supplier_order_ids))
            .order_by(
                SupplierOrderLine.supplier_order_id.asc(),
                SupplierOrderLine.id.asc(),
            )
        )
        return list(result.all())

    # Все placed SupplierOrder; опционально один заказ.
    async def list_placed_supplier_orders(
        self, order_id: int | None = None
    ) -> list[SupplierOrder]:
        filters = [SupplierOrder.status == SupplierOrderStatus.PLACED]
        if order_id is not None:
            filters.append(SupplierOrder.order_id == order_id)
        result = await self.session.scalars(
            select(SupplierOrder)
            .where(*filters)
            .order_by(SupplierOrder.order_id.asc(), SupplierOrder.seq.asc())
        )
        return list(result.all())

    # Заказы с TP number без placed SO с тем же external_id.
    async def list_orders_with_tp_missing_placed_so(
        self, order_id: int | None = None
    ) -> list[Order]:
        filters = [
            Order.supplier_order_id.is_not(None),
            func.length(func.btrim(Order.supplier_order_id)) > 0,
        ]
        if order_id is not None:
            filters.append(Order.id == order_id)
        has_placed = exists(
            select(SupplierOrder.id).where(
                SupplierOrder.order_id == Order.id,
                SupplierOrder.status == SupplierOrderStatus.PLACED,
                SupplierOrder.external_id == func.btrim(Order.supplier_order_id),
            )
        )
        result = await self.session.scalars(
            select(Order).where(*filters).where(~has_placed).order_by(Order.id.asc())
        )
        return list(result.all())

    # Shipment по id.
    async def get_shipment_by_id(self, shipment_id: int) -> Shipment | None:
        return await self.session.get(Shipment, shipment_id)

    # Shipment по id с блокировкой строки FOR UPDATE.
    async def get_shipment_by_id_for_update(self, shipment_id: int) -> Shipment | None:
        result = await self.session.scalars(
            select(Shipment).where(Shipment.id == shipment_id).with_for_update()
        )
        return result.first()

    # Delivered Shipment с due pending_retry в delivered_alert.
    # Без фильтра Order.status: A может ретраиться после finalize (completed).
    async def list_shipments_pending_delivered_alert_retry(
        self, now: datetime, limit: int
    ) -> list[Shipment]:
        alert = cast(Shipment.delivered_alert, JSONB)
        result = await self.session.scalars(
            select(Shipment)
            .where(
                Shipment.status == ShipmentStatus.DELIVERED,
                Shipment.delivered_alert.is_not(None),
                alert["pending_retry"].astext == "true",
                alert["next_retry_at"].astext.is_not(None),
                cast(alert["next_retry_at"].astext, DateTime) <= now,
            )
            .order_by(cast(alert["next_retry_at"].astext, DateTime).asc())
            .limit(max(1, limit))
        )
        return list(result.all())

    # Shipment по SupplierOrder.id.
    async def get_shipment_by_supplier_order_id(
        self, supplier_order_id: int
    ) -> Shipment | None:
        result = await self.session.scalar(
            select(Shipment).where(Shipment.supplier_order_id == supplier_order_id)
        )
        return result

    # Shipment заказа по id.
    async def list_shipments_for_order(self, order_id: int) -> list[Shipment]:
        return await self.list_shipments_for_order_ids([order_id])

    # Посылки нескольких заказов одним запросом, порядок order_id, id.
    async def list_shipments_for_order_ids(
        self, order_ids: list[int]
    ) -> list[Shipment]:
        if not order_ids:
            return []
        result = await self.session.scalars(
            select(Shipment)
            .where(Shipment.order_id.in_(order_ids))
            .order_by(Shipment.order_id.asc(), Shipment.id.asc())
        )
        return list(result.all())

    # Есть ли Shipment на этот SupplierOrder.
    async def shipment_exists_for_supplier_order(self, supplier_order_id: int) -> bool:
        result = await self.session.scalar(
            select(Shipment.id).where(Shipment.supplier_order_id == supplier_order_id)
        )
        return result is not None

        # Позиции заказа по id (для подписей lines в админке).

    async def get_order_items_by_ids(self, item_ids: list[int]) -> list[OrderItem]:
        if not item_ids:
            return []
        result = await self.session.scalars(
            select(OrderItem).where(OrderItem.id.in_(item_ids))
        )
        return list(result.all())
