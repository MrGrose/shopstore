import type { CatalogSubCategoryItem } from "./catalog";

export function mergeSubcategoryTypes(
  items: CatalogSubCategoryItem[],
  loaded: CatalogSubCategoryItem,
): CatalogSubCategoryItem[] {
  const idx = items.findIndex((row) => row.slug === loaded.slug);
  if (idx < 0) return [...items, loaded];
  const next = [...items];
  next[idx] = loaded;
  return next;
}
