import type { CatalogSortPrice } from "./catalogFilterParams";
import { writeCategoryFilterParams, writeCategoryUrlParams } from "./catalogFilterParams";

export type CatalogFilterQueryOpts = {
  topCategory: string | null;
  sub: string;
  type: string;
  useMappingParams?: boolean;
  categoryUrlParams?: Record<string, string> | null;
  brand: string;
  gender: string;
  color: string;
  size: string;
  priceMin: string;
  priceMax: string;
  sortPrice?: CatalogSortPrice;
  searchQ?: string;
};

// Добавляет параметры каталога в URLSearchParams для API запросов.
export function appendCatalogFilterParams(
  params: URLSearchParams,
  opts: CatalogFilterQueryOpts,
): void {
  if (opts.topCategory) params.set("top_category", opts.topCategory);
  if (opts.searchQ?.trim()) params.set("q", opts.searchQ.trim());
  if (opts.categoryUrlParams && Object.keys(opts.categoryUrlParams).length > 0) {
    writeCategoryUrlParams(params, opts.categoryUrlParams);
  } else {
    writeCategoryFilterParams(params, opts.sub, opts.type, Boolean(opts.useMappingParams));
  }
  if (opts.brand) params.set("brand", opts.brand);
  if (opts.gender) params.set("gender", opts.gender);
  if (opts.color) params.set("color", opts.color);
  if (opts.size) params.set("size", opts.size);
  const min = opts.priceMin.trim();
  const max = opts.priceMax.trim();
  if (min) params.set("price_min", min);
  if (max) params.set("price_max", max);
  if (opts.sortPrice === "asc" || opts.sortPrice === "desc") {
    params.set("sort_price", opts.sortPrice);
  }
}

// Сериализует фильтры каталога в query string (без page).
export function catalogFilterQueryString(opts: CatalogFilterQueryOpts): string {
  const params = new URLSearchParams();
  appendCatalogFilterParams(params, opts);
  return params.toString();
}

export function catalogProductsQueryKey(
  opts: CatalogFilterQueryOpts,
  page: number,
  pageSize: number,
): readonly ["catalog", "products", string, number, number] {
  return ["catalog", "products", catalogFilterQueryString(opts), page, pageSize] as const;
}

export function catalogProductsInfiniteQueryKey(
  opts: CatalogFilterQueryOpts,
  pageSize: number,
): readonly ["catalog", "products", "infinite", string, number] {
  return ["catalog", "products", "infinite", catalogFilterQueryString(opts), pageSize] as const;
}

export function catalogCountQueryKey(
  opts: CatalogFilterQueryOpts,
): readonly ["catalog", "count", string] {
  return ["catalog", "count", catalogFilterQueryString(opts)] as const;
}

export function catalogMetaQueryKey(
  opts: CatalogFilterQueryOpts,
): readonly ["catalog", "meta", string] {
  return ["catalog", "meta", catalogFilterQueryString(opts)] as const;
}
