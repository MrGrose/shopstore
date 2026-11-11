import { isCatalogListingPath } from "./catalogNavigation";
import { storefrontBasename } from "./miniApp";

export const CATALOG_SCROLL_PRODUCT_ATTR = "data-catalog-product-id";

export type CatalogScrollSnapshot = {
  url: string;
  top: number;
  productId: number;
  itemCount: number;
};

let pendingRestore: CatalogScrollSnapshot | null = null;
/** Skip card enter-motion on the next POP catalog mount (Back/Forward from PDP). */
let skipCatalogEnterAnimation = false;

export function catalogLocationKey(pathname: string, search: string): string {
  const q = search.startsWith("?") ? search.slice(1) : search;
  return q ? `${pathname}?${q}` : pathname;
}

export function peekCatalogScrollSnapshot(): CatalogScrollSnapshot | null {
  return pendingRestore;
}

export function saveCatalogScrollSnapshot(snapshot: CatalogScrollSnapshot): void {
  pendingRestore = snapshot;
  skipCatalogEnterAnimation = true;
}

export function clearCatalogScrollSnapshot(): void {
  pendingRestore = null;
}

export function shouldSkipCatalogEnterAnimation(): boolean {
  return skipCatalogEnterAnimation;
}

export function clearSkipCatalogEnterAnimation(): void {
  skipCatalogEnterAnimation = false;
}

/** Pathname without Mini App basename (`/app`), for window.location checks. */
export function storefrontRoutePathFromWindow(): string {
  const pathname = window.location.pathname;
  const basename = storefrontBasename();
  return basename && (pathname === basename || pathname.startsWith(`${basename}/`))
    ? pathname.slice(basename.length) || "/"
    : pathname;
}

export function isCatalogProductRoutePath(pathname: string): boolean {
  return pathname.startsWith("/catalog/product/");
}

export function shouldPopProductBack(from: string | undefined): boolean {
  if (!from?.startsWith("/") || from.startsWith("/catalog/product/")) return false;
  const pathname = from.split("?")[0] ?? from;
  return isCatalogListingPath(pathname);
}

export function getCatalogScrollRoot(fromEl: HTMLElement | null): HTMLElement | Window {
  const main = fromEl?.closest("main");
  if (main) {
    const overflowY = window.getComputedStyle(main).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") return main;
  }
  return window;
}

export function readCatalogScrollTop(root: HTMLElement | Window): number {
  if (root === window) {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }
  return (root as HTMLElement).scrollTop;
}

export function writeCatalogScrollTop(root: HTMLElement | Window, top: number): void {
  if (root === window) {
    document.documentElement.scrollTop = top;
    document.body.scrollTop = top;
    return;
  }
  (root as HTMLElement).scrollTop = top;
}

export function restoreCatalogScroll(
  root: HTMLElement | Window,
  snapshot: CatalogScrollSnapshot,
): void {
  writeCatalogScrollTop(root, snapshot.top);
  if (catalogScrollRestoreApplied(root, snapshot)) return;
  const card = document.querySelector(
    `[${CATALOG_SCROLL_PRODUCT_ATTR}="${snapshot.productId}"]`,
  );
  if (card instanceof HTMLElement) {
    card.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
}

export function catalogScrollRestoreApplied(
  root: HTMLElement | Window,
  snapshot: CatalogScrollSnapshot,
): boolean {
  if (Math.abs(readCatalogScrollTop(root) - snapshot.top) <= 40) return true;
  const card = document.querySelector(
    `[${CATALOG_SCROLL_PRODUCT_ATTR}="${snapshot.productId}"]`,
  );
  if (!(card instanceof HTMLElement)) return false;
  const rect = card.getBoundingClientRect();
  return rect.top < window.innerHeight && rect.bottom > 0;
}

export function shouldZeroCatalogScrollOnUnmount(): boolean {
  return !isCatalogListingPath(storefrontRoutePathFromWindow());
}

/**
 * Catalog unmount cleanup must not zero a shared layout scroller (`main`) when
 * leaving for PDP — the same `main` hosts both routes in Mini App / mobile web.
 * PDP mounts with an explicit top scroll instead.
 */
export function shouldSkipUnmountScrollZero(
  root: HTMLElement | Window,
  routePath: string = storefrontRoutePathFromWindow(),
): boolean {
  return root !== window && isCatalogProductRoutePath(routePath);
}
