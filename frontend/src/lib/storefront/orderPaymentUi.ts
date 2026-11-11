export type PaymentState =
  | "paid"
  | "waiting"
  | "failed"
  | "initializing"
  | "not_started"
  | "exhausted"
  | "late_paid_after_cancel";

export type OrderPaymentLike = {
  id?: number;
  payment_allowed?: boolean;
  payment_paid_at?: string | null;
  payment_status?: string | null;
  payment_state?: PaymentState;
  payment_paid_at_short_display?: string | null;
  payment_due_at_display?: string | null;
  availability_confirmation_status?: string;
  status?: string;
  late_payment_after_auto_cancel?: boolean;
  payment_attempts_exhausted?: boolean;
  payment_attempts_limit?: number;
};

export type OrderPaymentUiState =
  | { kind: "paid" }
  | { kind: "pending" }
  | { kind: "continue_pay" }
  | { kind: "pay_again" }
  | { kind: "pay" }
  | { kind: "gateway_unavailable" }
  | { kind: "exhausted" }
  | { kind: "late_paid_after_cancel" }
  | { kind: "none" };

export type CheckoutPostSubmitAction =
  | { action: "open_payment" }
  | { action: "show_pending"; orderId: number }
  | { action: "show_gateway_unavailable"; orderId: number }
  | { action: "go_orders" };

export function isOrderPaid(order: OrderPaymentLike): boolean {
  if (order.payment_state === "paid") return true;
  if (order.payment_state) return false;
  if (order.payment_paid_at) return true;
  const status = String(order.payment_status || "").toUpperCase();
  return ["IPS_ACCEPTED", "CHARGED", "AUTHORIZED"].includes(status);
}

export function isAvailabilityPending(order: OrderPaymentLike): boolean {
  return String(order.availability_confirmation_status || "").toLowerCase() === "pending";
}

export function resolveOrderPaymentUiState(
  order: OrderPaymentLike,
  paymentGatewayEnabled = true,
): OrderPaymentUiState {
  if (
    order.late_payment_after_auto_cancel ||
    order.payment_state === "late_paid_after_cancel"
  ) {
    return { kind: "late_paid_after_cancel" };
  }
  if (isOrderPaid(order)) return { kind: "paid" };
  const status = String(order.status || "").toLowerCase();
  if (["cancelled", "failed", "completed"].includes(status)) return { kind: "none" };
  if (isAvailabilityPending(order)) return { kind: "pending" };
  if (order.payment_attempts_exhausted || order.payment_state === "exhausted") {
    return { kind: "exhausted" };
  }
  if (order.payment_allowed === false) return { kind: "none" };
  if (!paymentGatewayEnabled) return { kind: "gateway_unavailable" };
  if (order.payment_state === "waiting") return { kind: "continue_pay" };
  if (order.payment_state === "initializing") return { kind: "continue_pay" };
  if (order.payment_state === "failed") return { kind: "pay_again" };
  return { kind: "pay" };
}

export function resolveCheckoutPostSubmitAction(
  order: OrderPaymentLike & { id: number; payment_gateway_enabled?: boolean },
): CheckoutPostSubmitAction {
  const gatewayEnabled = order.payment_gateway_enabled !== false;
  if (!gatewayEnabled && order.payment_allowed) {
    return { action: "show_gateway_unavailable", orderId: order.id };
  }
  if (isAvailabilityPending(order)) {
    return { action: "show_pending", orderId: order.id };
  }
  if (order.payment_allowed) {
    return { action: "open_payment" };
  }
  return { action: "go_orders" };
}

export const ORDER_PAYMENT_PENDING_LABEL = "Проверяем наличие";
export const ORDER_PAYMENT_PENDING_HEADLINE = "Проверяем наличие.";
export const ORDER_PAYMENT_PENDING_SUBTEXT = "Оплата станет доступна после проверки.";
export const ORDER_PAYMENT_PENDING_TEXT = `${ORDER_PAYMENT_PENDING_HEADLINE} ${ORDER_PAYMENT_PENDING_SUBTEXT}`;

export const ORDER_PAYMENT_GATEWAY_UNAVAILABLE_TEXT = "Оплата временно недоступна";

export const ORDER_PAYMENT_CONTINUE_TEXT = "Продолжить оплату";
export const ORDER_PAYMENT_PAY_TEXT = "Оплатить";
export const ORDER_PAYMENT_PAY_AGAIN_TEXT = "Повторить оплату";

export const ORDER_PAYMENT_EXHAUSTED_TEXT = "Лимит попыток исчерпан";

export function orderPaymentExhaustedText(_limit = 5): string {
  return ORDER_PAYMENT_EXHAUSTED_TEXT;
}

export const ORDER_PAYMENT_LATE_AFTER_CANCEL_TEXT = "Заказ проходит проверку.";

export const ORDER_CANCEL_BLOCKED_PAYMENT_TEXT =
  "Сейчас идёт оплата. Отменить можно после истечения QR-кода или если оплата не пройдёт.";

export const ORDER_CANCEL_CONFIRM_TEXT =
  "Отменить заказ? После отмены его нельзя будет оплатить.";

export const ORDER_CANCEL_BUTTON_TEXT = "Отменить заказ";

export function formatPaymentDueDisplay(value?: string | null): string {
  return String(value || "").replace(/\s+мск$/u, "").trim();
}
