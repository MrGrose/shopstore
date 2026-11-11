import type { CatalogTaxonomy } from "./catalog";
import {
  parseProductTypeFromSearchParams,
  parseSubCategoryFromSearchParams,
  type SubCategorySlug,
} from "./catalogCategoryFilter";
import {
  catalogAllPath,
  isCatalogListingPath,
  type CatalogSportSlug,
} from "./catalogNavigation";
import type {
  VariantConstraintGroup,
  VariantConstraintPreset,
} from "./variantConstraintTypes";

export type { VariantConstraintGroup, VariantConstraintPreset } from "./variantConstraintTypes";

export type CatalogSortPrice = "" | "asc" | "desc";

const FACET_DECIMAL_SIZE = /^\d+,\d+$/;

/** Comma splits legacy multi-value lists for brand only; color/gender stay opaque. */
function splitFacetTokenList(raw: string, facetKey: CatalogFacetKey): string[] {
  const text = raw.trim();
  if (!text) return [];
  if (text.includes("|")) {
    return text.split("|").map((part) => part.trim()).filter(Boolean);
  }
  if (facetKey === "size" && FACET_DECIMAL_SIZE.test(text)) {
    return [text];
  }
  if (facetKey === "brand" && text.includes(",")) {
    const parts = text.split(",").map((part) => part.trim()).filter(Boolean);
    if (parts.length > 1) return parts;
    if (parts.length === 1) return parts;
    return [];
  }
  return [text];
}

export type CatalogFacetKey = "brand" | "gender" | "color" | "size";

/** Variant-level facets only. Product facets → CATALOG_PRODUCT_FACET_KEYS. */
export const CATALOG_PRODUCT_FACET_KEYS = ["brand", "gender"] as const satisfies readonly CatalogFacetKey[];
export const CATALOG_VARIANT_FACET_KEYS = ["color", "size"] as const satisfies readonly CatalogFacetKey[];

export type CatalogVariantFacetKey = (typeof CATALOG_VARIANT_FACET_KEYS)[number];

export type ProductPageLocationState = {
  from?: string;
  previewImageUrl?: string | null;
  variantConstraintPreset?: VariantConstraintPreset;
};

export type CatalogFilterUrlOpts = {
  useMappingParams?: boolean;
  categoryUrlParams?: Record<string, string> | null;
};

/** True when URL carries sub/section/type filter keys (not merely other facets). */
export function hasCategoryFilterInUrl(params: URLSearchParams): boolean {
  return (
    params.has("section") ||
    params.has("node") ||
    params.has("sub") ||
    params.has("category_type") ||
    params.has("type")
  );
}

// Пишет section/node или sub/category_type в query string.
export function writeCategoryFilterParams(
  params: URLSearchParams,
  sub: string,
  productType: string,
  useMappingParams: boolean,
): void {
  params.delete("sub");
  params.delete("category_type");
  params.delete("type");
  params.delete("section");
  params.delete("node");
  const subTrim = sub.trim();
  const typeTrim = productType.trim();
  if (useMappingParams) {
    if (subTrim) params.set("section", subTrim);
    if (typeTrim) params.set("node", typeTrim);
    return;
  }
  if (subTrim) params.set("sub", subTrim);
  if (typeTrim) params.set("category_type", typeTrim);
}

// Пишет canonical category keys из navigation.url_params.
export function writeCategoryUrlParams(
  params: URLSearchParams,
  urlParams: Record<string, string>,
): void {
  params.delete("sub");
  params.delete("category_type");
  params.delete("type");
  params.delete("section");
  params.delete("node");
  for (const [key, value] of Object.entries(urlParams)) {
    const trimmed = value.trim();
    if (trimmed) params.set(key, trimmed);
  }
}

export type CatalogFacetOptionsSlice = {
  topCategory: string | null;
  sub: string;
  type: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  searchQ?: string;
  useMappingParams?: boolean;
  categoryUrlParams?: Record<string, string> | null;
};

export type CatalogFilterState = {
  sub: SubCategorySlug | "";
  productType: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  sortPrice: CatalogSortPrice;
  category: string;
};

export function readCatalogSearchQuery(params: URLSearchParams): string {
  return params.get("q")?.trim() ?? "";
}

export function applyCatalogSearchQueryToSearchParams(
  params: URLSearchParams,
  raw: string,
): URLSearchParams {
  const next = new URLSearchParams(params);
  const q = raw.trim();
  if (q) next.set("q", q);
  else next.delete("q");
  return next;
}

export function buildCatalogFacetResetPatch(): Partial<CatalogFilterState> {
  return {
    brand: "",
    gender: "",
    color: "",
    size: "",
    priceMin: "",
    priceMax: "",
    sortPrice: "",
  };
}

export function buildCatalogSearchNavigateTarget(
  pathname: string,
  currentSearch: string,
  rawQuery: string,
): { pathname: string; search: string } {
  if (isCatalogListingPath(pathname)) {
    const params = applyCatalogSearchQueryToSearchParams(
      new URLSearchParams(currentSearch),
      rawQuery,
    );
    const qs = params.toString();
    return { pathname, search: qs ? `?${qs}` : "" };
  }
  const params = applyCatalogSearchQueryToSearchParams(new URLSearchParams(), rawQuery);
  const qs = params.toString();
  return { pathname: catalogAllPath(), search: qs ? `?${qs}` : "" };
}

export function parseSortPrice(raw: string | null): CatalogSortPrice {
  return raw === "asc" || raw === "desc" ? raw : "";
}

// Разбирает serialized и repeated query values фасета.
export function parseFacetListParam(
  params: URLSearchParams,
  key: CatalogFacetKey,
): string[] {
  const repeated = params.getAll(key).flatMap((raw) => splitFacetTokenList(raw, key));
  const seen = new Set<string>();
  const values: string[] = [];
  for (const value of repeated) {
    if (seen.has(value)) continue;
    seen.add(value);
    values.push(value);
  }
  return values;
}

// Сериализует значения фасета для state/URL (| между значениями).
export function joinFacetListParam(values: string[] | readonly string[]): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const value of values) {
    const trimmed = String(value).trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    parts.push(trimmed);
  }
  return parts.join("|");
}

// Переключает значение в multi-select фасете.
export type FacetSearchOption = {
  value: string;
  label_ru: string;
  count?: number;
};

/** Client-side substring filter for facet checkbox lists. */
export function filterFacetOptions<T extends FacetSearchOption>(
  options: T[],
  query: string,
): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;
  return options.filter(
    (option) =>
      !option.value ||
      option.label_ru.toLowerCase().includes(q) ||
      option.value.toLowerCase().includes(q),
  );
}

export function toggleFacetListValue(
  current: string,
  value: string,
  facetKey: CatalogFacetKey,
): string {
  const trimmed = value.trim();
  if (!trimmed) return current;
  const qs = new URLSearchParams();
  if (current.trim()) qs.set(facetKey, current.trim());
  const list = parseFacetListParam(qs, facetKey);
  const set = new Set(list);
  if (set.has(trimmed)) set.delete(trimmed);
  else set.add(trimmed);
  return joinFacetListParam([...set]);
}

function readFacetParam(params: URLSearchParams, key: string): string {
  return joinFacetListParam(parseFacetListParam(params, key));
}

/** Читает фильтры из URL без отбрасывания «неизвестных» значений (для синхронизации state ↔ URL). */
export function readCatalogFiltersFromSearchParams(
  params: URLSearchParams,
  sportSlug?: CatalogSportSlug | null,
  taxonomy?: CatalogTaxonomy | null,
): CatalogFilterState {
  return {
    sub: parseSubCategoryFromSearchParams(params, sportSlug, taxonomy),
    productType: parseProductTypeFromSearchParams(params),
    brand: readFacetParam(params, "brand"),
    gender: readFacetParam(params, "gender"),
    color: readFacetParam(params, "color"),
    size: readFacetParam(params, "size"),
    priceMin: params.get("price_min")?.trim() ?? "",
    priceMax: params.get("price_max")?.trim() ?? "",
    sortPrice: parseSortPrice(params.get("sort_price")),
    category: params.get("category")?.trim() ?? "",
  };
}

export function parseCatalogFiltersFromSearchParams(
  params: URLSearchParams,
  sportSlug?: CatalogSportSlug | null,
  taxonomy?: CatalogTaxonomy | null,
): CatalogFilterState {
  return readCatalogFiltersFromSearchParams(params, sportSlug, taxonomy);
}

function setOrDelete(params: URLSearchParams, key: string, value: string) {
  const trimmed = value.trim();
  params.delete(key);
  if (trimmed) params.set(key, trimmed);
}

// Facet options: все фильтры кроме self-filter (counts внутри активного среза).
export function catalogFacetOptionsSliceExcluding(
  slice: CatalogFacetOptionsSlice,
  exclude: CatalogFacetKey,
): CatalogFacetOptionsSlice {
  return {
    ...slice,
    brand: exclude === "brand" ? "" : slice.brand,
    gender: exclude === "gender" ? "" : slice.gender,
    color: exclude === "color" ? "" : slice.color,
    size: exclude === "size" ? "" : slice.size,
  };
}

export function catalogFacetOptionsQueryKey(
  slice: CatalogFacetOptionsSlice,
  exclude: CatalogFacetKey,
): string {
  const opts = catalogFacetOptionsSliceExcluding(slice, exclude);
  const params = new URLSearchParams();
  if (opts.topCategory) params.set("top_category", opts.topCategory);
  if (opts.categoryUrlParams && Object.keys(opts.categoryUrlParams).length > 0) {
    writeCategoryUrlParams(params, opts.categoryUrlParams);
  } else {
    writeCategoryFilterParams(params, opts.sub, opts.type, Boolean(opts.useMappingParams));
  }
  setOrDelete(params, "brand", opts.brand);
  setOrDelete(params, "gender", opts.gender);
  setOrDelete(params, "color", opts.color);
  setOrDelete(params, "size", opts.size);
  setOrDelete(params, "price_min", opts.priceMin);
  setOrDelete(params, "price_max", opts.priceMax);
  setOrDelete(params, "q", opts.searchQ ?? "");
  return params.toString();
}

export function applyCatalogFiltersToSearchParams(
  base: URLSearchParams,
  filters: Partial<CatalogFilterState>,
  urlOpts?: CatalogFilterUrlOpts,
): URLSearchParams {
  const params = new URLSearchParams(base);
  const useMappingParams = Boolean(urlOpts?.useMappingParams);
  const categoryUrlParams = urlOpts?.categoryUrlParams;
  if ("sub" in filters || "productType" in filters) {
    const sub = "sub" in filters ? (filters.sub ?? "") : parseSubCategoryFromSearchParams(params);
    const productType =
      "productType" in filters ? (filters.productType ?? "") : parseProductTypeFromSearchParams(params);
    if (categoryUrlParams && Object.keys(categoryUrlParams).length > 0) {
      writeCategoryUrlParams(params, categoryUrlParams);
    } else {
      writeCategoryFilterParams(params, sub, productType, useMappingParams);
    }
  }
  if ("brand" in filters) setOrDelete(params, "brand", filters.brand ?? "");
  if ("gender" in filters) setOrDelete(params, "gender", filters.gender ?? "");
  if ("color" in filters) setOrDelete(params, "color", filters.color ?? "");
  if ("size" in filters) setOrDelete(params, "size", filters.size ?? "");
  if ("priceMin" in filters) setOrDelete(params, "price_min", filters.priceMin ?? "");
  if ("priceMax" in filters) setOrDelete(params, "price_max", filters.priceMax ?? "");
  if ("sortPrice" in filters) setOrDelete(params, "sort_price", filters.sortPrice ?? "");
  if ("category" in filters) setOrDelete(params, "category", filters.category ?? "");
  return params;
}

export type CatalogReturnPathOpts = {
  sub: string;
  productType: string;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  sortPrice: CatalogSortPrice;
  searchQ?: string;
  useMappingParams?: boolean;
};

export function buildCatalogSearchParams(opts: CatalogReturnPathOpts): URLSearchParams {
  const params = new URLSearchParams();
  if (opts.searchQ?.trim()) params.set("q", opts.searchQ.trim());
  writeCategoryFilterParams(
    params,
    opts.sub,
    opts.productType,
    Boolean(opts.useMappingParams),
  );
  setOrDelete(params, "brand", opts.brand);
  setOrDelete(params, "gender", opts.gender);
  setOrDelete(params, "color", opts.color);
  setOrDelete(params, "size", opts.size);
  setOrDelete(params, "price_min", opts.priceMin);
  setOrDelete(params, "price_max", opts.priceMax);
  setOrDelete(params, "sort_price", opts.sortPrice);
  return params;
}

// Переписывает legacy sub/category_type → section/node при mapping taxonomy.
export function canonicalizeCategorySearchParams(
  params: URLSearchParams,
  sub: string,
  productType: string,
): URLSearchParams {
  const next = new URLSearchParams(params);
  writeCategoryFilterParams(next, sub, productType, true);
  return next;
}

export function buildCatalogReturnPath(pathname: string, opts: CatalogReturnPathOpts): string {
  const qs = buildCatalogSearchParams(opts).toString();
  return qs ? `${pathname}?${qs}` : pathname;
}
export function parseFacetListValue(raw: string, facetKey: CatalogFacetKey): string[] {
  if (!raw.trim()) return [];
  const qs = new URLSearchParams();
  qs.set(facetKey, raw.trim());
  return parseFacetListParam(qs, facetKey);
}

export function buildVariantConstraintPreset(
  filters: Pick<CatalogFilterState, CatalogVariantFacetKey>,
): VariantConstraintPreset {
  const groups: VariantConstraintGroup[] = [];
  for (const key of CATALOG_VARIANT_FACET_KEYS) {
    const tokens = parseFacetListValue(filters[key], key);
    if (tokens.length) groups.push({ id: key, tokens });
  }
  return groups;
}

export function buildVariantConstraintPresetFromSearchParams(
  params: URLSearchParams,
): VariantConstraintPreset {
  const groups: VariantConstraintGroup[] = [];
  for (const key of CATALOG_VARIANT_FACET_KEYS) {
    const tokens = parseFacetListParam(params, key);
    if (tokens.length) groups.push({ id: key, tokens });
  }
  return groups;
}

export function buildPdpVariantSearchParams(
  filters: Pick<CatalogFilterState, CatalogVariantFacetKey>,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of CATALOG_VARIANT_FACET_KEYS) {
    const tokens = parseFacetListValue(filters[key], key);
    if (tokens[0]) params.set(key, tokens[0]);
  }
  return params;
}

export function pickVariantConstraintPreset(
  statePreset: VariantConstraintPreset | undefined,
  urlPreset: VariantConstraintPreset,
): VariantConstraintPreset {
  if (statePreset !== undefined) return statePreset;
  return urlPreset;
}
