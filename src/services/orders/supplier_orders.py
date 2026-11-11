from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.content.client_texts import (
    CUSTOMER_ASSEMBLY_PARCEL_DRAFT,
    CUSTOMER_ASSEMBLY_SINGLE_DRAFT,
)
from src.core.config import settings
from src.core.order_limits import (
    SupplierOrderAllocationError,
    _quantize_eur,
    estimate_supplier_orders,
    max_supplier_goods_eur,
    recommend_draft_parcels,
)
from src.models.order import (
    Order,
    OrderItem,
    OrderPaymentAttempt,
    OrderStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderStatus,
)
from src.models.user import User
from src.repositories.order_repo import CrudOrder
from src.services.customer_notification_service import CustomerNotificationService
from src.services.notifications.customer_notification_keys import (
    assembly_parcel_notify_key,
)
from src.services.pricing.calculator import calculate_delivery_rub
from src.services.pricing.service import PricingService
from src.utils.datetime_fmt import utc_now_naive
from src.utils.payment import attempt_payment_resumable

BACKFILL_PLACED_BY = "backfill:3a"

SUPPLIER_ORDER_STATUS_LABELS: dict[str, str] = {
    SupplierOrderStatus.DRAFT: "Черновик",
    SupplierOrderStatus.PLACED: "Оформлен",
    SupplierOrderStatus.CANCELLED: "Отменён",
}


# Qty allocation внутри одного SO из view или line map.
def supplier_order_allocated_qty(so: object) -> int:
    by_item = getattr(so, "line_qty_by_item_id", None)
    if isinstance(by_item, dict) and by_item:
        return sum(int(qty or 0) for qty in by_item.values())
    lines = getattr(so, "lines", None) or ()
    return sum(int(getattr(line, "quantity", 0) or 0) for line in lines)


# Сборка закрыта: leftover=0 и все непустые active SO placed.
# Cancelled и пустой draft не блокируют.
def packing_assembly_complete(
    fully_allocated: bool,
    statuses_and_qty: Sequence[tuple[str, int]],
) -> bool:
    if not fully_allocated:
        return False
    placed = 0
    for status, qty in statuses_and_qty:
        if status == SupplierOrderStatus.CANCELLED:
            continue
        if status == SupplierOrderStatus.PLACED:
            placed += 1
            continue
        if status == SupplierOrderStatus.DRAFT and int(qty) <= 0:
            continue
        return False
    return placed > 0


@dataclass(frozen=True)
class SupplierOrderLineView:
    order_item_id: int
    quantity: int
    unit_supplier_eur: Decimal
    goods_eur: Decimal
    product_title: str | None


@dataclass(frozen=True)
class ParcelLineControl:
    order_item_id: int
    title: str | None
    ordered_qty: int
    in_parcel_qty: int
    leftover_qty: int
    unit_supplier_eur: Decimal
    max_qty: int
    plus_disabled: bool
    minus_disabled: bool
    capacity_hint: str | None


@dataclass(frozen=True)
class RecommendedParcelLineView:
    title: str
    quantity: int
    unit_supplier_eur: Decimal


@dataclass(frozen=True)
class RecommendedParcelView:
    seq: int
    goods_eur: Decimal
    goods_cap_eur: Decimal
    goods_remaining_eur: Decimal
    goods_fill_percent: int
    lines: tuple[tuple[int, int, Decimal], ...]
    items: tuple[RecommendedParcelLineView, ...]


@dataclass(frozen=True)
class PackingRecommendation:
    parcels: tuple[RecommendedParcelView, ...]
    splits: tuple[tuple[str, tuple[int, ...]], ...]
    can_apply: bool
    block_reason: str | None
    replaces_drafts: bool
    goods_eur: Decimal
    goods_cap_eur: Decimal
    paid_count: int | None
    needed_count: int
    paid_n_blocked: bool


@dataclass(frozen=True)
class SupplierOrderView:
    id: int
    seq: int
    status: str
    status_label: str
    external_id: str | None
    goods_eur: Decimal
    supplier_shipping_eur: Decimal
    lines: list[SupplierOrderLineView]
    is_draft: bool
    line_qty_by_item_id: dict[int, int]
    line_controls: tuple[ParcelLineControl, ...]
    place_copy_text: str | None
    goods_cap_eur: Decimal
    goods_remaining_eur: Decimal
    goods_fill_percent: int
    customer_notify_label: str = "—"
    customer_notify_draft: str = ""
    can_notify: bool = False


@dataclass(frozen=True)
class SupplierOrderBackfillStats:
    scanned: int
    created_orders: int
    created_lines: int
    skipped: int


@dataclass(frozen=True)
class OrderItemAllocationView:
    order_item_id: int
    ordered_qty: int
    allocated_qty: int
    remaining_qty: int


# Нормализует legacy TP ID: пустая строка → нет заказа у поставщика.
def normalize_legacy_supplier_order_id(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    return value or None


# Снимок shipping поставщика на момент backfill/place (не в client total).
def supplier_shipping_snapshot_eur() -> Decimal:
    return _quantize_eur(Decimal(str(settings.SUPPLIER_ORDER_SHIPPING_EUR)))


# Считает goods_eur по allocation lines.
def goods_eur_from_lines(
    lines: list[tuple[int, Decimal]],
) -> Decimal:
    total = Decimal("0.00")
    for quantity, unit in lines:
        total += Decimal(quantity) * _quantize_eur(unit)
    return _quantize_eur(total)


# Display-only: cap / остаток EUR / % заполнения посылки (не меняет инварианты).
def parcel_goods_fill_display(goods_eur: Decimal) -> tuple[Decimal, Decimal, int]:
    cap = max_supplier_goods_eur()
    goods = _quantize_eur(Decimal(str(goods_eur or 0)))
    remaining = _quantize_eur(max(Decimal("0.00"), cap - goods))
    if cap <= 0:
        percent = 0
    else:
        percent = int(
            (goods * 100 / cap).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        percent = max(0, min(100, percent))
    return cap, remaining, percent


# Display-only подсказка: заполнять текущую посылку или создать следующую.
def packing_next_action_hint(
    leftover_qty: int,
    min_leftover_unit: Decimal | None,
    draft_goods: Sequence[Decimal],
    can_create: bool,
    block: str | None,
) -> str | None:
    if leftover_qty <= 0:
        return "Все товары уже распределены по посылкам."
    if block:
        return None
    cap = max_supplier_goods_eur()
    room_in_draft = False
    if min_leftover_unit is not None:
        for goods in draft_goods:
            if _quantize_eur(Decimal(str(goods or 0))) + min_leftover_unit <= cap:
                room_in_draft = True
                break
    if draft_goods and room_in_draft:
        return "Добавьте оставшиеся товары в текущую посылку."
    if can_create and draft_goods and not room_in_draft:
        return "Текущая посылка заполнена. Создайте следующую."
    if can_create:
        return "Создайте посылку и распределите товары."
    return "Остались нераспределённые товары, но новую посылку создать нельзя."


# Сколько посылок получат packing-уведомление: placed или с товарами.
def assembly_parcel_count(views: Sequence[object]) -> int:
    count = 0
    for view in views:
        status = str(getattr(view, "status", "") or "")
        if status == SupplierOrderStatus.CANCELLED:
            continue
        lines = getattr(view, "lines", None) or ()
        if status == SupplierOrderStatus.PLACED or lines:
            count += 1
    return count


# Черновик packing TG: одна посылка или нумерованная при нескольких.
def render_assembly_parcel_message(
    template: str | None,
    order_id: int,
    seq: int,
    parcel_count: int,
) -> str:
    default = (
        CUSTOMER_ASSEMBLY_SINGLE_DRAFT
        if parcel_count <= 1
        else CUSTOMER_ASSEMBLY_PARCEL_DRAFT
    )
    raw = (template or "").strip() or default
    text = raw.replace("{order_id}", str(order_id)).replace("{seq}", str(seq))
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


# Keys outbox packing-notify для карточек SO, включая суффикс канала.
def assembly_notify_outbox_keys_for_orders(
    order_id: int,
    views: Sequence[object],
) -> list[str]:
    keys: list[str] = []
    for view in views:
        so_id = getattr(view, "id", None)
        if not so_id:
            continue
        base = assembly_parcel_notify_key(order_id, int(so_id))
        keys.extend((base, f"{base}:telegram", f"{base}:email"))
    return keys


# Накладывает outbox packing-notify на карточки SO.
def apply_assembly_notify_state(
    views: Sequence[SupplierOrderView],
    order_id: int,
    outbox_by_key: Mapping[str, str],
    event_rows: Sequence[Mapping[str, object]] | None = None,
) -> list[SupplierOrderView]:
    # Circular: shipments импортирует normalize_legacy_supplier_order_id.
    from src.services.orders.shipments import (
        SHIPMENT_TELEGRAM_SENT_MARK,
        customer_notify_label_for_outbox,
        merge_customer_notify_sent_from_events,
        outbox_status_for_customer_key,
    )

    lookup = merge_customer_notify_sent_from_events(outbox_by_key, event_rows)
    parcel_count = assembly_parcel_count(views)
    updated: list[SupplierOrderView] = []
    for view in views:
        key = assembly_parcel_notify_key(order_id, view.id)
        status = outbox_status_for_customer_key(lookup, key)
        label = customer_notify_label_for_outbox(status)
        can_notify = (
            str(view.status) == SupplierOrderStatus.PLACED
            and label != SHIPMENT_TELEGRAM_SENT_MARK
        )
        draft = render_assembly_parcel_message(None, order_id, view.seq, parcel_count)
        updated.append(
            replace(
                view,
                customer_notify_label=label,
                customer_notify_draft=draft,
                can_notify=can_notify,
            )
        )
    return updated


# Max qty в этой посылке: leftover по всем SO + остаток EUR.
def parcel_line_qty_control(
    in_parcel_qty: int,
    leftover_qty: int,
    unit_supplier_eur: Decimal,
    remaining_eur: Decimal,
) -> tuple[int, bool, bool, str | None]:
    in_parcel = max(0, int(in_parcel_qty))
    leftover = max(0, int(leftover_qty))
    unit = _quantize_eur(Decimal(str(unit_supplier_eur or 0)))
    room = _quantize_eur(Decimal(str(remaining_eur or 0)))
    if unit <= 0:
        extra_fit = leftover
    else:
        extra_fit = int((room / unit).to_integral_value(rounding=ROUND_FLOOR))
        extra_fit = max(0, extra_fit)
    max_qty = in_parcel + min(leftover, extra_fit)
    plus_disabled = in_parcel >= max_qty
    minus_disabled = in_parcel <= 0
    hint = None
    if leftover > 0 and extra_fit <= 0:
        hint = "Не помещается в эту посылку"
    return max_qty, plus_disabled, minus_disabled, hint


# Текст для копирования в TP: qty/price с линий SO, не OrderItem.
def format_supplier_order_place_copy(
    seq: int,
    line_views: Sequence[SupplierOrderLineView],
    items_by_id: Mapping[int, OrderItem],
    goods_eur: Decimal,
    supplier_shipping_eur: Decimal,
) -> str:
    rows = [
        f"SO #{int(seq)}",
        f"Товары {goods_eur} EUR",
        f"Доставка поставщика {supplier_shipping_eur} EUR",
        "",
    ]
    for view in line_views:
        item = items_by_id.get(view.order_item_id)
        title = view.product_title or f"Позиция #{view.order_item_id}"
        sku = ""
        if item is not None:
            sku = str(
                item.variant_sku_captured or item.variant_external_id_captured or ""
            ).strip()
        suffix = f" [{sku}]" if sku else ""
        rows.append(f"{title}{suffix} × {view.quantity} × {view.unit_supplier_eur} EUR")
    return "\n".join(rows).strip()


# Суммирует allocated/remaining по позициям без проверки инвариантов.
def item_allocations_from_rows(
    ordered_items: Sequence[tuple[int, int]],
    allocated_lines: Sequence[tuple[int, int]],
) -> list[OrderItemAllocationView]:
    allocated: dict[int, int] = {}
    for item_id, qty in allocated_lines:
        allocated[item_id] = allocated.get(item_id, 0) + int(qty)
    views: list[OrderItemAllocationView] = []
    for item_id, ordered_qty in ordered_items:
        ordered = int(ordered_qty)
        done = allocated.get(item_id, 0)
        views.append(
            OrderItemAllocationView(
                order_item_id=item_id,
                ordered_qty=ordered,
                allocated_qty=done,
                remaining_qty=ordered - done,
            )
        )
    return views


# Отклоняет qty<=0, чужой item и over-allocation; leftover и split — ок.
def validate_allocation_lines(
    ordered_qty: Mapping[int, int],
    lines: Sequence[tuple[int, int]],
) -> list[OrderItemAllocationView]:
    for item_id, qty in lines:
        if int(qty) <= 0:
            raise SupplierOrderAllocationError(
                "Количество в заказе поставщика должно быть больше нуля"
            )
        if item_id not in ordered_qty:
            raise SupplierOrderAllocationError("Позиция не входит в клиентский заказ")
    views = item_allocations_from_rows(list(ordered_qty.items()), lines)
    for view in views:
        if view.allocated_qty > view.ordered_qty:
            raise SupplierOrderAllocationError(
                "Нельзя распределить больше штук, чем в позиции заказа"
            )
    return views


# Одна line на пару SupplierOrder × OrderItem.
def validate_unique_supplier_order_item_lines(
    pairs: Sequence[tuple[int, int]],
) -> None:
    if len(pairs) != len(set(pairs)):
        raise SupplierOrderAllocationError(
            "В одном заказе поставщика позиция может быть только один раз"
        )


# goods_eur одного SupplierOrder не выше капа Phase 1 (270.01).
def validate_supplier_order_goods_eur(goods_eur: Decimal) -> None:
    goods = _quantize_eur(Decimal(str(goods_eur or 0)))
    cap = max_supplier_goods_eur()
    if goods > cap:
        raise SupplierOrderAllocationError(
            "Сумма товаров в заказе поставщика превышает лимит"
        )


# N из оплаченного client delivery snapshot, не live ceil(goods/270.01).
def paid_supplier_order_count_from_snapshot(
    delivery_fee_eur_snapshot: Decimal,
    client_delivery_unit_eur: Decimal,
) -> int:
    total = _quantize_eur(Decimal(str(delivery_fee_eur_snapshot or 0)))
    unit = _quantize_eur(Decimal(str(client_delivery_unit_eur or 0)))
    if total <= 0 or unit <= 0:
        return 0
    return int((total / unit).to_integral_value(rounding=ROUND_HALF_UP))


# После оплаты actual не больше N из snapshot; до оплаты лимита нет.
def validate_actual_count_against_paid_snapshot(
    actual_count: int,
    delivery_fee_eur_snapshot: Decimal,
    client_delivery_unit_eur: Decimal,
    is_paid: bool,
) -> None:
    if not is_paid:
        return
    paid_n = paid_supplier_order_count_from_snapshot(
        delivery_fee_eur_snapshot,
        client_delivery_unit_eur,
    )
    if actual_count > paid_n:
        raise SupplierOrderAllocationError(
            "После оплаты нельзя создать больше заказов поставщика, чем уже оплачено"
        )


# Проверяет черновик SO: unique items, leftover, cap 270.01. Не пишет в БД.
def validate_proposed_supplier_order(
    ordered_qty: Mapping[int, int],
    existing_lines: Sequence[tuple[int, int]],
    proposed_lines: Sequence[tuple[int, int, Decimal]],
) -> list[OrderItemAllocationView]:
    proposed_item_ids = [item_id for item_id, _qty, _unit in proposed_lines]
    if len(proposed_item_ids) != len(set(proposed_item_ids)):
        raise SupplierOrderAllocationError(
            "В одном заказе поставщика позиция может быть только один раз"
        )
    proposed_qty_lines = [(item_id, qty) for item_id, qty, _unit in proposed_lines]
    views = validate_allocation_lines(
        ordered_qty, list(existing_lines) + proposed_qty_lines
    )
    goods = goods_eur_from_lines(
        [(qty, unit) for _item_id, qty, unit in proposed_lines]
    )
    validate_supplier_order_goods_eur(goods)
    return views


# Линии заказа для N: captured или 0, без live-цены товара.
def _captured_parcel_lines(
    items: Sequence[OrderItem],
) -> list[tuple[int, int, Decimal]] | None:
    lines: list[tuple[int, int, Decimal]] = []
    for item in items:
        qty = int(item.quantity or 0)
        if qty <= 0:
            continue
        lines.append(
            (
                int(item.id),
                qty,
                Decimal(str(item.supplier_price_eur_captured or 0)),
            )
        )
    return lines or None


# Биллинг N: actual не может быть ниже minimum_orders.
def billed_supplier_order_count(actual_count: int, minimum_orders: int) -> int:
    return max(int(actual_count or 0), int(minimum_orders or 0))


# Client delivery EUR до оплаты: billed N × unit.
def unpaid_delivery_eur(
    actual_count: int,
    minimum_orders: int,
    client_delivery_unit_eur: Decimal,
) -> Decimal:
    n = billed_supplier_order_count(actual_count, minimum_orders)
    unit = _quantize_eur(Decimal(str(client_delivery_unit_eur or 0)))
    return _quantize_eur(Decimal(n) * unit)


# Read-only + идемпотентный backfill 3A. Write draft/place — не раньше 3C/3D.
class SupplierOrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_crud = CrudOrder(session=session, model=Order)

    # Список SupplierOrder заказа для админки (read-only).
    async def list_for_order(self, order_id: int) -> list[SupplierOrderView]:
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        if not headers:
            return []
        items = await self.order_crud.get_order_items(order_id)
        items_by_id = {item.id: item for item in items}
        lines = await self.order_crud.list_supplier_order_lines_for_ids(
            [header.id for header in headers]
        )
        lines_by_so: dict[int, list[SupplierOrderLine]] = {}
        for line in lines:
            lines_by_so.setdefault(line.supplier_order_id, []).append(line)
        active_ids = {
            header.id
            for header in headers
            if str(header.status) != SupplierOrderStatus.CANCELLED
        }
        allocations = item_allocations_from_rows(
            [(item.id, int(item.quantity or 0)) for item in items],
            [
                (line.order_item_id, int(line.quantity))
                for line in lines
                if line.supplier_order_id in active_ids
            ],
        )
        leftover_by_id = {
            view.order_item_id: view.remaining_qty for view in allocations
        }
        views: list[SupplierOrderView] = []
        for header in headers:
            line_views: list[SupplierOrderLineView] = []
            for line in lines_by_so.get(header.id, []):
                item = items_by_id.get(line.order_item_id)
                unit = _quantize_eur(Decimal(str(line.unit_supplier_eur or 0)))
                qty = int(line.quantity)
                line_views.append(
                    SupplierOrderLineView(
                        order_item_id=line.order_item_id,
                        quantity=qty,
                        unit_supplier_eur=unit,
                        goods_eur=_quantize_eur(Decimal(qty) * unit),
                        product_title=(
                            item.product_title_captured if item is not None else None
                        ),
                    )
                )
            status = str(header.status or "")
            line_qty_by_item_id = {
                line_view.order_item_id: line_view.quantity for line_view in line_views
            }
            goods_eur = goods_eur_from_lines(
                [
                    (line_view.quantity, line_view.unit_supplier_eur)
                    for line_view in line_views
                ]
            )
            shipping_eur = _quantize_eur(
                Decimal(str(header.supplier_shipping_eur or 0))
            )
            cap_eur, remaining_eur, fill_percent = parcel_goods_fill_display(goods_eur)
            place_copy_text = None
            line_controls: tuple[ParcelLineControl, ...] = ()
            if status == SupplierOrderStatus.DRAFT:
                place_copy_text = format_supplier_order_place_copy(
                    int(header.seq),
                    line_views,
                    items_by_id,
                    goods_eur,
                    shipping_eur,
                )
                controls: list[ParcelLineControl] = []
                for item in items:
                    unit = _quantize_eur(
                        Decimal(str(item.supplier_price_eur_captured or 0))
                    )
                    in_parcel = line_qty_by_item_id.get(item.id, 0)
                    leftover = leftover_by_id.get(item.id, int(item.quantity or 0))
                    max_qty, plus_disabled, minus_disabled, hint = (
                        parcel_line_qty_control(
                            in_parcel, leftover, unit, remaining_eur
                        )
                    )
                    controls.append(
                        ParcelLineControl(
                            order_item_id=item.id,
                            title=item.product_title_captured,
                            ordered_qty=int(item.quantity or 0),
                            in_parcel_qty=in_parcel,
                            leftover_qty=leftover,
                            unit_supplier_eur=unit,
                            max_qty=max_qty,
                            plus_disabled=plus_disabled,
                            minus_disabled=minus_disabled,
                            capacity_hint=hint,
                        )
                    )
                line_controls = tuple(controls)
            views.append(
                SupplierOrderView(
                    id=header.id,
                    seq=int(header.seq),
                    status=status,
                    status_label=SUPPLIER_ORDER_STATUS_LABELS.get(status, status),
                    external_id=header.external_id,
                    goods_eur=goods_eur,
                    supplier_shipping_eur=shipping_eur,
                    lines=line_views,
                    is_draft=status == SupplierOrderStatus.DRAFT,
                    line_qty_by_item_id=line_qty_by_item_id,
                    line_controls=line_controls,
                    place_copy_text=place_copy_text,
                    goods_cap_eur=cap_eur,
                    goods_remaining_eur=remaining_eur,
                    goods_fill_percent=fill_percent,
                )
            )
        parcel_count = assembly_parcel_count(views)
        return [
            replace(
                view,
                customer_notify_draft=render_assembly_parcel_message(
                    None, order_id, view.seq, parcel_count
                ),
            )
            for view in views
        ]

    # Headers нескольких заказов одним запросом, без lines.
    async def list_headers_for_order_ids(
        self, order_ids: list[int]
    ) -> list[SupplierOrder]:
        return await self.order_crud.list_supplier_orders_for_order_ids(order_ids)

    # Remaining по OrderItem: draft+placed; cancelled не считаются.
    async def list_item_allocations(
        self, order_id: int
    ) -> list[OrderItemAllocationView]:
        items = await self.order_crud.get_order_items(order_id)
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        active_ids = [
            header.id
            for header in headers
            if str(header.status) != SupplierOrderStatus.CANCELLED
        ]
        lines = await self.order_crud.list_supplier_order_lines_for_ids(active_ids)
        return item_allocations_from_rows(
            [(item.id, int(item.quantity or 0)) for item in items],
            [(line.order_item_id, int(line.quantity)) for line in lines],
        )

    # Не даёт уменьшить/удалить OrderItem ниже уже распределённого qty.
    async def reject_composition_if_breaks_allocation(
        self,
        order_id: int,
        new_qty_by_id: Mapping[int, int],
        remove_ids: set[int],
    ) -> None:
        allocations = await self.list_item_allocations(order_id)
        for view in allocations:
            if view.order_item_id in remove_ids and view.allocated_qty > 0:
                raise SupplierOrderAllocationError(
                    "Нельзя удалить позицию: она уже распределена в заказ поставщика"
                )
            if view.order_item_id not in new_qty_by_id:
                continue
            if new_qty_by_id[view.order_item_id] < view.allocated_qty:
                raise SupplierOrderAllocationError(
                    "Нельзя уменьшить количество ниже уже распределённого"
                )

    # Active SO: draft + placed (cancelled не в actual).
    def _active_headers(self, headers: list[SupplierOrder]) -> list[SupplierOrder]:
        return [
            header
            for header in headers
            if str(header.status) != SupplierOrderStatus.CANCELLED
        ]

    # Считает billed N по товарам и фактическим SO.
    async def _billed_count_for_order(self, order: Order) -> int:
        items = await self.order_crud.get_order_items(order.id)
        settings_row = await PricingService(self.session).get_settings()
        unit = Decimal(str(settings_row.delivery_fee_eur))
        goods = goods_eur_from_lines(
            [
                (
                    int(item.quantity or 0),
                    Decimal(str(item.supplier_price_eur_captured or 0)),
                )
                for item in items
            ]
        )
        estimate = estimate_supplier_orders(
            goods,
            unit,
            len(items),
            supplier_lines=_captured_parcel_lines(items),
        )
        headers = await self.order_crud.list_supplier_orders_for_order(order.id)
        actual = len(self._active_headers(headers))
        return billed_supplier_order_count(actual, estimate.minimum_orders)

    # Контекст packing для админки: remaining, min/actual/delivery, can_create.
    async def packing_context(self, order_id: int) -> dict[str, object]:
        order = await self.order_crud.get_by_id(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        items = await self.order_crud.get_order_items(order_id)
        allocations = await self.list_item_allocations(order_id)
        by_id = {view.order_item_id: view for view in allocations}
        settings_row = await PricingService(self.session).get_settings()
        unit = Decimal(str(settings_row.delivery_fee_eur))
        goods = goods_eur_from_lines(
            [
                (
                    int(item.quantity or 0),
                    Decimal(str(item.supplier_price_eur_captured or 0)),
                )
                for item in items
            ]
        )
        estimate = estimate_supplier_orders(
            goods,
            unit,
            len(items),
            supplier_lines=_captured_parcel_lines(items),
        )
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        actual = len(self._active_headers(headers))
        billed = billed_supplier_order_count(actual, estimate.minimum_orders)
        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        block = self._packing_block_reason(order, latest)
        paid_n = order.paid_supplier_order_count
        can_create = block is None
        if can_create and order.payment_paid_at is not None:
            can_create = paid_n is not None and actual < int(paid_n)
        remaining_rows = []
        leftover_qty = 0
        leftover_units: list[Decimal] = []
        for item in items:
            view = by_id.get(item.id)
            ordered_qty = int(item.quantity or 0)
            remaining_qty = view.remaining_qty if view else ordered_qty
            unit_eur = _quantize_eur(
                Decimal(str(item.supplier_price_eur_captured or 0))
            )
            remaining_rows.append(
                {
                    "order_item_id": item.id,
                    "title": item.product_title_captured,
                    "ordered_qty": ordered_qty,
                    "allocated_qty": view.allocated_qty if view else 0,
                    "remaining_qty": remaining_qty,
                    "unit_supplier_eur": unit_eur,
                }
            )
            leftover_qty += remaining_qty
            if remaining_qty > 0:
                leftover_units.append(unit_eur)
        draft_ids = [
            header.id
            for header in headers
            if str(header.status) == SupplierOrderStatus.DRAFT
        ]
        draft_lines = await self.order_crud.list_supplier_order_lines_for_ids(draft_ids)
        goods_by_draft: dict[int, list[tuple[int, Decimal]]] = {
            header_id: [] for header_id in draft_ids
        }
        for line in draft_lines:
            goods_by_draft.setdefault(line.supplier_order_id, []).append(
                (
                    int(line.quantity),
                    _quantize_eur(Decimal(str(line.unit_supplier_eur or 0))),
                )
            )
        draft_goods = [
            goods_eur_from_lines(goods_by_draft.get(header_id, []))
            for header_id in draft_ids
        ]
        cap_eur = max_supplier_goods_eur()
        ordered_qty_total = sum(int(row["ordered_qty"]) for row in remaining_rows)
        allocated_qty_total = sum(int(row["allocated_qty"]) for row in remaining_rows)
        fully_allocated = leftover_qty <= 0 and ordered_qty_total > 0
        qty_by_so: dict[int, int] = {}
        for line in draft_lines:
            so_id = int(line.supplier_order_id)
            qty_by_so[so_id] = qty_by_so.get(so_id, 0) + int(line.quantity)
        placed_lines = await self.order_crud.list_supplier_order_lines_for_ids(
            [
                header.id
                for header in headers
                if str(header.status) == SupplierOrderStatus.PLACED
            ]
        )
        for line in placed_lines:
            so_id = int(line.supplier_order_id)
            qty_by_so[so_id] = qty_by_so.get(so_id, 0) + int(line.quantity)
        statuses_and_qty = [
            (str(header.status or ""), qty_by_so.get(int(header.id), 0))
            for header in headers
        ]
        active_headers = self._active_headers(headers)
        placed_count = sum(
            1
            for header in active_headers
            if str(header.status) == SupplierOrderStatus.PLACED
        )
        placeable_count = sum(
            1
            for header in active_headers
            if str(header.status) == SupplierOrderStatus.PLACED
            or qty_by_so.get(int(header.id), 0) > 0
        )
        return {
            "remaining_rows": remaining_rows,
            "ordered_qty_total": ordered_qty_total,
            "allocated_qty_total": allocated_qty_total,
            "goods_eur_total": goods,
            "fully_allocated": fully_allocated,
            "placed_count": placed_count,
            "placeable_count": placeable_count,
            "assembly_complete": packing_assembly_complete(
                fully_allocated, statuses_and_qty
            ),
            "manual_target_so_id": draft_ids[0] if len(draft_ids) == 1 else None,
            "minimum_orders": estimate.minimum_orders,
            "actual_count": actual,
            "billed_count": billed,
            "client_delivery_eur": _quantize_eur(
                Decimal(str(order.delivery_fee_eur_snapshot or 0))
            ),
            "supplier_shipping_eur": supplier_shipping_snapshot_eur(),
            "paid_supplier_order_count": paid_n,
            "can_create": can_create,
            "packing_block_reason": block,
            "item_qty_by_id": {item.id: int(item.quantity or 0) for item in items},
            "goods_cap_eur": cap_eur,
            "leftover_qty": leftover_qty,
            "next_action_hint": packing_next_action_hint(
                leftover_qty,
                min(leftover_units) if leftover_units else None,
                draft_goods,
                can_create,
                block,
            ),
        }

    # Блокирует packing для cancelled/QR; после оплаты delivery не трогаем.
    def _packing_block_reason(
        self,
        order: Order,
        latest_attempt: OrderPaymentAttempt | None,
    ) -> str | None:
        status = str(order.status or "").lower()
        if status in {
            OrderStatus.CANCELLED,
            OrderStatus.COMPLETED,
            OrderStatus.FAILED,
        }:
            return "Нельзя менять packing завершённого или отменённого заказа"
        if order.payment_paid_at is None and attempt_payment_resumable(latest_attempt):
            return (
                "Нельзя менять packing: по заказу действует платёж. "
                "Повторите после истечения QR-кода."
            )
        return None

    # Пересчитывает client delivery до оплаты по billed N.
    async def sync_unpaid_client_delivery(self, order: Order) -> None:
        if order.payment_paid_at is not None:
            return
        settings_row = await PricingService(self.session).get_settings()
        unit = Decimal(str(settings_row.delivery_fee_eur))
        items = await self.order_crud.get_order_items(order.id)
        goods = goods_eur_from_lines(
            [
                (
                    int(item.quantity or 0),
                    Decimal(str(item.supplier_price_eur_captured or 0)),
                )
                for item in items
            ]
        )
        estimate = estimate_supplier_orders(
            goods,
            unit,
            len(items),
            supplier_lines=_captured_parcel_lines(items),
        )
        headers = await self.order_crud.list_supplier_orders_for_order(order.id)
        actual = len(self._active_headers(headers))
        delivery_eur = unpaid_delivery_eur(actual, estimate.minimum_orders, unit)
        order.delivery_fee_eur_snapshot = delivery_eur
        order.delivery_fee_amount = calculate_delivery_rub(
            delivery_eur, Decimal(str(order.eur_rate_snapshot or 0))
        )
        order.total_amount = (
            Decimal(order.items_subtotal_amount or 0)
            - Decimal(order.discount_items_amount or 0)
            + Decimal(order.delivery_fee_amount or 0)
        )
        self.session.add(order)

    # Фиксирует paid N один раз в момент первой оплаты.
    async def freeze_paid_supplier_order_count(self, order: Order) -> int:
        if order.paid_supplier_order_count is not None:
            return int(order.paid_supplier_order_count)
        paid_n = await self._billed_count_for_order(order)
        order.paid_supplier_order_count = paid_n
        self.session.add(order)
        return paid_n

    # Создаёт пустой draft SO; после оплаты — только если actual < paid N.
    async def create_draft(self, order_id: int) -> SupplierOrder:
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if order is None:
                raise ValueError("Заказ не найден")
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            block = self._packing_block_reason(order, latest)
            if block:
                raise SupplierOrderAllocationError(block)
            headers = await self.order_crud.list_supplier_orders_for_order(order_id)
            active = self._active_headers(headers)
            if order.payment_paid_at is not None:
                cap = order.paid_supplier_order_count
                if cap is None or len(active) >= int(cap):
                    raise SupplierOrderAllocationError(
                        "После оплаты нельзя создать больше заказов поставщика, "
                        "чем уже оплачено"
                    )
            next_seq = max((header.seq for header in headers), default=0) + 1
            header = SupplierOrder(
                order_id=order.id,
                seq=next_seq,
                status=SupplierOrderStatus.DRAFT,
                goods_eur=Decimal("0.00"),
                supplier_shipping_eur=supplier_shipping_snapshot_eur(),
            )
            self.session.add(header)
            await self.session.flush()
            await self.sync_unpaid_client_delivery(order)
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="supplier_order_draft_created",
                event_message=f"Черновик заказа поставщика #{header.seq}",
                created_by="admin",
                payload_json={"supplier_order_id": header.id, "seq": header.seq},
            )
            await self.session.commit()
            await self.session.refresh(header)
            return header
        except Exception:
            await self.session.rollback()
            raise

    # Удаляет draft SO вместе с lines.
    async def delete_draft(self, order_id: int, supplier_order_id: int) -> None:
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if order is None:
                raise ValueError("Заказ не найден")
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            block = self._packing_block_reason(order, latest)
            if block:
                raise SupplierOrderAllocationError(block)
            headers = await self.order_crud.list_supplier_orders_for_order(order_id)
            header = next((row for row in headers if row.id == supplier_order_id), None)
            if header is None:
                raise ValueError("Заказ поставщика не найден")
            if str(header.status) != SupplierOrderStatus.DRAFT:
                raise SupplierOrderAllocationError(
                    "Можно удалить только черновик заказа поставщика"
                )
            await self.session.delete(header)
            await self.session.flush()
            await self.sync_unpaid_client_delivery(order)
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="supplier_order_draft_deleted",
                event_message=f"Удалён черновик заказа поставщика #{header.seq}",
                created_by="admin",
                payload_json={
                    "supplier_order_id": supplier_order_id,
                    "seq": header.seq,
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    # Сохраняет allocation draft SO; placed не редактируется.
    async def save_draft_lines(
        self,
        order_id: int,
        supplier_order_id: int,
        quantities: dict[int, int],
    ) -> None:
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if order is None:
                raise ValueError("Заказ не найден")
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            block = self._packing_block_reason(order, latest)
            if block:
                raise SupplierOrderAllocationError(block)
            headers = await self.order_crud.list_supplier_orders_for_order(order_id)
            header = next((row for row in headers if row.id == supplier_order_id), None)
            if header is None:
                raise ValueError("Заказ поставщика не найден")
            if str(header.status) != SupplierOrderStatus.DRAFT:
                raise SupplierOrderAllocationError(
                    "Состав оформленного заказа поставщика нельзя изменить"
                )
            items = await self.order_crud.get_order_items(order_id)
            ordered = {item.id: int(item.quantity or 0) for item in items}
            units = {
                item.id: _quantize_eur(
                    Decimal(str(item.supplier_price_eur_captured or 0))
                )
                for item in items
            }
            other_ids = [
                row.id for row in self._active_headers(headers) if row.id != header.id
            ]
            other_lines = await self.order_crud.list_supplier_order_lines_for_ids(
                other_ids
            )
            existing = [
                (line.order_item_id, int(line.quantity)) for line in other_lines
            ]
            proposed: list[tuple[int, int, Decimal]] = []
            for item_id, qty in quantities.items():
                qty_int = int(qty)
                if qty_int == 0:
                    continue
                proposed.append((item_id, qty_int, units.get(item_id, Decimal("0.00"))))
            validate_proposed_supplier_order(ordered, existing, proposed)
            current_lines = await self.order_crud.list_supplier_order_lines_for_ids(
                [header.id]
            )
            for line in current_lines:
                await self.session.delete(line)
            await self.session.flush()
            for item_id, qty, unit in proposed:
                self.session.add(
                    SupplierOrderLine(
                        supplier_order_id=header.id,
                        order_item_id=item_id,
                        quantity=qty,
                        unit_supplier_eur=unit,
                    )
                )
            header.goods_eur = goods_eur_from_lines(
                [(qty, unit) for _item_id, qty, unit in proposed]
            )
            self.session.add(header)
            await self.session.flush()
            await self.sync_unpaid_client_delivery(order)
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="supplier_order_lines_saved",
                event_message=f"Состав черновика поставщика #{header.seq} обновлён",
                created_by="admin",
                payload_json={
                    "supplier_order_id": header.id,
                    "seq": header.seq,
                    "goods_eur": str(header.goods_eur),
                },
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    # Preview: leftover после placed, drafts игнорируются. Ничего не пишет.
    async def packing_recommendation(self, order_id: int) -> PackingRecommendation:
        order = await self.order_crud.get_by_id(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        items = await self.order_crud.get_order_items(order_id)
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        latest = await self.order_crud.get_latest_payment_attempt(order_id)
        block = self._packing_block_reason(order, latest)
        placed = [
            header
            for header in headers
            if str(header.status) == SupplierOrderStatus.PLACED
        ]
        drafts = [
            header
            for header in headers
            if str(header.status) == SupplierOrderStatus.DRAFT
        ]
        placed_lines = await self.order_crud.list_supplier_order_lines_for_ids(
            [header.id for header in placed]
        )
        leftover_views = item_allocations_from_rows(
            [(item.id, int(item.quantity or 0)) for item in items],
            [(line.order_item_id, int(line.quantity)) for line in placed_lines],
        )
        leftover_by_id = {
            view.order_item_id: view.remaining_qty for view in leftover_views
        }
        leftover_items = [
            (
                item.id,
                leftover_by_id.get(item.id, int(item.quantity or 0)),
                _quantize_eur(Decimal(str(item.supplier_price_eur_captured or 0))),
            )
            for item in items
            if leftover_by_id.get(item.id, int(item.quantity or 0)) > 0
        ]
        titles = {
            item.id: (item.product_title_captured or f"Позиция #{item.id}")
            for item in items
        }
        cap = max_supplier_goods_eur()
        paid_count = (
            int(order.paid_supplier_order_count)
            if order.payment_paid_at is not None
            and order.paid_supplier_order_count is not None
            else None
        )
        try:
            bins = recommend_draft_parcels(leftover_items, cap)
        except SupplierOrderAllocationError as exc:
            return PackingRecommendation(
                parcels=(),
                splits=(),
                can_apply=False,
                block_reason=str(exc),
                replaces_drafts=bool(drafts),
                goods_eur=Decimal("0.00"),
                goods_cap_eur=cap,
                paid_count=paid_count,
                needed_count=len(placed),
                paid_n_blocked=False,
            )
        parcels: list[RecommendedParcelView] = []
        for idx, lines in enumerate(bins, start=1):
            goods = goods_eur_from_lines([(qty, unit) for _id, qty, unit in lines])
            cap_eur, remaining_eur, fill_percent = parcel_goods_fill_display(goods)
            parcel_items = tuple(
                RecommendedParcelLineView(
                    title=titles.get(item_id, f"Позиция #{item_id}"),
                    quantity=qty,
                    unit_supplier_eur=unit,
                )
                for item_id, qty, unit in lines
            )
            parcels.append(
                RecommendedParcelView(
                    seq=idx,
                    goods_eur=goods,
                    goods_cap_eur=cap_eur,
                    goods_remaining_eur=remaining_eur,
                    goods_fill_percent=fill_percent,
                    lines=tuple(lines),
                    items=parcel_items,
                )
            )
        splits: list[tuple[str, tuple[int, ...]]] = []
        for item_id, _qty, _unit in leftover_items:
            qtys = tuple(
                sum(qty for line_id, qty, _u in parcel.lines if line_id == item_id)
                for parcel in parcels
            )
            splits.append((titles.get(item_id, f"Позиция #{item_id}"), qtys))
        total_goods = _quantize_eur(
            sum((parcel.goods_eur for parcel in parcels), Decimal("0.00"))
        )
        can_apply = block is None
        apply_block = block
        paid_n_blocked = False
        needed = len(placed) + len(parcels)
        if can_apply and order.payment_paid_at is not None:
            if paid_count is None or needed > paid_count:
                can_apply = False
                paid_n_blocked = True
                shown_paid = paid_count if paid_count is not None else 0
                apply_block = (
                    f"Для текущего состава требуется {needed} посылок, "
                    f"но оплачено только {shown_paid}."
                )
        if can_apply and not parcels and not drafts:
            can_apply = False
            apply_block = "Нечего распределять"
        return PackingRecommendation(
            parcels=tuple(parcels),
            splits=tuple(splits),
            can_apply=can_apply,
            block_reason=apply_block,
            replaces_drafts=bool(drafts),
            goods_eur=total_goods,
            goods_cap_eur=cap,
            paid_count=paid_count,
            needed_count=needed,
            paid_n_blocked=paid_n_blocked,
        )

    # Заменяет только draft SO рекомендацией. Placed/cancelled не трогает.
    async def apply_packing_recommendation(
        self, order_id: int
    ) -> PackingRecommendation:
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if order is None:
                raise ValueError("Заказ не найден")
            preview = await self.packing_recommendation(order_id)
            if not preview.can_apply:
                raise SupplierOrderAllocationError(
                    preview.block_reason or "Рекомендацию нельзя применить"
                )
            headers = await self.order_crud.list_supplier_orders_for_order(order_id)
            drafts = [
                header
                for header in headers
                if str(header.status) == SupplierOrderStatus.DRAFT
            ]
            placed = [
                header
                for header in headers
                if str(header.status) == SupplierOrderStatus.PLACED
            ]
            items = await self.order_crud.get_order_items(order_id)
            ordered = {item.id: int(item.quantity or 0) for item in items}
            placed_lines = await self.order_crud.list_supplier_order_lines_for_ids(
                [header.id for header in placed]
            )
            existing = [
                (line.order_item_id, int(line.quantity)) for line in placed_lines
            ]
            for header in drafts:
                await self.session.delete(header)
            await self.session.flush()
            remaining_headers = [
                header
                for header in headers
                if str(header.status) != SupplierOrderStatus.DRAFT
            ]
            next_seq = max((header.seq for header in remaining_headers), default=0)
            created_ids: list[int] = []
            for parcel in preview.parcels:
                validate_proposed_supplier_order(ordered, existing, list(parcel.lines))
                next_seq += 1
                header = SupplierOrder(
                    order_id=order.id,
                    seq=next_seq,
                    status=SupplierOrderStatus.DRAFT,
                    goods_eur=parcel.goods_eur,
                    supplier_shipping_eur=supplier_shipping_snapshot_eur(),
                )
                self.session.add(header)
                await self.session.flush()
                for item_id, qty, unit in parcel.lines:
                    self.session.add(
                        SupplierOrderLine(
                            supplier_order_id=header.id,
                            order_item_id=item_id,
                            quantity=qty,
                            unit_supplier_eur=unit,
                        )
                    )
                existing = existing + [
                    (item_id, qty) for item_id, qty, _u in parcel.lines
                ]
                created_ids.append(header.id)
            await self.session.flush()
            await self.sync_unpaid_client_delivery(order)
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="supplier_order_recommendation_applied",
                event_message="Рекомендация сборки посылок применена",
                created_by="admin",
                payload_json={
                    "parcels": len(preview.parcels),
                    "supplier_order_ids": created_ids,
                },
            )
            await self.session.commit()
            return preview
        except Exception:
            await self.session.rollback()
            raise

    # Ручной place: TP number → placed + зеркало первого SO + assembling.
    async def place_draft(
        self,
        order_id: int,
        supplier_order_id: int,
        external_id: str,
        *,
        notify_customer: bool = False,
        custom_message: str | None = None,
        actor: User | None = None,
    ) -> SupplierOrder:
        try:
            order = await self.order_crud.get_by_id_for_update(order_id)
            if order is None:
                raise ValueError("Заказ не найден")
            latest = await self.order_crud.get_latest_payment_attempt(order_id)
            block = self._packing_block_reason(order, latest)
            if block:
                raise SupplierOrderAllocationError(block)
            tp_id = normalize_legacy_supplier_order_id(external_id)
            if tp_id is None:
                raise SupplierOrderAllocationError("Укажите номер заказа у поставщика")
            if len(tp_id) > 128:
                raise SupplierOrderAllocationError(
                    "Номер заказа у поставщика слишком длинный"
                )
            headers = await self.order_crud.list_supplier_orders_for_order(order_id)
            header = next((row for row in headers if row.id == supplier_order_id), None)
            if header is None:
                raise ValueError("Заказ поставщика не найден")
            status = str(header.status or "")
            if status == SupplierOrderStatus.CANCELLED:
                raise SupplierOrderAllocationError(
                    "Отменённый заказ поставщика нельзя оформить"
                )
            if status == SupplierOrderStatus.PLACED:
                if normalize_legacy_supplier_order_id(header.external_id) == tp_id:
                    await self._ensure_shipment_for_placed(order.id, header.id)
                    await self.session.commit()
                    return header
                raise SupplierOrderAllocationError(
                    "Номер заказа у поставщика нельзя изменить"
                )
            if status != SupplierOrderStatus.DRAFT:
                raise SupplierOrderAllocationError(
                    "Оформить можно только черновик заказа поставщика"
                )
            taken = await self.order_crud.get_supplier_order_by_external_id(tp_id)
            if taken is not None and taken.id != header.id:
                raise SupplierOrderAllocationError(
                    "Этот номер заказа у поставщика уже использован"
                )
            items = await self.order_crud.get_order_items(order_id)
            ordered = {item.id: int(item.quantity or 0) for item in items}
            current_lines = await self.order_crud.list_supplier_order_lines_for_ids(
                [header.id]
            )
            if not current_lines:
                raise SupplierOrderAllocationError(
                    "Нельзя оформить пустой заказ поставщика"
                )
            other_ids = [
                row.id for row in self._active_headers(headers) if row.id != header.id
            ]
            other_lines = await self.order_crud.list_supplier_order_lines_for_ids(
                other_ids
            )
            existing = [
                (line.order_item_id, int(line.quantity)) for line in other_lines
            ]
            proposed = [
                (
                    int(line.order_item_id),
                    int(line.quantity),
                    _quantize_eur(Decimal(str(line.unit_supplier_eur or 0))),
                )
                for line in current_lines
            ]
            validate_proposed_supplier_order(ordered, existing, proposed)
            placed_before = [
                row
                for row in self._active_headers(headers)
                if str(row.status) == SupplierOrderStatus.PLACED
            ]
            is_first_place = len(placed_before) == 0
            current_mirror = normalize_legacy_supplier_order_id(order.supplier_order_id)
            if is_first_place and current_mirror and current_mirror != tp_id:
                raise SupplierOrderAllocationError(
                    "У заказа уже есть другой номер у поставщика"
                )
            header.status = SupplierOrderStatus.PLACED
            header.external_id = tp_id
            header.placed_at = utc_now_naive()
            header.placed_by = "admin"
            header.goods_eur = goods_eur_from_lines(
                [(qty, unit) for _item_id, qty, unit in proposed]
            )
            self.session.add(header)
            await self.session.flush()
            order_service = None
            if is_first_place:
                # Circular: OrderService imports SupplierOrderService at module load.
                from src.services.orders.order_service import OrderService

                order_service = OrderService(self.session)
                await order_service.apply_assembling_after_first_place(order, tp_id)
            await self._ensure_shipment_for_placed(order.id, header.id)
            await self.order_crud.create_order_event(
                order_id=order.id,
                event_type="supplier_order_placed",
                event_message=f"Заказ поставщика #{header.seq} оформлен",
                created_by="admin",
                payload_json={
                    "supplier_order_id": header.id,
                    "seq": header.seq,
                    "external_id": tp_id,
                },
            )
            await self.session.commit()
            await self.session.refresh(header)
            if notify_customer:
                await self._enqueue_assembly_parcel_notify(
                    order,
                    header,
                    custom_message,
                    actor,
                )
            return header
        except SupplierOrderAllocationError:
            await self.session.rollback()
            raise
        except IntegrityError:
            await self.session.rollback()
            raise SupplierOrderAllocationError(
                "Этот номер заказа у поставщика уже использован"
            )
        except Exception:
            await self.session.rollback()
            raise

    # Ставит packing-notify в outbox по SO. Повтор с тем же ключом — no-op.
    async def _enqueue_assembly_parcel_notify(
        self,
        order: Order,
        header: SupplierOrder,
        custom_message: str | None,
        actor: User | None,
    ) -> bool:
        views = await self.list_for_order(order.id)
        parcel_count = assembly_parcel_count(views)
        text = render_assembly_parcel_message(
            custom_message,
            order.id,
            int(header.seq),
            parcel_count,
        )
        from src.services.orders.order_service import OrderService

        created_by = await OrderService(self.session)._build_admin_created_by(
            None, actor
        )
        ok = await CustomerNotificationService(self.session).notify_order_status(
            order_id=order.id,
            custom_message=text,
            created_by=created_by,
            idempotency_key=assembly_parcel_notify_key(order.id, header.id),
        )
        if ok:
            await self.session.commit()
        return ok

    # Догон packing-notify для уже оформленной посылки.
    async def notify_placed_parcel(
        self,
        order_id: int,
        supplier_order_id: int,
        custom_message: str | None,
        actor: User | None = None,
    ) -> bool:
        order = await self.order_crud.get_by_id(order_id)
        if order is None:
            raise ValueError("Заказ не найден")
        headers = await self.order_crud.list_supplier_orders_for_order(order_id)
        header = next((row for row in headers if row.id == supplier_order_id), None)
        if header is None or int(header.order_id) != int(order_id):
            raise ValueError("Заказ поставщика не найден")
        if str(header.status) != SupplierOrderStatus.PLACED:
            raise ValueError("Уведомить можно только оформленную посылку")
        return await self._enqueue_assembly_parcel_notify(
            order, header, custom_message, actor
        )

    # Shipment в той же транзакции, что place; без вложенного commit.
    async def _ensure_shipment_for_placed(
        self, order_id: int, supplier_order_id: int
    ) -> None:
        from src.services.orders.shipments import ShipmentService

        await ShipmentService(self.session).create_from_placed_supplier_order(
            order_id, supplier_order_id, commit=False
        )

    # Идемпотентный backfill: legacy supplier_order_id → один placed SO seq=1.
    async def backfill_legacy(
        self,
        now: datetime | None = None,
        order_id: int | None = None,
    ) -> SupplierOrderBackfillStats:
        check_at = now or utc_now_naive()
        shipping = supplier_shipping_snapshot_eur()
        orders = await self.order_crud.list_orders_with_legacy_supplier_id(order_id)
        existing = await self.order_crud.order_ids_with_supplier_orders(
            [order.id for order in orders]
        )
        created_orders = 0
        created_lines = 0
        skipped = 0
        for order in orders:
            if order.id in existing:
                skipped += 1
                continue
            items = await self.order_crud.get_order_items(order.id)
            try:
                async with self.session.begin_nested():
                    added = await self._backfill_one_order(
                        order, items, shipping=shipping, now=check_at
                    )
            except IntegrityError:
                skipped += 1
                continue
            if added is None:
                skipped += 1
                continue
            created_orders += 1
            created_lines += added
            existing.add(order.id)
        await self.session.commit()
        return SupplierOrderBackfillStats(
            scanned=len(orders),
            created_orders=created_orders,
            created_lines=created_lines,
            skipped=skipped,
        )

    # Создаёт один placed SO на полный состав OrderItem; None если нечего зеркалировать.
    async def _backfill_one_order(
        self,
        order: Order,
        items: list[OrderItem],
        shipping: Decimal,
        now: datetime,
    ) -> int | None:
        external_id = normalize_legacy_supplier_order_id(order.supplier_order_id)
        if external_id is None:
            return None
        line_specs: list[tuple[OrderItem, int, Decimal]] = []
        for item in items:
            qty = int(item.quantity or 0)
            if qty <= 0:
                continue
            unit = _quantize_eur(Decimal(str(item.supplier_price_eur_captured or 0)))
            line_specs.append((item, qty, unit))
        goods = goods_eur_from_lines([(qty, unit) for _, qty, unit in line_specs])
        header = SupplierOrder(
            order_id=order.id,
            seq=1,
            external_id=external_id,
            status=SupplierOrderStatus.PLACED,
            goods_eur=goods,
            supplier_shipping_eur=shipping,
            placed_at=now,
            placed_by=BACKFILL_PLACED_BY,
        )
        self.session.add(header)
        await self.session.flush()
        for item, qty, unit in line_specs:
            self.session.add(
                SupplierOrderLine(
                    supplier_order_id=header.id,
                    order_item_id=item.id,
                    quantity=qty,
                    unit_supplier_eur=unit,
                )
            )
        return len(line_specs)
