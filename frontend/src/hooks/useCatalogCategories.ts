import { useQuery } from "@tanstack/react-query";

import { fetchCategories, type CatalogLabelItem } from "../lib/storefront/catalog";

export function catalogCategoriesQueryKey(
  topCategory: string,
): readonly ["catalog", "categories", string] {
  return ["catalog", "categories", topCategory] as const;
}

const CATALOG_CATEGORIES_STALE_MS = 60_000;

export function useCatalogCategories(
  topCategory: string | null | undefined,
  enabled = true,
): {
  categories: CatalogLabelItem[] | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogLabelItem[], Error>({
    queryKey: catalogCategoriesQueryKey(topCategory ?? ""),
    queryFn: () => fetchCategories(topCategory!),
    enabled: enabled && Boolean(topCategory),
    staleTime: CATALOG_CATEGORIES_STALE_MS,
  });

  return {
    categories: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
