import { useQuery } from "@tanstack/react-query";

import {
  fetchCatalogSubcategories,
  type CatalogSubCategoryItem,
} from "../lib/storefront/catalog";

export const CATALOG_SUBCATEGORIES_STALE_MS = 5 * 60_000;
export const CATALOG_SUBCATEGORIES_REFETCH_ON_FOCUS = "always" as const;

export function catalogSubcategoriesQueryKey(
  topCategory: string,
  sub?: string,
  section?: string,
): readonly ["catalog", "subcategories", string, string, string] {
  return ["catalog", "subcategories", topCategory, sub ?? "", section ?? ""] as const;
}

export function useCatalogSubcategories(
  topCategory: string | null | undefined,
  sub?: string,
  section?: string,
  enabled = true,
): {
  subcategories: CatalogSubCategoryItem[] | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogSubCategoryItem[], Error>({
    queryKey: catalogSubcategoriesQueryKey(topCategory ?? "", sub, section),
    queryFn: () => fetchCatalogSubcategories(topCategory!, sub, section),
    enabled: enabled && Boolean(topCategory),
    staleTime: CATALOG_SUBCATEGORIES_STALE_MS,
    refetchOnWindowFocus: CATALOG_SUBCATEGORIES_REFETCH_ON_FOCUS,
  });

  return {
    subcategories: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
