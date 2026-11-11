import { storefrontApiFetch } from "./api";
import { clearReferralCookie, readReferralCookie } from "./referral";

export type MyReferrer = {
  referrer_id: number | null;
  referrer_name: string | null;
};

export type ReferralCommissionSource = "global" | "individual" | "disabled";

export function formatReferralPercent(value: number | string): string {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(parsed);
}

export function maskReferralOrderLabel(_orderId: number | string): string {
  return "*****";
}

export type ReferrerApplyStatus =
  | "attributed"
  | "already_attributed"
  | "invalid_code"
  | "self_referral"
  | "attribution_locked"
  | "not_eligible";

export async function fetchMyReferrer(): Promise<MyReferrer> {
  const data = await storefrontApiFetch<MyReferrer>("/users/me/referrer");
  return data as MyReferrer;
}

// Применяет referral_code из cookie; очищает cookie кроме invalid_code.
export async function applyPendingReferrerFromCookie(): Promise<ReferrerApplyStatus | null> {
  if (!readReferralCookie()) return null;
  const data = await storefrontApiFetch<{ status: ReferrerApplyStatus }>(
    "/users/me/referrer/apply",
    { method: "POST" },
  );
  if (data.status !== "invalid_code") {
    clearReferralCookie();
  }
  return data.status;
}
