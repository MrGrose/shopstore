import {
  ORDER_PAYMENT_CONTINUE_TEXT,
  ORDER_PAYMENT_GATEWAY_UNAVAILABLE_TEXT,
  ORDER_PAYMENT_LATE_AFTER_CANCEL_TEXT,
  ORDER_PAYMENT_PAY_AGAIN_TEXT,
  ORDER_PAYMENT_PAY_TEXT,
  ORDER_PAYMENT_PENDING_SUBTEXT,
  ORDER_PAYMENT_EXHAUSTED_TEXT,
  resolveOrderPaymentUiState,
  type OrderPaymentLike,
} from "../../lib/storefront/orderPaymentUi";
import { miniAppPillClass } from "../../lib/storefront/miniAppUi";
import { useStorefrontCompact } from "../../lib/storefront/useStorefrontSurface";

type Props = {
  order: OrderPaymentLike;
  paymentGatewayEnabled?: boolean;
  onPay: () => void;
  className?: string;
  inline?: boolean;
};

function pendingPaymentButtonClass(
  actionButtonClass: string,
  inline: boolean,
  compact: boolean,
): string {
  return `${actionButtonClass} opacity-60 cursor-not-allowed ${inline ? "" : "w-full"}`;
}

function pendingPaymentButtonStyle(inline: boolean, compact: boolean) {
  return {
    border: "1px solid var(--sp-border)",
    borderRadius: "var(--sp-radius-pill)",
    background: "var(--sp-bg)",
    color: "var(--sp-text-secondary)",
    padding: inline ? undefined : compact ? "0.65rem 1rem" : "0.7rem 1rem",
  } as const;
}

export function OrderPaymentActions({
  order,
  paymentGatewayEnabled = true,
  onPay,
  className,
  inline = false,
}: Props) {
  const compact = useStorefrontCompact();
  const state = resolveOrderPaymentUiState(order, paymentGatewayEnabled);

  if (state.kind === "paid") {
    return null;
  }

  const actionButtonClass = inline
    ? `${className ?? ""} inline-flex items-center justify-center px-5 py-2 text-[13px] font-semibold sp-transition`
    : `${className ?? ""} w-full py-3 font-semibold sp-transition`;

  if (state.kind === "pending") {
    return (
      <div className={className}>
        <p
          className="m-0 text-[13px] leading-snug"
          style={{ color: "var(--sp-text-secondary)" }}
        >
          {ORDER_PAYMENT_PENDING_SUBTEXT}
        </p>
        <button
          type="button"
          disabled
          aria-disabled="true"
          className={`${pendingPaymentButtonClass(actionButtonClass, inline, compact)} mt-3`}
          style={pendingPaymentButtonStyle(inline, compact)}
        >
          {ORDER_PAYMENT_PAY_TEXT}
        </button>
      </div>
    );
  }

  if (state.kind === "gateway_unavailable") {
    return (
      <p
        className={className}
        style={{
          margin: 0,
          fontSize: "13px",
          lineHeight: 1.45,
          color: "var(--sp-text-secondary)",
        }}
      >
        {ORDER_PAYMENT_GATEWAY_UNAVAILABLE_TEXT}
      </p>
    );
  }

  if (state.kind === "exhausted") {
    return (
      <p
        className={className}
        style={{
          margin: 0,
          fontSize: "13px",
          lineHeight: 1.45,
          color: "var(--sp-text-secondary)",
        }}
      >
        {ORDER_PAYMENT_EXHAUSTED_TEXT}
      </p>
    );
  }

  if (state.kind === "late_paid_after_cancel") {
    return (
      <p
        className={className}
        style={{
          margin: 0,
          fontSize: "13px",
          lineHeight: 1.45,
          color: "var(--sp-text-secondary)",
        }}
      >
        {ORDER_PAYMENT_LATE_AFTER_CANCEL_TEXT}
      </p>
    );
  }

  if (state.kind === "continue_pay" || state.kind === "pay" || state.kind === "pay_again") {
    const label =
      state.kind === "continue_pay"
        ? ORDER_PAYMENT_CONTINUE_TEXT
        : state.kind === "pay_again"
          ? ORDER_PAYMENT_PAY_AGAIN_TEXT
          : ORDER_PAYMENT_PAY_TEXT;
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onPay();
        }}
        className={
          compact
            ? `${miniAppPillClass(true)} ${className ?? ""} ${inline ? "" : "w-full"}`
            : `${actionButtonClass} text-white hover:opacity-90`
        }
        style={
          compact
            ? undefined
            : {
                background: "var(--sp-blue)",
                borderRadius: "var(--sp-radius-pill)",
                border: "none",
                cursor: "pointer",
              }
        }
      >
        {label}
      </button>
    );
  }

  return null;
}
