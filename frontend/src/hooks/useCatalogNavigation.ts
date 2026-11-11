import { useQuery } from "@tanstack/react-query";

import {
  fetchCatalogNavigation,
  type CatalogNavigation,
  type CatalogNavigationParams,
} from "../lib/storefront/catalog";

export const CATALOG_NAVIGATION_STALE_MS = 60_000;
export const CATALOG_NAVIGATION_REFETCH_ON_FOCUS = "always" as const;

export function catalogNavigationQueryKey(
  params: CatalogNavigationParams,
): readonly ["catalog", "navigation", string] {
  const qs = new URLSearchParams({ top_category: params.top_category });
  if (params.section?.trim()) qs.set("section", params.section.trim());
  if (params.node?.trim()) qs.set("node", params.node.trim());
  if (params.sub?.trim()) qs.set("sub", params.sub.trim());
  if (params.category_type?.trim()) qs.set("category_type", params.category_type.trim());
  return ["catalog", "navigation", qs.toString()] as const;
}

export type CatalogNavigationScope = {
  topCategory: string | null;
  sub: string;
  productType: string;
};

function buildNavigationParams(scope: CatalogNavigationScope): CatalogNavigationParams | null {
  if (!scope.topCategory) return null;
  const sub = scope.sub.trim();
  const productType = scope.productType.trim();
  return {
    top_category: scope.topCategory,
    sub: sub || undefined,
    section: sub || undefined,
    category_type: productType || undefined,
    node: productType || undefined,
  };
}

export function useCatalogNavigation(
  scope: CatalogNavigationScope,
  enabled = true,
): {
  navigation: CatalogNavigation | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const params = buildNavigationParams(scope);
  const query = useQuery<CatalogNavigation, Error>({
    queryKey: params ? catalogNavigationQueryKey(params) : ["catalog", "navigation", "disabled"],
    queryFn: () => fetchCatalogNavigation(params!),
    enabled: enabled && params !== null,
    staleTime: CATALOG_NAVIGATION_STALE_MS,
    refetchOnWindowFocus: CATALOG_NAVIGATION_REFETCH_ON_FOCUS,
  });

  return {
    navigation: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
