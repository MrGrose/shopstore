import { describe, expect, it } from "vitest";
import {
  formatPaymentDueDisplay,
  isOrderPaid,
  ORDER_PAYMENT_EXHAUSTED_TEXT,
  ORDER_PAYMENT_LATE_AFTER_CANCEL_TEXT,
  ORDER_PAYMENT_PAY_AGAIN_TEXT,
  ORDER_PAYMENT_PAY_TEXT,
  ORDER_PAYMENT_PENDING_LABEL,
  ORDER_PAYMENT_PENDING_HEADLINE,
  ORDER_PAYMENT_PENDING_SUBTEXT,
  orderPaymentExhaustedText,
  resolveCheckoutPostSubmitAction,
  resolveOrderPaymentUiState,
} from "./orderPaymentUi";
import { paymentStateBadgeLabel, paymentStateBadgeStyle } from "./paymentStateBadge";

describe("orderPaymentUi", () => {
  it("opens payment after checkout when allowed", () => {
    expect(
      resolveCheckoutPostSubmitAction({
        id: 7,
        payment_allowed: true,
        payment_gateway_enabled: true,
      }),
    ).toEqual({ action: "open_payment" });
  });

  it("shows pending dialog after checkout", () => {
    expect(
      resolveCheckoutPostSubmitAction({
        id: 8,
        payment_allowed: false,
        availability_confirmation_status: "pending",
      }),
    ).toEqual({ action: "show_pending", orderId: 8 });
  });

  it("shows gateway unavailable message when sbp disabled", () => {
    expect(
      resolveCheckoutPostSubmitAction({
        id: 9,
        payment_allowed: true,
        payment_gateway_enabled: false,
      }),
    ).toEqual({ action: "show_gateway_unavailable", orderId: 9 });
  });
});

describe("resolveOrderPaymentUiState", () => {
  it("shows pay button for payable order", () => {
    expect(
      resolveOrderPaymentUiState({ payment_allowed: true, status: "processing" }),
    ).toEqual({ kind: "pay" });
  });

  it("shows gateway unavailable when payment gateway disabled", () => {
    expect(
      resolveOrderPaymentUiState({ payment_allowed: true, status: "processing" }, false),
    ).toEqual({ kind: "gateway_unavailable" });
  });

  it("shows pending disabled state", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_allowed: false,
        availability_confirmation_status: "pending",
      }),
    ).toEqual({ kind: "pending" });
  });

  it("shows paid badge", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_paid_at: "2026-06-27T10:00:00Z",
        payment_status: "IPS_ACCEPTED",
      }),
    ).toEqual({ kind: "paid" });
  });

  it("shows paid badge with payment_state", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_state: "paid",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "paid" });
  });

  it("shows continue pay for waiting and initializing states", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_state: "waiting",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "continue_pay" });
    expect(
      resolveOrderPaymentUiState({
        payment_state: "initializing",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "continue_pay" });
  });

  it("shows pay again for failed and pay for not_started", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_state: "failed",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "pay_again" });
    expect(
      resolveOrderPaymentUiState({
        payment_state: "not_started",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "pay" });
  });

  it("hides pay button for paid order", () => {
    expect(isOrderPaid({ payment_state: "paid" })).toBe(true);
    expect(
      resolveOrderPaymentUiState({
        payment_state: "paid",
        payment_allowed: true,
      }),
    ).toEqual({ kind: "paid" });
  });

  it("shows exhausted state", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_state: "exhausted",
        payment_allowed: false,
        status: "processing",
      }),
    ).toEqual({ kind: "exhausted" });
  });

  it("shows late paid after cancel state", () => {
    expect(
      resolveOrderPaymentUiState({
        payment_state: "late_paid_after_cancel",
        status: "cancelled",
        payment_allowed: false,
        late_payment_after_auto_cancel: true,
      }),
    ).toEqual({ kind: "late_paid_after_cancel" });
  });
});

describe("customer payment copy", () => {
  it("uses short exhausted text", () => {
    expect(orderPaymentExhaustedText(7)).toBe("Лимит попыток исчерпан");
    expect(ORDER_PAYMENT_EXHAUSTED_TEXT).toBe("Лимит попыток исчерпан");
  });

  it("uses pending availability copy", () => {
    expect(ORDER_PAYMENT_PENDING_LABEL).toBe("Проверяем наличие");
    expect(ORDER_PAYMENT_PENDING_HEADLINE).toBe("Проверяем наличие.");
    expect(ORDER_PAYMENT_PENDING_SUBTEXT).toBe("Оплата станет доступна после проверки.");
  });

  it("uses retry payment button label", () => {
    expect(ORDER_PAYMENT_PAY_AGAIN_TEXT).toBe("Повторить оплату");
    expect(ORDER_PAYMENT_PAY_TEXT).toBe("Оплатить");
  });

  it("uses late paid after cancel note", () => {
    expect(ORDER_PAYMENT_LATE_AFTER_CANCEL_TEXT).toBe("Заказ проходит проверку.");
  });

  it("strips msk suffix from payment due display", () => {
    expect(formatPaymentDueDisplay("04.07.2026 15:20 мск")).toBe("04.07.2026 15:20");
    expect(formatPaymentDueDisplay("04.07.2026 15:20")).toBe("04.07.2026 15:20");
  });
});

describe("paymentStateBadge", () => {
  it("shows initializing label from API", () => {
    expect(paymentStateBadgeLabel("initializing", "Создаём оплату")).toBe("Создаём оплату");
  });

  it("shows not_started label from API", () => {
    expect(paymentStateBadgeLabel("not_started", "Можно оплатить")).toBe("Можно оплатить");
  });

  it("shows pending availability label from API", () => {
    expect(paymentStateBadgeLabel("not_started", "Проверяем наличие")).toBe(
      "Проверяем наличие",
    );
  });

  it("uses orange style for late paid after cancel", () => {
    expect(paymentStateBadgeStyle("late_paid_after_cancel").color).toBe("#FF9F0A");
    expect(paymentStateBadgeLabel("late_paid_after_cancel", "Оплачено")).toBe("Оплачено");
  });
});
