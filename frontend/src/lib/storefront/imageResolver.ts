import {
  IMAGE_RESOLVER_STRATEGY_CHAIN,
  type ImageContext,
  type ImageResolverStrategy,
} from "./imageResolver.strategies";

export type { ImageContext } from "./imageResolver.strategies";

export type ProductImageSource = {
  image_url?: string | null;
  image_urls?: Partial<Record<string, string>> | null;
};

export type AboveFoldLayout = {
  columns: number;
  priorityRows: number;
};

export type ImageLoadingAttrs = {
  loading: "eager" | "lazy";
  fetchPriority: "high" | "auto";
};

function isResolverDisabled(): boolean {
  return import.meta.env.VITE_IMAGE_RESOLVER === "0";
}

function extractRawUrl(
  input: ProductImageSource | string | null | undefined,
): string | null {
  if (input == null) return null;
  if (typeof input === "string") {
    const trimmed = input.trim();
    return trimmed || null;
  }
  const raw = input.image_url?.trim();
  return raw || null;
}

function extractImageUrls(
  input: ProductImageSource | string | null | undefined,
): Partial<Record<string, string>> | null {
  if (input == null || typeof input === "string") return null;
  return input.image_urls ?? null;
}

export function resolveProductImageUrl(
  input: ProductImageSource | string | null | undefined,
  context: ImageContext,
  strategies: readonly ImageResolverStrategy[] = IMAGE_RESOLVER_STRATEGY_CHAIN,
): string | null {
  const rawUrl = extractRawUrl(input);
  if (!rawUrl) return null;
  if (isResolverDisabled()) return rawUrl;

  const imageUrls = extractImageUrls(input);
  for (const strategy of strategies) {
    const resolved = strategy.resolve(rawUrl, context, imageUrls);
    if (resolved) return resolved;
  }
  return rawUrl;
}

export function isAboveFoldPriority(index: number, layout: AboveFoldLayout): boolean {
  if (index < 0) return false;
  const limit = layout.columns * layout.priorityRows;
  return index < limit;
}

export function resolveImageLoadingAttrs(priority: boolean): ImageLoadingAttrs {
  return priority
    ? { loading: "eager", fetchPriority: "high" }
    : { loading: "lazy", fetchPriority: "auto" };
}

export function resolveCatalogCardPreviewUrl(
  input: ProductImageSource | string | null | undefined,
): string | null {
  return resolveProductImageUrl(input, "catalog_card_compact");
}

/** Catalog→PDP preview from location.state — do not re-resolve (keeps 560 desktop cache). */
export function readPdpTransitionPreviewUrl(
  input: string | null | undefined,
): string | null {
  if (typeof input !== "string") return null;
  const trimmed = input.trim();
  return trimmed || null;
}

export function resolveLineItemThumbUrl(
  input: ProductImageSource | string | null | undefined,
): string | null {
  return resolveProductImageUrl(input, "line_item_thumb");
}
