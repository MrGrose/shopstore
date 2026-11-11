import { isStorefrontVariantBuyable } from "./variantStock";

export type OptionKey = "option1" | "option2" | "option3";

export type VariantRow = {
  id: number;
  option1?: string | null;
  option2?: string | null;
  option3?: string | null;
  inventory_quantity: number;
  available: boolean;
  available_quantity?: number | null;
  buyable_qty?: number;
  stock_status?: "in_stock" | "low" | "last" | "out_of_stock";
};

export type VariantSelectionProduct = {
  variants?: VariantRow[];
  variant_options_hidden?: string[];
};

export function fmtOpt(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

export function getVariantOptionKeys(variants: VariantRow[] | undefined): OptionKey[] {
  const v = Array.isArray(variants) ? variants : [];
  return (["option1", "option2", "option3"] as const).filter((k) =>
    v.some((it) => fmtOpt(it?.[k]) !== ""),
  );
}

export function getVisibleVariantOptionKeys(product: VariantSelectionProduct): OptionKey[] {
  const hidden = new Set(product.variant_options_hidden ?? []);
  return getVariantOptionKeys(product.variants).filter((k) => !hidden.has(k));
}

export function isVariantInStock(v: VariantRow): boolean {
  return isStorefrontVariantBuyable(v);
}

export function findMatchingVariant(
  variants: VariantRow[],
  selection: Partial<Record<OptionKey, string>>,
): VariantRow | null {
  const optionKeys = getVariantOptionKeys(variants);
  if (!optionKeys.length) return null;

  const hasFullSelection = optionKeys.every((k) => fmtOpt(selection[k]));
  return (
    variants.find((v) => {
      if (hasFullSelection) {
        return optionKeys.every((k) => fmtOpt(v[k]) === fmtOpt(selection[k]));
      }
      return optionKeys.every((k) => {
        const want = selection[k];
        if (!want) return true;
        return fmtOpt(v[k]) === want;
      });
    }) ?? null
  );
}

export function isValueAvailable(
  variants: VariantRow[],
  selection: Partial<Record<OptionKey, string>>,
  key: OptionKey,
  value: string,
): boolean {
  const optionKeys = getVariantOptionKeys(variants);
  const nextSel = { ...selection, [key]: value };
  return variants.some((v) => {
    if (!isVariantInStock(v)) return false;
    return optionKeys.every((k) => {
      const want = nextSel[k];
      if (!want) return true;
      return fmtOpt(v[k]) === want;
    });
  });
}

export function selectionFromVariant(
  variant: VariantRow,
): Partial<Record<OptionKey, string>> {
  const out: Partial<Record<OptionKey, string>> = {};
  for (const key of ["option1", "option2", "option3"] as const) {
    const val = fmtOpt(variant[key]);
    if (val) out[key] = val;
  }
  return out;
}

export function firstInStockSelection(
  variants: VariantRow[],
): Partial<Record<OptionKey, string>> {
  const first = variants.find(isVariantInStock) ?? null;
  return first ? selectionFromVariant(first) : {};
}
