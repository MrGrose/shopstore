import { isVariantBuyable, variantBuyableQty, type StorefrontVariant as VariantStockRow } from "./variantStock";

export type StorefrontVariant = VariantStockRow & {
  option1?: string | null;
  option2?: string | null;
  option3?: string | null;
  available: boolean;
  inventory_quantity: number;
};

export type StockDisplayConfig = {
  okFromQty: number;
  lowMinQty: number;
  shippingEstimateFallback: string;
  labels: {
    inStock: string;
    low: string;
    last: string;
    out: string;
  };
};

export type BuyerStockBadgeParts = {
  text: string;
  extraClass: string;
};

export const DEFAULT_STOCK_DISPLAY: StockDisplayConfig = {
  okFromQty: 6,
  lowMinQty: 2,
  shippingEstimateFallback: "Доставка 14 дней",
  labels: {
    inStock: "В наличии",
    low: "Мало",
    last: "Последний",
    out: "Нет в наличии",
  },
};

export async function fetchStockDisplayConfig(): Promise<StockDisplayConfig> {
  try {
    const res = await fetch("/storefront/stock-display", { credentials: "include" });
    if (!res.ok) return DEFAULT_STOCK_DISPLAY;
    const data = (await res.json()) as StockDisplayConfig;
    return {
      okFromQty: Number(data.okFromQty) || DEFAULT_STOCK_DISPLAY.okFromQty,
      lowMinQty: Number(data.lowMinQty) || DEFAULT_STOCK_DISPLAY.lowMinQty,
      shippingEstimateFallback:
        String(data.shippingEstimateFallback || "").trim() ||
        DEFAULT_STOCK_DISPLAY.shippingEstimateFallback,
      labels: { ...DEFAULT_STOCK_DISPLAY.labels, ...data.labels },
    };
  } catch {
    return DEFAULT_STOCK_DISPLAY;
  }
}

export function buyerStockBadgeParts(
  qty: number,
  cfg: StockDisplayConfig = DEFAULT_STOCK_DISPLAY,
): BuyerStockBadgeParts {
  const q = Math.max(0, Math.floor(Number(qty) || 0));
  const okFrom = Math.max(1, cfg.okFromQty);
  let lowMin = Math.max(1, cfg.lowMinQty);
  if (lowMin >= okFrom) lowMin = Math.max(1, okFrom - 1);
  const L = cfg.labels;
  if (q <= 0) return { text: L.out, extraClass: "out-of-stock" };
  if (q < lowMin) return { text: L.last, extraClass: "stock-badge--last" };
  if (q < okFrom) return { text: L.low, extraClass: "stock-badge--low" };
  return { text: L.inStock, extraClass: "" };
}

export type BuyerStockDisplay = {
  kind: "in" | "out";
  text: string;
};

export function buyerStockDisplay(
  qty: number,
  cfg: StockDisplayConfig = DEFAULT_STOCK_DISPLAY,
): BuyerStockDisplay {
  const parts = buyerStockBadgeParts(qty, cfg);
  if (parts.extraClass === "out-of-stock") {
    return { kind: "out", text: cfg.labels.out };
  }
  return { kind: "in", text: cfg.labels.inStock };
}

export function buyerStockLabel(qty: number, cfg: StockDisplayConfig = DEFAULT_STOCK_DISPLAY): string {
  return buyerStockBadgeParts(qty, cfg).text;
}

type VariantRow = StorefrontVariant;
type OptionKey = "option1" | "option2" | "option3";
type Selection = Partial<Record<OptionKey, string>>;

function fmtOpt(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

function variantInStock(v: VariantRow): boolean {
  return isVariantBuyable(v);
}

function matchingVariants(
  variants: VariantRow[],
  optionKeys: OptionKey[],
  selection: Selection,
): VariantRow[] {
  return variants.filter((v) =>
    optionKeys.every((k) => {
      const want = selection[k];
      if (!want) return true;
      return fmtOpt(v[k]) === want;
    }),
  );
}

/** Остаток варианта при наведении на значение опции (как buyerStockBadgeParts в legacy). */
export function variantQtyForChipHover(
  variants: VariantRow[],
  optionKeys: OptionKey[],
  selection: Selection,
  key: OptionKey,
  value: string,
): number {
  const next: Selection = { ...selection, [key]: value };
  const inStock = matchingVariants(variants, optionKeys, next).filter(variantInStock);
  if (!inStock.length) return 0;

  const full = variants.find((v) =>
    optionKeys.every((k) => {
      const want = next[k];
      if (!want) return true;
      return fmtOpt(v[k]) === want;
    }),
  );
  if (full && variantInStock(full)) return variantBuyableQty(full);

  return Math.max(...inStock.map((v) => variantBuyableQty(v)));
}

export function variantStockLabelForChip(
  variants: VariantRow[],
  optionKeys: OptionKey[],
  selection: Selection,
  key: OptionKey,
  value: string,
  cfg: StockDisplayConfig = DEFAULT_STOCK_DISPLAY,
): string {
  return buyerStockLabel(variantQtyForChipHover(variants, optionKeys, selection, key, value), cfg);
}
