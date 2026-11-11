import { useLayoutEffect } from "react";
import { useLocation, useNavigationType } from "react-router";

import { isCatalogListingPath } from "../lib/storefront/catalogNavigation";
import {
  catalogLocationKey,
  catalogScrollRestoreApplied,
  clearCatalogScrollSnapshot,
  clearSkipCatalogEnterAnimation,
  getCatalogScrollRoot,
  peekCatalogScrollSnapshot,
  restoreCatalogScroll,
  shouldSkipUnmountScrollZero,
  shouldZeroCatalogScrollOnUnmount,
  writeCatalogScrollTop,
} from "../lib/storefront/catalogScrollRestore";

export type UseCatalogScrollRestoreArgs = {
  items: readonly { id: number }[];
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  productsFetched: boolean;
  fetchNextPage: () => void;
};

export function useCatalogScrollRestore({
  items,
  hasMore,
  loading,
  loadingMore,
  productsFetched,
  fetchNextPage,
}: UseCatalogScrollRestoreArgs): void {
  const { pathname, search } = useLocation();
  const navType = useNavigationType();
  const url = catalogLocationKey(pathname, search);
  const itemCount = items.length;
  const isListing = isCatalogListingPath(pathname);

  useLayoutEffect(() => {
    return () => {
      if (!shouldZeroCatalogScrollOnUnmount()) return;
      const root = getCatalogScrollRoot(document.querySelector("main"));
      // Shared Mini App / mobile `main`: leave scroll for PDP lifecycle (explicit top there).
      if (shouldSkipUnmountScrollZero(root)) return;
      writeCatalogScrollTop(root, 0);
    };
  }, []);

  // PUSH entry only: zero once per listing URL visit, never on data rerenders.
  useLayoutEffect(() => {
    if (!isListing || navType !== "PUSH") return;
    clearCatalogScrollSnapshot();
    clearSkipCatalogEnterAnimation();
    writeCatalogScrollTop(getCatalogScrollRoot(document.getElementById("products")), 0);
  }, [isListing, navType, url]);

  useLayoutEffect(() => {
    if (!isListing || navType !== "POP") return;

    const snapshot = peekCatalogScrollSnapshot();
    if (!snapshot || snapshot.url !== url) return;
    if (!productsFetched && itemCount === 0) return;

    if (itemCount < snapshot.itemCount && hasMore && !loading && !loadingMore) {
      fetchNextPage();
      return;
    }

    const apply = (): boolean => {
      const root = getCatalogScrollRoot(document.getElementById("products"));
      restoreCatalogScroll(root, snapshot);
      const ok = catalogScrollRestoreApplied(root, snapshot);
      // One-shot: clear only after the target position is actually applied.
      if (ok) clearCatalogScrollSnapshot();
      return ok;
    };

    if (apply()) return;

    const node = document.getElementById("products");
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (apply()) observer.disconnect();
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [
    fetchNextPage,
    hasMore,
    isListing,
    itemCount,
    loading,
    loadingMore,
    navType,
    productsFetched,
    url,
  ]);
}
