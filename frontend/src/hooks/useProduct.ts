import { useQuery } from "@tanstack/react-query";

import { fetchProduct } from "../lib/storefront/catalog";

const PRODUCT_STALE_MS = 60_000;

export type CatalogProductDetail = Awaited<ReturnType<typeof fetchProduct>>;

export function productQueryKey(productId: number): readonly ["catalog", "product", number] {
  return ["catalog", "product", productId] as const;
}

export function useProduct(
  productId: number,
  enabled = true,
): {
  product: CatalogProductDetail | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
} {
  const query = useQuery<CatalogProductDetail, Error>({
    queryKey: productQueryKey(productId),
    queryFn: () => fetchProduct(productId),
    enabled: enabled && Number.isFinite(productId) && productId > 0,
    staleTime: PRODUCT_STALE_MS,
  });

  return {
    product: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
  };
}
