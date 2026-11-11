import type { VariantConstraintPreset } from "./variantConstraintTypes";
import {
  findMatchingVariant,
  fmtOpt,
  getVisibleVariantOptionKeys,
  isValueAvailable,
  isVariantInStock,
  selectionFromVariant,
  type OptionKey,
  type VariantSelectionProduct,
} from "./variantSelection";

function tokenEqualsValue(token: string, value: string): boolean {
  return token.trim().toLowerCase() === value.trim().toLowerCase();
}

function distinctValuesForKey(
  variants: NonNullable<VariantSelectionProduct["variants"]>,
  key: OptionKey,
): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const variant of variants) {
    const value = fmtOpt(variant[key]);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

function assignToken(
  variants: NonNullable<VariantSelectionProduct["variants"]>,
  visibleKeys: OptionKey[],
  selection: Partial<Record<OptionKey, string>>,
  token: string,
): Partial<Record<OptionKey, string>> | null {
  for (const key of visibleKeys) {
    for (const value of distinctValuesForKey(variants, key)) {
      if (!tokenEqualsValue(token, value)) continue;
      if (!isValueAvailable(variants, selection, key, value)) continue;
      return { ...selection, [key]: value };
    }
  }
  return null;
}

function resolveGroups(
  product: VariantSelectionProduct,
  preset: VariantConstraintPreset,
): Partial<Record<OptionKey, string>> | null {
  const variants = product.variants;
  if (!Array.isArray(variants) || !variants.length || !preset.length) return null;

  const visibleKeys = getVisibleVariantOptionKeys(product);
  if (!visibleKeys.length) return null;

  function backtrack(
    groupIndex: number,
    selection: Partial<Record<OptionKey, string>>,
  ): Partial<Record<OptionKey, string>> | null {
    if (groupIndex >= preset.length) {
      const match = findMatchingVariant(variants, selection);
      if (!match || !isVariantInStock(match)) return null;
      return selectionFromVariant(match);
    }

    const group = preset[groupIndex];
    for (const token of group.tokens) {
      const next = assignToken(variants, visibleKeys, selection, token);
      if (!next) continue;
      const resolved = backtrack(groupIndex + 1, next);
      if (resolved) return resolved;
    }
    return null;
  }

  return backtrack(0, {});
}

/** Pure resolver. No catalog/URL/facet knowledge. In-stock only; null → caller fallback. */
export function resolveVariantSelectionFromConstraints(
  product: VariantSelectionProduct,
  preset: VariantConstraintPreset,
): Partial<Record<OptionKey, string>> | null {
  if (!preset.length) return null;
  return resolveGroups(product, preset);
}
