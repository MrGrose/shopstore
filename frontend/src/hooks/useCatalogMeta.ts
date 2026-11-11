import { useQuery } from "@tanstack/react-query";

import {
  resolveCatalogCategoryApiParams,
  fetchCatalogProductMeta,
  type CatalogFacets,
} from "../lib/storefront/catalog";
import {
  catalogMetaQueryKey,
  type CatalogFilterQueryOpts,
} from "../lib/storefront/catalogFilterQuery";

const CATALOG_META_STALE_MS = 60_000;

function buildMetaRequest(opts: CatalogFilterQueryOpts) {
  return {
    top_category: opts.topCategory ?? undefined,
    ...resolveCatalogCategoryApiParams(opts.sub, opts.type, opts.categoryUrlParams),
    brand: opts.brand || undefined,
    gender: opts.gender || undefined,
    color: opts.color || undefined,
    size: opts.size || undefined,
    price_min: opts.priceMin || undefined,
    price_max: opts.priceMax || undefined,
    q: opts.searchQ?.trim() || undefined,
    include: "all",
  };
}

export function useCatalogMeta(
  opts: CatalogFilterQueryOpts,
  enabled = true,
): {
  total: number | undefined;
  facets: CatalogFacets | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isPlaceholderData: boolean;
  error: Error | null;
} {
  const query = useQuery<{ total: number; facets: CatalogFacets }, Error>({
    queryKey: catalogMetaQueryKey(opts),
    queryFn: () => fetchCatalogProductMeta(buildMetaRequest(opts)),
    enabled: enabled && Boolean(opts.topCategory),
    staleTime: CATALOG_META_STALE_MS,
  });

  return {
    total: query.data?.total,
    facets: query.data?.facets,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isPlaceholderData: query.isPlaceholderData,
    error: query.error,
  };
}
