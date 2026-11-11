import { useQuery } from "@tanstack/react-query";

import {
  fetchCatalogLabels,
  type CatalogLabelsConfig,
} from "../lib/storefront/catalogLabels";

export const catalogLabelsQueryKey = ["catalog", "labels"] as const;

const CATALOG_REFERENCE_STALE_MS = 5 * 60_000;

export function useCatalogLabels(): {
  labels: CatalogLabelsConfig | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogLabelsConfig, Error>({
    queryKey: catalogLabelsQueryKey,
    queryFn: fetchCatalogLabels,
    staleTime: CATALOG_REFERENCE_STALE_MS,
  });

  return {
    labels: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
