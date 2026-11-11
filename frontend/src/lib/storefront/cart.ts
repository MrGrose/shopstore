/**
 * Корзина — логика из src/static/site/js/storefront-cart-core.js
 * (variant_id, +/- qty, первая позиция в каталоге).
 */

import { storefrontApiFetch } from "./api";

export type CartLine = {
  product_id: number;
  variant_id?: number | null;
  quantity?: number;
  available_stock?: number;
};

export type CartMe = {
  items?: CartLine[];
};

export function cartTotalQty(items: CartLine[] | undefined): number {
  return (items ?? []).reduce((sum, it) => sum + Number(it.quantity || 0), 0);
}

export function broadcastCartCount(count: number): void {
  window.dispatchEvent(new CustomEvent("store:cart:count", { detail: { count } }));
}

export function withVariantId(path: string, variantId?: number | null): string {
  if (variantId == null) return path;
  const n = Number(variantId);
  if (!Number.isFinite(n) || n <= 0) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}variant_id=${n}`;
}

export function getCatalogCartItem(
  items: CartLine[] | undefined,
  productId: number,
): CartLine | null {
  const productItems = (items ?? []).filter(
    (it) => Number(it.product_id) === productId,
  );
  if (!productItems.length) return null;
  return (
    productItems.find(
      (it) => it.variant_id === null || it.variant_id === undefined,
    ) ?? productItems[0]
  );
}

export function cartQtyForLine(
  items: CartLine[] | undefined,
  productId: number,
  variantId?: number | null,
): number {
  const wantVid =
    variantId === null || variantId === undefined ? null : Number(variantId);
  const line = (items ?? []).find((it) => {
    if (Number(it.product_id) !== productId) return false;
    const got =
      it.variant_id === null || it.variant_id === undefined
        ? null
        : Number(it.variant_id);
    return got === wantVid;
  });
  return Number(line?.quantity ?? 0);
}

// Qty только для выбранного variant (переключение размеров на PDP).
export function pdpCartQtyForVariant(
  items: CartLine[] | undefined,
  productId: number,
  variantId?: number | null,
): number {
  return cartQtyForLine(items, productId, variantId);
}

// После POST add: сервер мог подставить другой variant_id.
export function resolvePdpCartLineAfterAdd(
  items: CartLine[] | undefined,
  productId: number,
  requestedVariantId?: number | null,
): { variantId: number | null; qty: number } {
  const exactQty = cartQtyForLine(items, productId, requestedVariantId);
  if (exactQty > 0) {
    const vid =
      requestedVariantId === null || requestedVariantId === undefined
        ? null
        : Number(requestedVariantId);
    return { variantId: vid, qty: exactQty };
  }
  const line = getCatalogCartItem(items, productId);
  if (!line) {
    const vid =
      requestedVariantId === null || requestedVariantId === undefined
        ? null
        : Number(requestedVariantId);
    return { variantId: Number.isFinite(vid) ? vid : null, qty: 0 };
  }
  const variantId =
    line.variant_id === null || line.variant_id === undefined
      ? null
      : Number(line.variant_id);
  return { variantId, qty: Number(line.quantity ?? 0) };
}

export async function fetchCart(): Promise<CartMe> {
  return (await storefrontApiFetch<CartMe>("/cart/me")) ?? { items: [] };
}

export function cartTotalFromItems(items: CartLine[] | undefined): number {
  return cartTotalQty(items);
}

// Обновляет счётчик корзины из ответа API (POST/PUT/DELETE /cart/me/…).
export function broadcastCartFromItems(items: CartLine[] | undefined): void {
  broadcastCartCount(cartTotalFromItems(items));
}

// Добавляет позицию в корзину (POST /cart/me/items).
export async function addCartItem(
  productId: number,
  variantId?: number | null,
  quantity = 1,
): Promise<CartMe> {
  const body: Record<string, unknown> = {
    product_id: productId,
    quantity,
  };
  if (variantId != null && Number(variantId) > 0) {
    body.variant_id = Number(variantId);
  }
  return (
    (await storefrontApiFetch<CartMe>("/cart/me/items", {
      method: "POST",
      body: JSON.stringify(body),
    })) ?? { items: [] }
  );
}

export async function changeCartQty(
  productId: number,
  quantity: number,
  variantId?: number | null,
): Promise<CartMe | null> {
  const path = withVariantId(
    `/cart/me/items/${productId}`,
    variantId ?? null,
  );
  if (quantity <= 0) {
    return (await storefrontApiFetch<CartMe>(path, { method: "DELETE" })) ?? null;
  }
  return (
    (await storefrontApiFetch<CartMe>(path, {
      method: "PUT",
      body: JSON.stringify({ quantity }),
    })) ?? null
  );
}
