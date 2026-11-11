export type StockStatus = "in_stock" | "low" | "last" | "out_of_stock";

export type StorefrontVariant = {
  available?: boolean;
  inventory_quantity?: number;
  available_quantity?: number | null;
  buyable_qty?: number;
  stock_status?: StockStatus;
};

export function variantBuyableQty(v: StorefrontVariant): number {
  if (v.available === false) return 0;
  const net = v.available_quantity;
  if (net != null && Number.isFinite(Number(net))) {
    return Math.max(0, Number(net));
  }
  return Math.max(0, Number(v.inventory_quantity || 0));
}

export function resolveVariantBuyableQty(v: StorefrontVariant): number {
  if (v.buyable_qty != null && Number.isFinite(Number(v.buyable_qty))) {
    return Math.max(0, Number(v.buyable_qty));
  }
  return variantBuyableQty(v);
}

export function isVariantBuyable(v: StorefrontVariant): boolean {
  return resolveVariantBuyableQty(v) > 0;
}

export function isStorefrontVariantBuyable(v: StorefrontVariant): boolean {
  if (v.stock_status !== undefined) {
    return v.stock_status !== "out_of_stock";
  }
  return isVariantBuyable(v);
}

export function stockStatusExtraClass(status?: StockStatus): string {
  switch (status) {
    case "out_of_stock":
      return "out-of-stock";
    case "last":
      return "stock-badge--last";
    case "low":
      return "stock-badge--low";
    case "in_stock":
      return "";
    default: {
      const _exhaustive: never | undefined = status;
      return _exhaustive ?? "";
    }
  }
}
