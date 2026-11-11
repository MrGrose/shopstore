import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { CatalogProductCardData } from "../app/components/catalog/catalogProductTypes";
import { userFacingApiErrorMessage } from "../lib/apiErrorMapper";
import { addCartItem, changeCartQty } from "../lib/storefront/cart";
import { invalidateCartQuery, syncCartQueryCache } from "./useCart";

type ToastSetter = (message: string | null) => void;

export function useCatalogCartActions(setToast: ToastSetter): {
  cartRefreshing: boolean;
  addToCart: (product: CatalogProductCardData, variantId?: number | null) => Promise<void>;
  changeCatalogCartQty: (
    product: CatalogProductCardData,
    nextQty: number,
    variantId?: number | null,
  ) => Promise<void>;
} {
  const queryClient = useQueryClient();
  const [cartRefreshing, setCartRefreshing] = useState(false);

  const addToCart = useCallback(
    async (product: CatalogProductCardData, variantId?: number | null) => {
      try {
        const cart = await addCartItem(product.id, variantId ?? null);
        syncCartQueryCache(queryClient, cart);
        setToast("Добавлено в корзину");
        window.setTimeout(() => setToast(null), 1400);
      } catch (e) {
        const message = userFacingApiErrorMessage(e, "Не удалось добавить в корзину");
        setToast(message);
        window.setTimeout(() => setToast(null), 2800);
        await invalidateCartQuery(queryClient);
      }
    },
    [queryClient, setToast],
  );

  const changeCatalogCartQty = useCallback(
    async (
      product: CatalogProductCardData,
      nextQty: number,
      variantId?: number | null,
    ) => {
      setCartRefreshing(true);
      try {
        const cart = await changeCartQty(product.id, nextQty, variantId ?? null);
        if (cart?.items) {
          syncCartQueryCache(queryClient, cart);
        } else {
          await invalidateCartQuery(queryClient);
        }
      } catch (e) {
        const message = userFacingApiErrorMessage(e, "Не удалось изменить количество");
        setToast(message);
        window.setTimeout(() => setToast(null), 2800);
        await invalidateCartQuery(queryClient);
      } finally {
        setCartRefreshing(false);
      }
    },
    [queryClient, setToast],
  );

  return { cartRefreshing, addToCart, changeCatalogCartQty };
}
