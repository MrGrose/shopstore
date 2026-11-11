import { useCallback } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { fetchCatalogTaxonomy } from "./catalog";
import { fetchCatalogLabels } from "./catalogLabels";
import { catalogLabelsQueryKey } from "../../hooks/useCatalogLabels";
import { catalogTaxonomyQueryKey } from "../../hooks/useCatalogTaxonomy";

const CATALOG_REFERENCE_STALE_MS = 5 * 60_000;

// Prefetch labels и taxonomy для каталога (idempotent через React Query staleTime).
export function prefetchCatalogReferenceData(queryClient: QueryClient): void {
  void queryClient.prefetchQuery({
    queryKey: catalogLabelsQueryKey,
    queryFn: fetchCatalogLabels,
    staleTime: CATALOG_REFERENCE_STALE_MS,
  });
  void queryClient.prefetchQuery({
    queryKey: catalogTaxonomyQueryKey,
    queryFn: fetchCatalogTaxonomy,
    staleTime: CATALOG_REFERENCE_STALE_MS,
  });
}

export function useCatalogReferencePrefetch(): () => void {
  const queryClient = useQueryClient();
  return useCallback(() => prefetchCatalogReferenceData(queryClient), [queryClient]);
}
