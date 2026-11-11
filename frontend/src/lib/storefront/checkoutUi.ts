export type ApiCart = {
  items: Array<{
    product_id: number;
    variant_id?: number | null;
    quantity: number;
    price_snapshot: number | string;
    product_title?: string | null;
    display_title?: string | null;
    product_brand?: string | null;
    product_image_url?: string | null;
    variant_option1?: string | null;
    variant_option2?: string | null;
    variant_option3?: string | null;
    variant_option1_ru?: string | null;
    variant_option2_ru?: string | null;
    variant_option3_ru?: string | null;
    available_stock?: number;
  }>;
  total_amount: number | string;
  delivery_fee_amount?: number | string;
  total_with_delivery_amount?: number | string;
  supplier_cost_eur?: number | string;
};

export type CheckoutPreview = {
  items_subtotal_amount: number | string;
  discounted_items_subtotal_amount: number | string;
  discount_items_amount: number | string;
  delivery_fee_amount: number | string;
  total_amount: number | string;
  promo_code_applied?: string | null;
  supplier_cost_eur?: number | string;
  customs_duty_amount?: number | string;
  customs_duty_notice?: string | null;
  eur_rate?: number | string;
  requires_availability_confirmation?: boolean;
  availability_message_ru?: string | null;
};

export function deliveryInputBorder(hasError: boolean) {
  return hasError ? "1px solid #ff6b6b" : "1px solid var(--sp-border)";
}

export function moneyRub(value: number | string) {
  const n = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  if (!Number.isFinite(n)) return String(value);
  return `${Math.round(n).toLocaleString("ru-RU")} ₽`;
}

export function rubAmount(value: number | string | null | undefined): number {
  const n = typeof value === "number" ? value : Number(String(value ?? "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

export function cartItemTitle(item: {
  product_id: number;
  product_title?: string | null;
  display_title?: string | null;
}): string {
  return item.display_title || item.product_title || `Товар #${item.product_id}`;
}

export function variantOptionParts(item: {
  variant_option1?: string | null;
  variant_option2?: string | null;
  variant_option3?: string | null;
  variant_option1_ru?: string | null;
  variant_option2_ru?: string | null;
  variant_option3_ru?: string | null;
}): string[] {
  const ru = [item.variant_option1_ru, item.variant_option2_ru, item.variant_option3_ru];
  const source = ru.some((v) => String(v ?? "").trim())
    ? ru
    : [item.variant_option1, item.variant_option2, item.variant_option3];
  return source.map((v) => String(v || "").trim()).filter(Boolean);
}

export const checkoutCardStyle = {
  background: "var(--sp-surface)",
  border: "1px solid var(--sp-border)",
  borderRadius: "var(--sp-radius-card)",
} as const;

export function cartItemUnavailable(item: {
  available_stock?: number;
  quantity: number;
}): boolean {
  if (item.available_stock == null) return false;
  return item.available_stock < item.quantity;
}

export function cartHasUnavailableItems(cart: ApiCart | null | undefined): boolean {
  return (cart?.items ?? []).some(cartItemUnavailable);
}
