import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronRight,
  Clock,
  Package,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { userFacingApiErrorMessage } from "../../lib/errorMessages";
import { storefrontApiFetch } from "../../lib/storefront/api";
import { resolveLineItemThumbUrl } from "../../lib/storefront/imageResolver";
import { moneyRub, cartItemTitle, variantOptionParts } from "../../lib/storefront/checkoutUi";
import { PaymentDialog } from "./PaymentDialog";
import { OrderPaymentActions } from "./OrderPaymentActions";
import { OrderTrackingDialog } from "./OrderTrackingDialog";
import { PaymentStateBadge } from "./PaymentStateBadge";
import {
  formatPaymentDueDisplay,
  isAvailabilityPending,
  ORDER_CANCEL_BLOCKED_PAYMENT_TEXT,
  ORDER_CANCEL_BUTTON_TEXT,
  ORDER_CANCEL_CONFIRM_TEXT,
  ORDER_PAYMENT_PENDING_LABEL,
  type PaymentState,
} from "../../lib/storefront/orderPaymentUi";

export type OrderItem = {
  id?: number | null;
  product_id: number;
  variant_id?: number | null;
  quantity: number;
  unit_price: number | string;
  product_title?: string | null;
  display_title?: string | null;
  category_l2?: string | null;
  category_l3?: string | null;
  category_l2_label_ru?: string | null;
  category_l3_label_ru?: string | null;
  product_image_url?: string | null;
  variant_option1?: string | null;
  variant_option2?: string | null;
  variant_option3?: string | null;
  variant_option1_ru?: string | null;
  variant_option2_ru?: string | null;
  variant_option3_ru?: string | null;
};


/** L2 RU label for LK order lines; L3 is ignored. */
export function orderItemL2LabelRu(item: {
  category_l2_label_ru?: string | null;
  category_l3_label_ru?: string | null;
}): string | null {
  const label = String(item.category_l2_label_ru ?? "").trim();
  return label || null;
}

export type OrderShipmentTrackingLink = {
  carrier: string;
  url: string;
};

export type OrderShipmentTracking = {
  carrier: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  links?: OrderShipmentTrackingLink[];
};

export type OrderShipmentItem = {
  order_item_id: number;
  quantity: number;
  product_title?: string | null;
  display_title?: string | null;
  product_image_url?: string | null;
  category_l2?: string | null;
  category_l3?: string | null;
  category_l2_label_ru?: string | null;
  category_l3_label_ru?: string | null;
};

export type OrderShipment = {
  id: number;
  seq: number;
  status: string;
  status_label: string;
  status_updated_at?: string | null;
  delivered_at?: string | null;
  supplier_tracking: OrderShipmentTracking;
  customer_tracking: OrderShipmentTracking;
  items?: OrderShipmentItem[];
};

export type Order = {
  id: number;
  status: string;
  status_label?: string | null;
  availability_confirmation_status?: string;
  availability_confirmation_status_label?: string | null;
  availability_message_ru?: string | null;
  payment_allowed?: boolean;
  payment_gateway_enabled?: boolean;
  total_amount: number | string;
  items_subtotal_amount?: number | string;
  discount_items_amount?: number | string;
  delivery_fee_amount?: number | string;
  promo_code_applied?: string | null;
  payment_status?: string | null;
  payment_state?: PaymentState;
  payment_label?: string | null;
  payment_method_label?: string | null;
  payment_paid_at?: string | null;
  payment_paid_at_short_display?: string | null;
  payment_due_at_display?: string | null;
  late_payment_after_auto_cancel?: boolean;
  payment_attempts_exhausted?: boolean;
  payment_attempts_limit?: number;
  customer_cancel_allowed?: boolean;
  customer_cancel_blocked_reason?: string | null;
  payment_redirect_url?: string | null;
  created_at_display?: string | null;
  created_at?: string | null;
  items?: OrderItem[];
  supplier_order_id?: string | null;
  shipments?: OrderShipment[];
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  created: "Ожидает оплаты",
  processing: "Проверяем наличие",
  assembling: "Готовится к отправке",
  delivery: "В пути",
  completed: "Доставлен",
  cancelled: "Отменен",
  failed: "Ошибка",
};

export function formatOrderStatus(status: string) {
  const key = String(status || "").toLowerCase();
  return ORDER_STATUS_LABELS[key] || status || "-";
}

export function getOrderStatusLabel(o: Order) {
  return o.status_label || formatOrderStatus(o.status);
}

const LEGACY_TRACKING_STATUSES = ["assembling", "delivery", "completed"];

export function canOpenTracking(
  order: Pick<Order, "shipments" | "supplier_order_id" | "status">,
): boolean {
  if ((order.shipments?.length ?? 0) > 0) return true;
  return (
    Boolean(order.supplier_order_id) &&
    LEGACY_TRACKING_STATUSES.includes(order.status)
  );
}

export function formatOrderDateTime(o: Order) {
  if (o.created_at_display) {
    return o.created_at_display.replace(/\s+мск$/u, "");
  }
  const raw = String(o.created_at || "").trim();
  if (!raw) return "—";
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw.includes("T") ? `${raw}Z` : raw;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatPaymentLine(o: Order): string {
  const label = isAvailabilityPending(o)
    ? ORDER_PAYMENT_PENDING_LABEL
    : o.payment_label || "Можно оплатить";
  const parts = [label];
  if (o.payment_method_label) parts.push(o.payment_method_label);
  if (o.payment_state === "paid" && o.payment_paid_at_short_display) {
    parts.push(o.payment_paid_at_short_display);
  }
  return parts.join(" · ");
}

const STATUS_STYLE: Record<
  string,
  { label: string; color: string; bg: string; Icon: LucideIcon }
> = {
  completed: { label: "Доставлен", color: "#30D158", bg: "rgba(48,209,88,0.1)", Icon: CheckCircle2 },
  delivery: { label: "В пути", color: "#2997FF", bg: "rgba(41,151,255,0.1)", Icon: Truck },
  assembling: { label: "Готовится к отправке", color: "#AF52DE", bg: "rgba(175,82,222,0.1)", Icon: Package },
  processing: { label: "Проверяем наличие", color: "#FF9F0A", bg: "rgba(255,159,10,0.1)", Icon: Clock },
  created: { label: "Ожидает оплаты", color: "#FF9F0A", bg: "rgba(255,159,10,0.1)", Icon: Clock },
  cancelled: { label: "Отменён", color: "#86868B", bg: "rgba(134,134,139,0.1)", Icon: Clock },
  failed: { label: "Ошибка", color: "#86868B", bg: "rgba(134,134,139,0.1)", Icon: Clock },
};

function orderStatusStyle(status: string) {
  const key = String(status || "").toLowerCase();
  return (
    STATUS_STYLE[key] ?? {
      label: formatOrderStatus(status),
      color: "#86868B",
      bg: "rgba(134,134,139,0.1)",
      Icon: Clock,
    }
  );
}

function orderItemsSummary(o: Order) {
  const items = o.items || [];
  if (!items.length) return `Заказ #${o.id}`;
  return items.map((it) => cartItemTitle(it)).join(", ");
}

type Props = {
  pageSize?: number;
  className?: string;
  variant?: "drawer" | "account";
  paginated?: boolean;
};

export function OrdersList({
  pageSize: pageSizeProp,
  className,
  variant = "drawer",
  paginated = false,
}: Props) {
  const pageSize = pageSizeProp ?? (variant === "account" ? 10 : 50);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [ordersError, setOrdersError] = useState<string | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [activeOrderId, setActiveOrderId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [paymentOrder, setPaymentOrder] = useState<Order | null>(null);
  const [cancellingOrderId, setCancellingOrderId] = useState<number | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [trackingOrder, setTrackingOrder] = useState<Order | null>(null);

  const loadOrders = useCallback(
    async (targetPage: number, append: boolean) => {
      if (append) {
        setLoadingMore(true);
      } else {
        setOrdersLoading(true);
        setOrdersError(null);
      }
      try {
        const qs = new URLSearchParams({
          page: String(targetPage),
          page_size: String(pageSize),
        });
        const data = await storefrontApiFetch<Order[]>(`/orders/my?${qs.toString()}`);
        const list = Array.isArray(data) ? data : [];
        setHasMore(paginated && list.length === pageSize);
        if (append) {
          setOrders((prev) => [...prev, ...list]);
        } else {
          setOrders(list);
          setActiveOrderId(null);
        }
      } catch (e) {
        setOrdersError(userFacingApiErrorMessage(e, "Не удалось загрузить заказы"));
      } finally {
        setOrdersLoading(false);
        setLoadingMore(false);
      }
    },
    [pageSize, paginated],
  );

  const refreshOrders = useCallback(async () => {
    setPage(1);
    await loadOrders(1, false);
  }, [loadOrders]);

  const cancelOrder = useCallback(
    async (orderId: number) => {
      if (!window.confirm(ORDER_CANCEL_CONFIRM_TEXT)) {
        return;
      }
      setCancellingOrderId(orderId);
      setCancelError(null);
      try {
        await storefrontApiFetch<Order>(`/orders/${orderId}/cancel`, {
          method: "POST",
        });
        await refreshOrders();
      } catch (e) {
        setCancelError(userFacingApiErrorMessage(e, "Не удалось отменить заказ"));
      } finally {
        setCancellingOrderId(null);
      }
    },
    [refreshOrders],
  );

  useEffect(() => {
    if (paginated) {
      void loadOrders(page, page > 1);
      return;
    }
    void loadOrders(1, false);
  }, [paginated, page, loadOrders]);

  return (
    <div className={`w-full min-w-0 overflow-x-hidden ${className ?? ""}`}>
      {!paginated ? (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.75rem" }}>
          <button
            type="button"
            onClick={() => void refreshOrders()}
            disabled={ordersLoading}
            className="text-[12px] px-3 py-1.5 rounded-full border border-sp-border text-sp-text-secondary hover:text-sp-text-primary sp-transition"
            style={{ opacity: ordersLoading ? 0.6 : 1 }}
          >
            Обновить
          </button>
        </div>
      ) : null}

      {ordersLoading ? (
        <div className="text-sp-text-secondary">Загрузка…</div>
      ) : ordersError ? (
        <div style={{ color: "#ff8b8b" }}>{ordersError}</div>
      ) : orders.length === 0 ? (
        <div
          className={variant === "account" ? "text-center py-20" : ""}
          style={{ color: "var(--sp-text-muted)" }}
        >
          Заказов пока нет.
        </div>
      ) : (
        <div style={{ display: "grid", gap: variant === "account" ? "0.75rem" : "0.75rem" }}>
          {cancelError ? (
            <div style={{ color: "#ff8b8b", fontSize: "13px" }}>{cancelError}</div>
          ) : null}
          {orders.map((o) => {
            const open = activeOrderId === o.id;
            const hasDiscount = Number(o.discount_items_amount || 0) > 0;
            const availabilityMessage = String(o.availability_message_ru || "").trim();
            const showAvailabilityMessage =
              availabilityMessage && !isAvailabilityPending(o);
            const statusCfg = orderStatusStyle(o.status);
            const StatusIcon = statusCfg.Icon;
            return (
              <div
                key={o.id}
                className={variant === "account" ? "sp-transition" : ""}
                style={{
                  border: "1px solid var(--sp-border)",
                  background: variant === "account" ? "var(--sp-surface)" : "var(--sp-bg)",
                  borderRadius: variant === "account" ? "18px" : undefined,
                  overflow: variant === "account" ? "hidden" : undefined,
                }}
              >
                <button
                  type="button"
                  onClick={() => setActiveOrderId(open ? null : o.id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--sp-text-primary)",
                    padding: variant === "account" ? "1.25rem 1.5rem" : "0.9rem",
                    display: "flex",
                    justifyContent: "space-between",
                    gap: "1rem",
                    alignItems: variant === "account" ? "center" : undefined,
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    {variant === "account" ? (
                      <>
                        <div className="flex items-center gap-3 mb-1 flex-wrap">
                          <span className="text-[13px] font-semibold">#{o.id}</span>
                          <span className="text-[13px]" style={{ color: "var(--sp-text-muted)" }}>
                            {formatOrderDateTime(o)}
                          </span>
                          <span
                            className="flex items-center gap-1 px-2.5 py-0.5 text-[12px] font-medium"
                            style={{
                              background: statusCfg.bg,
                              color: statusCfg.color,
                              borderRadius: "999px",
                            }}
                          >
                            <StatusIcon size={11} />
                            {getOrderStatusLabel(o)}
                          </span>
                          <PaymentStateBadge state={o.payment_state} label={o.payment_label} />
                        </div>
                        <p className="text-[14px] truncate m-0" style={{ color: "var(--sp-text-secondary)" }}>
                          {orderItemsSummary(o)}
                        </p>
                        {o.payment_due_at_display && o.payment_allowed ? (
                          <p
                            className="text-[12px] m-0 mt-1"
                            style={{ color: "var(--sp-text-muted)" }}
                          >
                            Оплатить до {formatPaymentDueDisplay(o.payment_due_at_display)}
                          </p>
                        ) : null}
                      </>
                    ) : (
                      <>
                        <div className="font-semibold">Заказ #{o.id}</div>
                        <div className="text-sp-text-secondary text-[0.9rem]">
                          {getOrderStatusLabel(o)} · {formatOrderDateTime(o)}
                        </div>
                      </>
                    )}
                  </div>
                  <div style={{ textAlign: "right", display: "flex", alignItems: "center", gap: "0.75rem", flexShrink: 0 }}>
                    <div>
                      <div className="font-semibold" style={{ fontSize: variant === "account" ? "15px" : undefined }}>
                        {moneyRub(o.total_amount)}
                      </div>
                      {o.promo_code_applied ? (
                        <div style={{ color: "#9ae6b4", fontSize: "0.85rem" }}>
                          {o.promo_code_applied}
                        </div>
                      ) : null}
                    </div>
                    {variant === "account" ? (
                      <ChevronRight
                        size={18}
                        style={{
                          color: "var(--sp-text-muted)",
                          transform: open ? "rotate(90deg)" : "rotate(0deg)",
                          transition: "transform 0.2s",
                        }}
                      />
                    ) : null}
                  </div>
                </button>

                {open ? (
                  variant === "account" ? (
                    <div
                      className="px-6 pb-5"
                      style={{ borderTop: "1px solid var(--sp-border)" }}
                    >
                      <div className="pt-4 space-y-2">
                        {Array.isArray(o.items) && o.items.length ? (
                          o.items.map((it, idx) => {
                            const categoryLabel = orderItemL2LabelRu(it);
                            return (
                            <div
                              key={`${it.product_id}:${it.variant_id ?? ""}:${idx}`}
                              className="flex justify-between items-center gap-4"
                            >
                              <span className="min-w-0">
                                {categoryLabel ? (
                                  <span
                                    className="block text-[12px] leading-4"
                                    style={{ color: "var(--sp-text-muted)" }}
                                  >
                                    {categoryLabel}
                                  </span>
                                ) : null}
                                <span
                                  className="text-[14px] min-w-0 truncate block"
                                  style={{ color: "var(--sp-text-secondary)" }}
                                >
                                  {cartItemTitle(it)} × {it.quantity}
                                </span>
                              </span>
                              <span
                                className="text-[14px] font-medium shrink-0"
                                style={{ color: "var(--sp-text-primary)" }}
                              >
                                {moneyRub(Number(it.unit_price) * Number(it.quantity))}
                              </span>
                            </div>
                            );
                          })
                        ) : (
                          <p className="text-[14px] m-0" style={{ color: "var(--sp-text-muted)" }}>
                            Позиции заказа не загружены
                          </p>
                        )}

                        <div
                          className="space-y-2 pt-3 mt-2"
                          style={{ borderTop: "1px solid var(--sp-border)" }}
                        >
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Товары
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0"
                              style={{ color: "var(--sp-text-primary)" }}
                            >
                              {moneyRub(o.items_subtotal_amount || 0)}
                            </span>
                          </div>
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Скидка
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0"
                              style={{ color: hasDiscount ? "#30D158" : "var(--sp-text-primary)" }}
                            >
                              {hasDiscount ? `−${moneyRub(o.discount_items_amount || 0)}` : "0 ₽"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Доставка
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0"
                              style={{ color: "var(--sp-text-primary)" }}
                            >
                              {moneyRub(o.delivery_fee_amount || 0)}
                            </span>
                          </div>
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Промокод
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0"
                              style={{ color: o.promo_code_applied ? "#30D158" : "var(--sp-text-primary)" }}
                            >
                              {o.promo_code_applied || "—"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Оплата
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0 text-right"
                              style={{ color: "var(--sp-text-primary)" }}
                            >
                              {formatPaymentLine(o)}
                            </span>
                          </div>
                          <div className="flex justify-between items-center gap-4">
                            <span className="text-[14px]" style={{ color: "var(--sp-text-secondary)" }}>
                              Статус
                            </span>
                            <span
                              className="text-[14px] font-medium shrink-0"
                              style={{ color: "var(--sp-text-primary)" }}
                            >
                              {getOrderStatusLabel(o)}
                            </span>
                          </div>
                        </div>

                        <div
                          className="flex justify-between items-center pt-3 mt-2"
                          style={{ borderTop: "1px solid var(--sp-border)" }}
                        >
                          <span
                            className="text-[14px] font-semibold"
                            style={{ color: "var(--sp-text-primary)" }}
                          >
                            Итого
                          </span>
                          <span
                            className="text-[15px] font-semibold"
                            style={{ color: "var(--sp-text-primary)" }}
                          >
                            {moneyRub(o.total_amount)}
                          </span>
                        </div>

                        {showAvailabilityMessage ? (
                          <p
                            className="mt-3 m-0 text-[13px] leading-snug"
                            style={{ color: "var(--sp-text-secondary)" }}
                          >
                            {availabilityMessage}
                          </p>
                        ) : null}

                        <OrderPaymentActions
                          order={o}
                          paymentGatewayEnabled={o.payment_gateway_enabled !== false}
                          onPay={() => setPaymentOrder(o)}
                          inline={variant === "account"}
                          className={variant === "account" ? "mt-3" : "mt-3"}
                        />
                        {canOpenTracking(o) ? (
                          <button
                            type="button"
                            onClick={() => setTrackingOrder(o)}
                            className="mt-3 flex w-full items-center justify-center gap-2 rounded-full border border-sp-border px-4 py-3 text-[14px] font-medium text-sp-text-primary sp-transition hover:border-sp-blue hover:text-sp-blue"
                          >
                            <Truck size={16} /> Отследить товар
                          </button>
                        ) : null}
                        {o.customer_cancel_blocked_reason ? (
                          <p
                            className="mt-3 m-0 text-[13px] leading-snug"
                            style={{ color: "var(--sp-text-secondary)" }}
                          >
                            {o.customer_cancel_blocked_reason ||
                              ORDER_CANCEL_BLOCKED_PAYMENT_TEXT}
                          </p>
                        ) : null}
                        {o.customer_cancel_allowed ? (
                          <button
                            type="button"
                            disabled={cancellingOrderId === o.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void cancelOrder(o.id);
                            }}
                            className="mt-3 text-[13px] font-medium sp-transition disabled:opacity-50"
                            style={{
                              border: "1px solid var(--sp-border)",
                              borderRadius: "var(--sp-radius-pill)",
                              background: "transparent",
                              color: "var(--sp-text-secondary)",
                              padding: "0.65rem 1rem",
                              cursor: cancellingOrderId === o.id ? "not-allowed" : "pointer",
                            }}
                          >
                            {cancellingOrderId === o.id
                              ? "Отмена…"
                              : ORDER_CANCEL_BUTTON_TEXT}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        borderTop: "1px solid var(--sp-border)",
                        padding: "0.9rem",
                      }}
                    >
                      <div style={{ display: "grid", gap: "0.25rem", marginBottom: "0.75rem" }}>
                        <div className="text-sp-text-muted text-sm">
                          Товары: {moneyRub(o.items_subtotal_amount || 0)}
                        </div>
                        <div className="text-sp-text-muted text-sm">
                          Скидка: {hasDiscount ? `−${moneyRub(o.discount_items_amount || 0)}` : "0 ₽"}
                        </div>
                        <div className="text-sp-text-muted text-sm">
                          Доставка: {moneyRub(o.delivery_fee_amount || 0)}
                        </div>
                        <div className="text-sp-text-muted text-sm">
                          Промокод: {o.promo_code_applied || "—"}
                        </div>
                        <div className="text-sp-text-muted text-sm flex items-center gap-2 flex-wrap">
                          Оплата: <PaymentStateBadge state={o.payment_state} label={o.payment_label} />
                        </div>
                        <div className="text-sp-text-muted text-sm">
                          Статус: {getOrderStatusLabel(o)}
                        </div>
                        <div className="font-semibold">Сумма: {moneyRub(o.total_amount)}</div>
                        {showAvailabilityMessage ? (
                          <div className="text-sp-text-secondary text-sm">{availabilityMessage}</div>
                        ) : null}
                        <OrderPaymentActions
                          order={o}
                          paymentGatewayEnabled={o.payment_gateway_enabled !== false}
                          onPay={() => setPaymentOrder(o)}
                          className="mt-2"
                        />
                        {canOpenTracking(o) ? (
                          <button
                            type="button"
                            onClick={() => setTrackingOrder(o)}
                            className="mt-3 flex w-full items-center justify-center gap-2 rounded-full border border-sp-border px-4 py-3 text-sm font-medium text-sp-text-primary"
                          >
                            <Truck size={16} /> Отследить товар
                          </button>
                        ) : null}
                        {o.customer_cancel_blocked_reason ? (
                          <p className="mt-2 m-0 text-sp-text-secondary text-[13px] leading-snug">
                            {o.customer_cancel_blocked_reason ||
                              ORDER_CANCEL_BLOCKED_PAYMENT_TEXT}
                          </p>
                        ) : null}
                        {o.customer_cancel_allowed ? (
                          <button
                            type="button"
                            disabled={cancellingOrderId === o.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void cancelOrder(o.id);
                            }}
                            className="mt-2 text-[13px] font-medium sp-transition disabled:opacity-50 px-4 py-2 rounded-full border border-sp-border text-sp-text-secondary"
                          >
                            {cancellingOrderId === o.id
                              ? "Отмена…"
                              : ORDER_CANCEL_BUTTON_TEXT}
                          </button>
                        ) : null}
                      </div>

                      {Array.isArray(o.items) && o.items.length ? (
                        <div style={{ display: "grid", gap: "0.65rem" }}>
                          {o.items.map((it, idx) => {
                            const categoryLabel = orderItemL2LabelRu(it);
                            return (
                            <div
                              key={`${it.product_id}:${it.variant_id ?? ""}:${idx}`}
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: "1rem",
                              }}
                            >
                              <div style={{ display: "flex", gap: "0.75rem", minWidth: 0 }}>
                                {it.product_image_url ? (
                                  <img
                                    src={resolveLineItemThumbUrl(it.product_image_url) ?? ""}
                                    alt={cartItemTitle(it)}
                                    style={{
                                      width: 48,
                                      height: 60,
                                      objectFit: "cover",
                                      backgroundColor: "var(--sp-bg)",
                                    }}
                                  />
                                ) : (
                                  <div
                                    style={{
                                      width: 48,
                                      height: 60,
                                      backgroundColor: "var(--sp-bg)",
                                    }}
                                  />
                                )}
                                <div style={{ minWidth: 0 }}>
                                  {categoryLabel ? (
                                    <div className="text-[12px] text-sp-text-muted">
                                      {categoryLabel}
                                    </div>
                                  ) : null}
                                  <div className="font-semibold">{cartItemTitle(it)}</div>
                                  <div className="text-sp-text-secondary text-[0.85rem]">
                                    {variantOptionParts(it).join(" / ")}
                                  </div>
                                </div>
                              </div>
                              <div style={{ textAlign: "right", flexShrink: 0 }}>
                                <div>
                                  {it.quantity} × {moneyRub(it.unit_price)}
                                </div>
                              </div>
                            </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="text-sp-text-muted">Позиции заказа не загружены.</div>
                      )}
                    </div>
                  )
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {paginated && hasMore ? (
        <div className="flex justify-center mt-6">
          <button
            type="button"
            disabled={loadingMore || ordersLoading}
            onClick={() => setPage((p) => p + 1)}
            className="px-6 py-2.5 text-[14px] font-medium sp-transition disabled:opacity-50"
            style={{
              border: "1px solid var(--sp-border)",
              borderRadius: "var(--sp-radius-pill)",
              background: "var(--sp-surface)",
              color: "var(--sp-text-primary)",
            }}
          >
            {loadingMore ? "Загрузка…" : "Показать ещё"}
          </button>
        </div>
      ) : null}

      {paymentOrder ? (
        <PaymentDialog
          open
          orderId={paymentOrder.id}
          totalAmount={paymentOrder.total_amount}
          title={`Оплата заказа №${paymentOrder.id}`}
          onClose={() => setPaymentOrder(null)}
          onPaid={() => void refreshOrders()}
        />
      ) : null}
      {trackingOrder ? (
        <OrderTrackingDialog
          orderId={trackingOrder.id}
          shipments={trackingOrder.shipments ?? []}
          onClose={() => setTrackingOrder(null)}
        />
      ) : null}
    </div>
  );
}
