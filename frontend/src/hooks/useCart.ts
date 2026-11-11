import { useQuery, type QueryClient } from "@tanstack/react-query";

import {
  broadcastCartCount,
  cartTotalQty,
  fetchCart,
  type CartMe,
} from "../lib/storefront/cart";

export const cartQueryKey = ["cart", "me"] as const;

export function syncCartQueryCache(
  queryClient: QueryClient,
  cart: CartMe | null | undefined,
): void {
  const next = cart ?? { items: [] };
  queryClient.setQueryData(cartQueryKey, next);
  broadcastCartCount(cartTotalQty(next.items));
}

export async function invalidateCartQuery(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: cartQueryKey });
  await queryClient.fetchQuery({
    queryKey: cartQueryKey,
    queryFn: fetchCart,
  });
}

export function useCart(): {
  cart: CartMe | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refetch: () => Promise<unknown>;
} {
  const query = useQuery<CartMe, Error>({
    queryKey: cartQueryKey,
    queryFn: fetchCart,
  });

  return {
    cart: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    refetch: query.refetch,
  };
}
