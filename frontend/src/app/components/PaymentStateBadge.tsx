import type { PaymentState } from "../../lib/storefront/orderPaymentUi";
import {
  paymentStateBadgeLabel,
  paymentStateBadgeStyle,
} from "../../lib/storefront/paymentStateBadge";

type Props = {
  state?: PaymentState | null;
  label?: string | null;
  className?: string;
};

export function PaymentStateBadge({ state, label, className }: Props) {
  const cfg = paymentStateBadgeStyle(state);
  const Icon = cfg.Icon;
  const text = paymentStateBadgeLabel(state, label);

  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 text-[12px] font-medium ${className ?? ""}`}
      style={{
        background: cfg.bg,
        color: cfg.color,
        borderRadius: "999px",
      }}
    >
      <Icon size={11} />
      {text}
    </span>
  );
}
