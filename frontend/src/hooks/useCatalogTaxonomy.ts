import { useQuery } from "@tanstack/react-query";

import { fetchCatalogTaxonomy, type CatalogTaxonomy } from "../lib/storefront/catalog";

export const catalogTaxonomyQueryKey = ["catalog", "taxonomy"] as const;

const CATALOG_REFERENCE_STALE_MS = 5 * 60_000;

export function useCatalogTaxonomy(): {
  taxonomy: CatalogTaxonomy | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogTaxonomy, Error>({
    queryKey: catalogTaxonomyQueryKey,
    queryFn: fetchCatalogTaxonomy,
    staleTime: CATALOG_REFERENCE_STALE_MS,
  });

  return {
    taxonomy: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
