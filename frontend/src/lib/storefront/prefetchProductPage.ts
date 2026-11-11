let prefetchPromise: Promise<typeof import("../../app/pages/ProductPage")> | null = null;

/** Prefetch ProductPage JS chunk on catalog card hover/focus. */
export function prefetchProductPageChunk(): void {
  prefetchPromise ??= import("../../app/pages/ProductPage");
  void prefetchPromise;
}
