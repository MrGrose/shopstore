const REFERRAL_COOKIE = "referral_code";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

function referralCookieFlags(): string {
  if (typeof window === "undefined") return "; samesite=lax";
  const secure = window.location.protocol === "https:" ? "; secure" : "";
  return `; path=/; samesite=lax${secure}`;
}

// Сохраняет ?ref= в cookie на 30 дней.
export function captureReferralFromSearch(search: string) {
  if (typeof document === "undefined") return;
  const ref = new URLSearchParams(search).get("ref")?.trim();
  if (!ref) return;
  document.cookie = `${REFERRAL_COOKIE}=${encodeURIComponent(ref)}; max-age=${MAX_AGE_SECONDS}${referralCookieFlags()}`;
}

// Читает сохранённый реф-код из cookie.
export function readReferralCookie(): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${REFERRAL_COOKIE}=`;
  const part = document.cookie
    .split(";")
    .map((chunk) => chunk.trim())
    .find((chunk) => chunk.startsWith(prefix));
  if (!part) return null;
  const raw = part.slice(prefix.length);
  try {
    return decodeURIComponent(raw).trim() || null;
  } catch {
    return raw.trim() || null;
  }
}

// Удаляет referral cookie после успешной/финальной attribution.
export function clearReferralCookie() {
  if (typeof document === "undefined") return;
  document.cookie = `${REFERRAL_COOKIE}=; max-age=0${referralCookieFlags()}`;
}
