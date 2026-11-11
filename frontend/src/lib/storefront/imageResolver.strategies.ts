export type ImageContext =
  | "catalog_card_desktop"
  | "catalog_card_compact"
  | "pdp_hero"
  | "pdp_gallery_thumb"
  | "line_item_thumb";

/** Target request width per display context (≤2× typical CSS width). */
export const IMAGE_CONTEXT_TARGET_WIDTH: Record<ImageContext, number> = {
  catalog_card_desktop: 560,
  catalog_card_compact: 720,
  pdp_hero: 1400,
  pdp_gallery_thumb: 160,
  line_item_thumb: 128,
};

const CONTEXT_API_VARIANT_KEYS: Record<ImageContext, readonly string[]> = {
  catalog_card_desktop: ["card", "catalog_card_desktop"],
  catalog_card_compact: ["card", "catalog_card_compact", "card_compact"],
  pdp_hero: ["hero", "pdp_hero"],
  pdp_gallery_thumb: ["thumb", "pdp_gallery_thumb", "gallery_thumb"],
  line_item_thumb: ["thumb", "line_item_thumb"],
};

export type ImageResolverStrategy = {
  name: string;
  resolve: (
    rawUrl: string,
    context: ImageContext,
    imageUrls?: Partial<Record<string, string>> | null,
  ) => string | null;
};

export const passthroughStrategy: ImageResolverStrategy = {
  name: "passthrough",
  resolve: (rawUrl) => rawUrl,
};

export const apiVariantsStrategy: ImageResolverStrategy = {
  name: "api_variants",
  resolve: (_rawUrl, context, imageUrls) => {
    if (!imageUrls) return null;
    for (const key of CONTEXT_API_VARIANT_KEYS[context]) {
      const candidate = imageUrls[key];
      if (candidate?.trim()) return candidate.trim();
    }
    return null;
  },
};

function canTransformUrlParam(url: string): boolean {
  if (!url.startsWith("http://") && !url.startsWith("https://")) return false;
  try {
    const parsed = new URL(url);
    if (parsed.searchParams.has("width")) return true;
    const host = parsed.hostname.toLowerCase();
    return host.includes("shopify") || host.endsWith("shopifycdn.com");
  } catch {
    return false;
  }
}

function transformUrlWidth(url: string, width: number): string {
  try {
    const parsed = new URL(url);
    parsed.searchParams.set("width", String(width));
    return parsed.toString();
  } catch {
    return url;
  }
}

export const urlParamTransformStrategy: ImageResolverStrategy = {
  name: "url_transform",
  resolve: (rawUrl, context) => {
    if (!canTransformUrlParam(rawUrl)) return null;
    const width = IMAGE_CONTEXT_TARGET_WIDTH[context];
    return transformUrlWidth(rawUrl, width);
  },
};

const LOCAL_MEDIA_PREFIX = "/media/products/";
const PREVIEW_SIZES = [300, 600, 900] as const;

function previewSizeForWidth(targetWidth: number): (typeof PREVIEW_SIZES)[number] {
  if (targetWidth <= 300) return 300;
  if (targetWidth <= 600) return 600;
  return 900;
}

function localMediaPathname(url: string): { origin: string; dir: string; name: string } | null {
  let pathname = url;
  let origin = "";
  if (url.startsWith("http://") || url.startsWith("https://")) {
    try {
      const parsed = new URL(url);
      pathname = parsed.pathname;
      origin = parsed.origin;
    } catch {
      return null;
    }
  }
  if (!pathname.startsWith(LOCAL_MEDIA_PREFIX)) return null;
  const name = pathname.slice(LOCAL_MEDIA_PREFIX.length);
  if (!name || name.includes("/")) return null;
  return { origin, dir: LOCAL_MEDIA_PREFIX, name };
}

function originalLocalFileName(name: string): string {
  const dot = name.lastIndexOf(".");
  const stem = dot >= 0 ? name.slice(0, dot) : name;
  const suffix = dot >= 0 ? name.slice(dot) : "";
  for (const size of PREVIEW_SIZES) {
    const tag = `_${size}`;
    if (stem.endsWith(tag)) return `${stem.slice(0, -tag.length)}${suffix}`;
  }
  return name;
}

export const localMediaVariantStrategy: ImageResolverStrategy = {
  name: "local_media_variant",
  resolve: (rawUrl, context) => {
    const parsed = localMediaPathname(rawUrl);
    if (!parsed) return null;
    const original = originalLocalFileName(parsed.name);
    const size = previewSizeForWidth(IMAGE_CONTEXT_TARGET_WIDTH[context]);
    const dot = original.lastIndexOf(".");
    const stem = dot >= 0 ? original.slice(0, dot) : original;
    const suffix = dot >= 0 ? original.slice(dot) : "";
    return `${parsed.origin}${parsed.dir}${stem}_${size}${suffix}`;
  },
};

export const IMAGE_RESOLVER_STRATEGY_CHAIN: readonly ImageResolverStrategy[] = [
  apiVariantsStrategy,
  localMediaVariantStrategy,
  urlParamTransformStrategy,
  passthroughStrategy,
];
