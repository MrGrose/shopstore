import { useQuery } from "@tanstack/react-query";

import {
  fetchCatalogFacetsByQueryKey,
  type CatalogFacets,
} from "../lib/storefront/catalog";

export function catalogFacetsQueryKey(
  queryKey: string,
  include: string,
): readonly ["catalog", "facets", string, string] {
  return ["catalog", "facets", include, queryKey] as const;
}

const CATALOG_FACETS_STALE_MS = 60_000;

export function useCatalogFacets(
  queryKey: string,
  include: string,
  enabled = true,
): {
  facets: CatalogFacets | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogFacets, Error>({
    queryKey: catalogFacetsQueryKey(queryKey, include),
    queryFn: () => fetchCatalogFacetsByQueryKey(queryKey, include),
    enabled,
    staleTime: CATALOG_FACETS_STALE_MS,
  });

  return {
    facets: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
