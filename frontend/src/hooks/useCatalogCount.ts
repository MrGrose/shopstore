import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  resolveCatalogCategoryApiParams,
  fetchCatalogProductCount,
} from "../lib/storefront/catalog";
import {
  catalogCountQueryKey,
  type CatalogFilterQueryOpts,
} from "../lib/storefront/catalogFilterQuery";

const CATALOG_COUNT_STALE_MS = 60_000;

export function useCatalogCount(
  opts: CatalogFilterQueryOpts,
  enabled = true,
): {
  total: number | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<number, Error>({
    queryKey: catalogCountQueryKey(opts),
    queryFn: () =>
      fetchCatalogProductCount({
        top_category: opts.topCategory ?? undefined,
        ...resolveCatalogCategoryApiParams(opts.sub, opts.type, opts.categoryUrlParams),
        brand: opts.brand || undefined,
        gender: opts.gender || undefined,
        color: opts.color || undefined,
        size: opts.size || undefined,
        price_min: opts.priceMin || undefined,
        price_max: opts.priceMax || undefined,
        q: opts.searchQ?.trim() || undefined,
      }),
    enabled: enabled && Boolean(opts.topCategory),
    staleTime: CATALOG_COUNT_STALE_MS,
    placeholderData: keepPreviousData,
  });

  return {
    total: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
