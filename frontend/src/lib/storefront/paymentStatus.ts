export type PaymentState =
  | "paid"
  | "waiting"
  | "initializing"
  | "failed"
  | "not_started"
  | "exhausted"
  | "late_paid_after_cancel";

export function isPaymentSuccessState(
  paymentState: string | null | undefined,
  isPaid?: boolean,
) {
  if (isPaid) return true;
  return String(paymentState || "").toLowerCase() === "paid";
}

export function isPaymentWaitingState(paymentState: string | null | undefined) {
  const key = String(paymentState || "").toLowerCase();
  return key === "waiting" || key === "initializing";
}

export function isPaymentFinalErrorState(paymentState: string | null | undefined) {
  const key = String(paymentState || "").toLowerCase();
  return key === "failed" || key === "exhausted";
}

export function isPaymentExhaustedState(paymentState: string | null | undefined) {
  return String(paymentState || "").toLowerCase() === "exhausted";
}

export const PAYMENT_POLL_INTERVAL_MS = 4000;
export const PAYMENT_NETWORK_RETRY_DELAYS_MS = [1000, 2000, 4000];

export function parseUtcIsoMs(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(trimmed) ? trimmed : `${trimmed}Z`;
  const parsed = Date.parse(normalized);
  return Number.isNaN(parsed) ? null : parsed;
}

export function qrCountdownMs(qrExpiresAt: string | null | undefined, nowMs = Date.now()) {
  if (!qrExpiresAt) return null;
  const expires = parseUtcIsoMs(qrExpiresAt);
  if (expires === null) return null;
  return Math.max(0, expires - nowMs);
}

export function formatCountdown(ms: number) {
  const totalSec = Math.max(0, Math.ceil(ms / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${String(sec).padStart(2, "0")}`;
}
