import { useEffect, useLayoutEffect, useRef } from "react";
import { useNavigationType } from "react-router";

import { getCatalogCartItem } from "../../../lib/storefront/cart";
import type { CartLine } from "../../../lib/storefront/cart";
import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";
import { isAboveFoldPriority } from "../../../lib/storefront/imageResolver";
import { CatalogProductCard } from "./CatalogProductCard";
import type { CatalogProductCardData } from "./catalogProductTypes";
import {
  clearSkipCatalogEnterAnimation,
  shouldSkipCatalogEnterAnimation,
} from "../../../lib/storefront/catalogScrollRestore";

export type CatalogProductListProps = {
  items: CatalogProductCardData[];
  pageSize: number;
  compact: boolean;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  showStaleGrid: boolean;
  productsErrorMessage: string | null;
  productsFetched: boolean;
  searchQ: string;
  cartItems: CartLine[];
  cartRefreshing: boolean;
  onOpen: (id: number, previewImageUrl?: string | null) => void;
  onAddToCart: (product: CatalogProductCardData, variantId?: number | null) => Promise<void>;
  onChangeCartQty: (
    product: CatalogProductCardData,
    nextQty: number,
    variantId?: number | null,
  ) => void;
  onLoadMore: () => void;
};

export function CatalogProductList({
  items,
  pageSize,
  compact,
  loading,
  loadingMore,
  hasMore,
  showStaleGrid,
  productsErrorMessage,
  productsFetched,
  searchQ,
  cartItems,
  cartRefreshing,
  onOpen,
  onAddToCart,
  onChangeCartQty,
  onLoadMore,
}: CatalogProductListProps) {
  const navType = useNavigationType();
  // Read once on mount. Only a POP (Back/Forward) may skip enter-motion.
  const skipEnterAnimation = useRef(
    navType === "POP" && shouldSkipCatalogEnterAnimation(),
  ).current;

  useLayoutEffect(() => {
    // PUSH/REPLACE must play. Drop a leftover flag without treating it as a skip.
    if (navType === "POP") return;
    clearSkipCatalogEnterAnimation();
  }, [navType]);

  useEffect(() => {
    if (!skipEnterAnimation) return;
    // Defer clear so StrictMode mount → cleanup → remount still sees the flag.
    const id = window.setTimeout(() => {
      clearSkipCatalogEnterAnimation();
    }, 0);
    return () => window.clearTimeout(id);
  }, [skipEnterAnimation]);

  const showInitialLoading = loading && items.length === 0;
  const showEmptyProducts =
    productsFetched && items.length === 0 && !loading && !loadingMore;

  const handleLoadMore = () => {
    if (loadingMore || loading) return;
    onLoadMore();
  };

  return (
    <>
      <div className="relative">
        {showStaleGrid ? (
          <div
            className="pointer-events-none absolute inset-0 z-10 rounded-[var(--sp-radius-card)] bg-sp-bg/35"
            aria-hidden
          />
        ) : null}
        <div
          className={
            compact
              ? "grid grid-cols-2 items-stretch gap-3 auto-rows-auto"
              : "grid grid-cols-1 items-start sm:grid-cols-2 lg:grid-cols-4 gap-6 auto-rows-auto"
          }
          style={{
            opacity: showStaleGrid ? 0.55 : 1,
            transition: "opacity 0.15s ease",
          }}
        >
          {showInitialLoading ? (
            <div className="text-sp-text-secondary">Загрузка…</div>
          ) : productsErrorMessage && items.length === 0 && !loading && !loadingMore ? (
            <div className="text-red-500">
              Не удалось загрузить товары: {productsErrorMessage}
            </div>
          ) : items.length === 0 && showEmptyProducts ? (
            <div className="text-sp-text-secondary">
              {searchQ.trim()
                ? `По запросу «${searchQ.trim()}» ничего не найдено.`
                : "Товары не найдены."}
            </div>
          ) : (
            items.map((product, i) => (
              <CatalogProductCard
                key={product.id}
                product={product}
                animationIndex={i % pageSize}
                cartLine={getCatalogCartItem(cartItems, product.id)}
                cartBusy={cartRefreshing}
                onOpen={onOpen}
                onAddToCart={(p) => onAddToCart(p)}
                onChangeCartQty={(p, qty, vid) => void onChangeCartQty(p, qty, vid)}
                compact={compact}
                skipEnterAnimation={skipEnterAnimation}
                imagePriority={isAboveFoldPriority(i, {
                  columns: compact ? 2 : 4,
                  priorityRows: 1,
                })}
              />
            ))
          )}
        </div>
      </div>

      {hasMore ? (
        <div className={compact ? "mt-4 flex justify-center" : "mt-12 flex justify-center"}>
          <button
            type="button"
            disabled={loadingMore || loading}
            aria-busy={loadingMore}
            onClick={handleLoadMore}
            className={
              compact
                ? `${miniAppPillClass(true)} min-w-[9.5rem] px-4 disabled:opacity-60`
                : `${miniAppPillClass(true)} min-w-[11rem] px-4 py-2.5 text-[14px] disabled:opacity-60 hover:opacity-90`
            }
          >
            <span className={loadingMore ? "opacity-70" : undefined}>
              {compact ? "Показать ещё" : "ПОКАЗАТЬ ЕЩЁ"}
            </span>
          </button>
        </div>
      ) : null}
    </>
  );
}
