import type { StorefrontApiErrorDetail } from "./api";

export type { StorefrontApiErrorDetail };

export type DeliveryFormField =
  | "last_name"
  | "first_name"
  | "city"
  | "postal_code"
  | "street"
  | "house"
  | "apartment"
  | "phone";

const DELIVERY_FIELDS = new Set<string>([
  "last_name",
  "first_name",
  "city",
  "postal_code",
  "street",
  "house",
  "apartment",
  "phone",
]);

function formatValidationMsg(raw: string): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  return s.replace(/^Value error,\s*/i, "").trim() || s;
}

function apiLocToDeliveryField(loc: unknown): DeliveryFormField | null {
  if (!Array.isArray(loc)) return null;
  for (let i = loc.length - 1; i >= 0; i -= 1) {
    const part = loc[i];
    if (typeof part === "string" && DELIVERY_FIELDS.has(part)) {
      return part as DeliveryFormField;
    }
  }
  return null;
}

/** Ошибки полей доставки из FastAPI 422 (`detail` — массив). */
export function parseDeliveryFieldErrors(
  apiDetail: StorefrontApiErrorDetail | undefined,
): Array<{ field: DeliveryFormField; msg: string }> {
  if (!Array.isArray(apiDetail)) return [];
  const out: Array<{ field: DeliveryFormField; msg: string }> = [];
  for (const item of apiDetail) {
    const field = apiLocToDeliveryField(item?.loc);
    if (!field) continue;
    const msg = formatValidationMsg(String(item?.msg || ""));
    if (msg) out.push({ field, msg });
  }
  return out;
}

export function deliveryFieldErrorsMap(
  hints: Array<{ field: DeliveryFormField; msg: string }>,
): Partial<Record<DeliveryFormField, string>> {
  const map: Partial<Record<DeliveryFormField, string>> = {};
  for (const h of hints) {
    map[h.field] = h.msg;
  }
  return map;
}

/** Текст ошибки промокода из FastAPI 422. */
export function parsePromoFieldError(apiDetail: StorefrontApiErrorDetail | undefined): string | null {
  if (typeof apiDetail === "string" && apiDetail.trim()) return apiDetail.trim();
  if (!Array.isArray(apiDetail)) return null;
  for (const item of apiDetail) {
    const loc = item?.loc;
    if (!Array.isArray(loc) || !loc.includes("promo_code")) continue;
    const msg = formatValidationMsg(String(item?.msg || ""));
    if (msg) return msg;
  }
  return null;
}
