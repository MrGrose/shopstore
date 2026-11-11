import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  resolveCatalogCategoryApiParams,
  fetchProducts,
  type CatalogProductListResponse,
} from "../lib/storefront/catalog";
import {
  catalogProductsInfiniteQueryKey,
  type CatalogFilterQueryOpts,
} from "../lib/storefront/catalogFilterQuery";

const CATALOG_PRODUCTS_STALE_MS = 30_000;

function buildProductsRequest(
  opts: CatalogFilterQueryOpts,
  page: number,
  pageSize: number,
) {
  return {
    page,
    page_size: pageSize,
    top_category: opts.topCategory ?? undefined,
    ...resolveCatalogCategoryApiParams(opts.sub, opts.type, opts.categoryUrlParams),
    brand: opts.brand || undefined,
    gender: opts.gender || undefined,
    color: opts.color || undefined,
    size: opts.size || undefined,
    price_min: opts.priceMin || undefined,
    price_max: opts.priceMax || undefined,
    q: opts.searchQ?.trim() || undefined,
    sort_price: opts.sortPrice || undefined,
  };
}

export function useProducts(
  opts: CatalogFilterQueryOpts,
  pageSize: number,
  enabled = true,
): {
  items: CatalogProductListResponse["items"];
  hasMore: boolean;
  isLoading: boolean;
  isFetching: boolean;
  isFetchingNextPage: boolean;
  isFetched: boolean;
  isPlaceholderData: boolean;
  error: Error | null;
  fetchNextPage: () => void;
} {
  const query = useInfiniteQuery<CatalogProductListResponse, Error>({
    queryKey: catalogProductsInfiniteQueryKey(opts, pageSize),
    queryFn: ({ pageParam }) =>
      fetchProducts(buildProductsRequest(opts, pageParam, pageSize)),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _pages, lastPageParam) =>
      lastPage.has_more ? lastPageParam + 1 : undefined,
    enabled: enabled && Boolean(opts.topCategory),
    staleTime: CATALOG_PRODUCTS_STALE_MS,
    placeholderData: keepPreviousData,
  });

  const items = useMemo(
    () => query.data?.pages.flatMap((page) => page.items ?? []) ?? [],
    [query.data],
  );

  return {
    items,
    hasMore: Boolean(query.hasNextPage),
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isFetchingNextPage: query.isFetchingNextPage,
    isFetched: query.isFetched,
    isPlaceholderData: query.isPlaceholderData,
    error: query.error,
    fetchNextPage: () => {
      void query.fetchNextPage();
    },
  };
}
