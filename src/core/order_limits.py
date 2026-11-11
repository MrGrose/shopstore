from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Protocol

from src.core.config import settings
from src.schemas.money import ceil_rub

_EUR_CENTS = Decimal("0.01")


# Ошибка раскладки заказа поставщика. Текст для клиента админки не менять.
class SupplierOrderAllocationError(ValueError):
    pass


# Протокол для элемента корзины.
class CartCostItem(Protocol):
    product_id: int
    quantity: int


# Протокол для товара с закупочной ценой.
class SupplierPricedProduct(Protocol):
    supplier_price_eur: float | Decimal | None


# Протокол для оценки заказа поставщика.
@dataclass(frozen=True)
class SupplierOrderEstimate:
    goods_cost_eur: Decimal
    max_goods_eur: Decimal
    minimum_orders: int
    supplier_shipping_eur: Decimal
    client_shipping_eur: Decimal


# Округляет сумму EUR до центов.
def _quantize_eur(value: Decimal) -> Decimal:
    return value.quantize(_EUR_CENTS, rounding=ROUND_HALF_UP)


# Возвращает максимум товаров в одном заказе Supplier-Demo.
def max_supplier_goods_eur() -> Decimal:
    return _quantize_eur(
        Decimal(str(settings.SUPPLIER_ORDER_MAX_EUR))
        - Decimal(str(settings.SUPPLIER_ORDER_SHIPPING_EUR))
    )


# Проверяет, можно ли показывать товар с этой закупочной ценой на витрине.
def is_supplier_unit_storefront_allowed(
    supplier_price_eur: float | Decimal | None,
) -> bool:
    unit = _quantize_eur(Decimal(str(supplier_price_eur or 0)))
    return unit <= max_supplier_goods_eur()


# Сумма товаров в одной посылке-рекомендации.
def _parcel_goods(lines: Sequence[tuple[int, int, Decimal]]) -> Decimal:
    total = Decimal("0.00")
    for _item_id, quantity, unit in lines:
        total += Decimal(quantity) * _quantize_eur(unit)
    return _quantize_eur(total)


# Сколько штук влезает в остаток EUR.
def _qty_fit_in_room(room: Decimal, unit: Decimal, left: int) -> int:
    if int(left) <= 0:
        return 0
    if unit <= 0:
        return int(left)
    take = int((room / unit).to_integral_value(rounding=ROUND_FLOOR))
    return min(int(left), max(0, take))


# Добавляет qty в bin, сливая line того же OrderItem.
def _add_qty_to_bin(
    bin_lines: list[tuple[int, int, Decimal]],
    item_id: int,
    qty: int,
    unit: Decimal,
) -> None:
    for idx, (eid, eqty, eunit) in enumerate(bin_lines):
        if eid == item_id:
            bin_lines[idx] = (eid, eqty + qty, eunit)
            return
    bin_lines.append((item_id, qty, unit))


# First Fit: первый bin, куда влезает хотя бы 1 шт.
def _first_fit_bin(
    goods: Sequence[Decimal],
    unit: Decimal,
    limit: Decimal,
) -> int | None:
    for idx, current in enumerate(goods):
        if current + unit <= limit:
            return idx
    return None


# Пытается полностью перенести src-bin в другие. Детерминированно.
def _try_empty_bin(
    bins: list[list[tuple[int, int, Decimal]]],
    src: int,
    limit: Decimal,
) -> bool:
    if src < 0 or src >= len(bins) or len(bins) <= 1:
        return False
    src_lines = sorted(bins[src], key=lambda row: (-row[2], -row[1], row[0]))
    tentative = [list(lines) for lines in bins]
    tentative[src] = []
    for item_id, qty, unit in src_lines:
        left = int(qty)
        while left > 0:
            candidates: list[tuple[Decimal, int]] = []
            for idx, lines in enumerate(tentative):
                if idx == src:
                    continue
                current = _parcel_goods(lines)
                if current + unit > limit:
                    continue
                room = limit - current
                candidates.append((room, idx))
            if not candidates:
                return False
            candidates.sort(key=lambda row: (row[0], row[1]))
            target = candidates[0][1]
            take = _qty_fit_in_room(
                limit - _parcel_goods(tentative[target]), unit, left
            )
            if take <= 0:
                return False
            _add_qty_to_bin(tentative[target], item_id, take, unit)
            left -= take
    bins[:] = [lines for idx, lines in enumerate(tentative) if idx != src]
    return True


# Убирает мелкие остаточные bin, пока есть полное перемещение.
def _improve_parcel_bins(
    bins: list[list[tuple[int, int, Decimal]]],
    limit: Decimal,
) -> list[list[tuple[int, int, Decimal]]]:
    packed = [list(lines) for lines in bins if lines]
    guard = 0
    while len(packed) > 1 and guard < 64:
        guard += 1
        goods = [_parcel_goods(lines) for lines in packed]
        order = sorted(range(len(packed)), key=lambda idx: (goods[idx], idx))
        moved = False
        for src in order:
            if _try_empty_bin(packed, src, limit):
                moved = True
                break
        if not moved:
            break
    return packed


# FFD по цене ед. + improvement pass. Не last-bin-only.
def recommend_draft_parcels(
    leftover_items: Sequence[tuple[int, int, Decimal]],
    cap: Decimal | None = None,
) -> list[list[tuple[int, int, Decimal]]]:
    limit = _quantize_eur(Decimal(str(cap or max_supplier_goods_eur())))
    pending = [
        (int(item_id), int(qty), _quantize_eur(Decimal(str(unit or 0))))
        for item_id, qty, unit in leftover_items
        if int(qty) > 0
    ]
    pending.sort(key=lambda row: (-row[2], -(Decimal(row[1]) * row[2]), row[0]))
    for _item_id, _qty, unit in pending:
        if unit > limit:
            raise SupplierOrderAllocationError("Товар дороже лимита одной посылки")
    bins: list[list[tuple[int, int, Decimal]]] = []
    goods: list[Decimal] = []
    for item_id, qty, unit in pending:
        left = qty
        while left > 0:
            target = _first_fit_bin(goods, unit, limit)
            if target is None:
                bins.append([])
                goods.append(Decimal("0.00"))
                target = len(bins) - 1
            take = _qty_fit_in_room(limit - goods[target], unit, left)
            if take <= 0:
                bins.append([])
                goods.append(Decimal("0.00"))
                continue
            _add_qty_to_bin(bins[target], item_id, take, unit)
            goods[target] = _quantize_eur(goods[target] + Decimal(take) * unit)
            left -= take
    return _improve_parcel_bins(bins, limit)


# Число посылок тем же пакером. Bins не сохраняет.
def required_parcel_count(
    lines: Sequence[tuple[int, int, Decimal]],
) -> int:
    return len(recommend_draft_parcels(lines))


# Считает теоретический минимум заказов Supplier-Demo и обе доставки.
# Пустая корзина — N=0; позиции с нулевой закупкой всё равно один заказ.
def estimate_supplier_orders(
    goods_cost_eur: Decimal,
    client_delivery_base_eur: Decimal,
    item_count: int = 0,
    *,
    supplier_lines: Sequence[tuple[int, int, Decimal]] | None = None,
) -> SupplierOrderEstimate:
    goods = _quantize_eur(Decimal(str(goods_cost_eur)))
    if goods < 0:
        goods = Decimal("0.00")
    max_goods = max_supplier_goods_eur()
    base = _quantize_eur(Decimal(str(client_delivery_base_eur)))
    if base < 0:
        base = Decimal("0.00")
    if supplier_lines:
        minimum_orders = required_parcel_count(supplier_lines)
    elif goods <= 0 and item_count <= 0:
        return SupplierOrderEstimate(
            goods_cost_eur=goods,
            max_goods_eur=max_goods,
            minimum_orders=0,
            supplier_shipping_eur=Decimal("0.00"),
            client_shipping_eur=Decimal("0.00"),
        )
    elif goods <= 0:
        minimum_orders = 1
    else:
        minimum_orders = int(
            (goods / max_goods).to_integral_value(rounding=ROUND_CEILING)
        )
    n = Decimal(minimum_orders)
    return SupplierOrderEstimate(
        goods_cost_eur=goods,
        max_goods_eur=max_goods,
        minimum_orders=minimum_orders,
        supplier_shipping_eur=_quantize_eur(
            n * Decimal(str(settings.SUPPLIER_ORDER_SHIPPING_EUR))
        ),
        client_shipping_eur=_quantize_eur(n * base),
    )


# Линии корзины и checkout для N: live-цена, пропуск отсутствующего товара.
def live_supplier_lines(
    items: Sequence[CartCostItem],
    products_map: Mapping[int, SupplierPricedProduct],
) -> list[tuple[int, int, Decimal]] | None:
    lines: list[tuple[int, int, Decimal]] = []
    next_id = 1
    for item in items:
        product = products_map.get(item.product_id)
        if product is None:
            continue
        qty = int(item.quantity)
        if qty <= 0:
            continue
        lines.append((next_id, qty, Decimal(str(product.supplier_price_eur or 0))))
        next_id += 1
    return lines or None


# Рассчитывает общую себестоимость заказа в евро.
def calculate_supplier_cost_eur(
    items: Sequence[CartCostItem],
    products_map: Mapping[int, SupplierPricedProduct],
) -> Decimal:
    total = Decimal("0")
    for item in items:
        product = products_map.get(item.product_id)
        if product is None:
            continue
        unit = Decimal(str(product.supplier_price_eur or 0))
        total += unit * int(item.quantity)
    return total


# Форматирует сумму в рублях для клиентских сообщений.
def format_rub_amount(amount: Decimal) -> str:
    value = int(ceil_rub(amount) or 0)
    return f"{value:,}".replace(",", " ") + " ₽"


# Форматирует EUR-порог в рублях для клиентских сообщений.
def format_eur_limit_rub(limit_eur: Decimal | int, eur_rate: Decimal) -> str:
    return format_rub_amount(Decimal(str(limit_eur)) * eur_rate)


# Рассчитывает налог на добавленную стоимость (НДС) в рублях.
def calculate_customs_duty_rub(
    supplier_cost_eur: Decimal,
    eur_rate: Decimal,
    duty_free_eur: Decimal | None = None,
    duty_rate: Decimal | None = None,
) -> Decimal:
    # Определяет порог безналогового ввоза.
    threshold = (
        duty_free_eur
        if duty_free_eur is not None
        else Decimal(str(settings.CUSTOMS_DUTY_FREE_EUR))
    )
    # Определяет ставку налога.
    rate = (
        duty_rate if duty_rate is not None else Decimal(str(settings.CUSTOMS_DUTY_RATE))
    )
    # Если себестоимость заказа меньше порога безналогового ввоза, НДС не начисляется.
    if supplier_cost_eur <= threshold:
        return Decimal("0")
    # Рассчитывает налогооблагаемую базу.
    taxable = supplier_cost_eur - threshold
    # Рассчитывает НДС.
    raw = taxable * rate * eur_rate
    # Округляет НДС до рублей.
    return ceil_rub(raw) or Decimal("0")


# Форматирует текст таможенного платежа на checkout.
def customs_duty_notice(customs_duty_amount: Decimal, eur_rate: Decimal) -> str | None:
    if customs_duty_amount <= 0:
        return None
    limit_rub = format_eur_limit_rub(settings.CUSTOMS_DUTY_FREE_EUR, eur_rate)
    return settings.CUSTOMS_DUTY_NOTICE.format(
        amount=format_rub_amount(customs_duty_amount),
        limit=limit_rub,
    )
