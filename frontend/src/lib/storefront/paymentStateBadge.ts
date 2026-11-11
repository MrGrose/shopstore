import {
  CheckCircle2,
  Circle,
  Clock,
  Loader2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { PaymentState } from "./orderPaymentUi";

export type PaymentStateBadgeStyle = {
  color: string;
  bg: string;
  Icon: LucideIcon;
};

export const PAYMENT_STATE_BADGE: Record<PaymentState, PaymentStateBadgeStyle> = {
  paid: {
    color: "#30D158",
    bg: "rgba(48,209,88,0.1)",
    Icon: CheckCircle2,
  },
  waiting: {
    color: "#FF9F0A",
    bg: "rgba(255,159,10,0.1)",
    Icon: Clock,
  },
  initializing: {
    color: "#86868B",
    bg: "rgba(134,134,139,0.1)",
    Icon: Loader2,
  },
  not_started: {
    color: "#86868B",
    bg: "rgba(134,134,139,0.1)",
    Icon: Circle,
  },
  failed: {
    color: "#ff8b8b",
    bg: "rgba(255,59,48,0.1)",
    Icon: XCircle,
  },
  exhausted: {
    color: "#ff8b8b",
    bg: "rgba(255,59,48,0.1)",
    Icon: XCircle,
  },
  late_paid_after_cancel: {
    color: "#FF9F0A",
    bg: "rgba(255,159,10,0.1)",
    Icon: Clock,
  },
};

export function paymentStateBadgeStyle(state?: PaymentState | null): PaymentStateBadgeStyle {
  if (state && state in PAYMENT_STATE_BADGE) {
    return PAYMENT_STATE_BADGE[state];
  }
  return PAYMENT_STATE_BADGE.not_started;
}

export function paymentStateBadgeLabel(
  state?: PaymentState | null,
  paymentLabel?: string | null,
): string {
  if (paymentLabel && String(paymentLabel).trim()) return String(paymentLabel).trim();
  if (state && state in PAYMENT_STATE_BADGE) {
    return state === "not_started" ? "—" : state;
  }
  return "—";
}
