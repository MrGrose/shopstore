import { describe, expect, it } from "vitest";
import {
  isAboveFoldPriority,
  resolveImageLoadingAttrs,
  readPdpTransitionPreviewUrl,
  resolveProductImageUrl,
  resolveCatalogCardPreviewUrl,
  resolveLineItemThumbUrl,
} from "./imageResolver";
import {
  apiVariantsStrategy,
  localMediaVariantStrategy,
  passthroughStrategy,
  urlParamTransformStrategy,
  type ImageContext,
} from "./imageResolver.strategies";

const API_SOURCE = {
  image_url: "https://cdn.example/original.jpg",
  image_urls: {
    card: "https://cdn.example/card.jpg",
    hero: "https://cdn.example/hero.jpg",
    thumb: "https://cdn.example/thumb.jpg",
  },
};

const TRANSFORM_SOURCE =
  "https://cdn.shopify.com/s/files/1/0001/products/padel.jpg?v=1234567890";

const PASSTHROUGH_SOURCE = "/media/products/local.jpg";
const LOCAL_ORIGINAL = "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg";

const CONTEXTS: ImageContext[] = [
  "catalog_card_desktop",
  "catalog_card_compact",
  "pdp_hero",
  "pdp_gallery_thumb",
  "line_item_thumb",
];

describe("resolveProductImageUrl strategies", () => {
  it("uses API variants when present", () => {
    const url = resolveProductImageUrl(API_SOURCE, "catalog_card_desktop", [
      apiVariantsStrategy,
      passthroughStrategy,
    ]);
    expect(url).toBe("https://cdn.example/card.jpg");
  });

  it("uses hero and thumb API variants per context", () => {
    expect(
      resolveProductImageUrl(API_SOURCE, "pdp_hero", [apiVariantsStrategy, passthroughStrategy]),
    ).toBe("https://cdn.example/hero.jpg");
    expect(
      resolveProductImageUrl(API_SOURCE, "line_item_thumb", [
        apiVariantsStrategy,
        passthroughStrategy,
      ]),
    ).toBe("https://cdn.example/thumb.jpg");
  });

  it("transforms URL-param-capable remote URLs", () => {
    const url = resolveProductImageUrl(TRANSFORM_SOURCE, "catalog_card_desktop", [
      urlParamTransformStrategy,
      passthroughStrategy,
    ]);
    expect(url).toContain("width=560");
    expect(url).toContain("cdn.shopify.com");
  });

  it("transforms width per context", () => {
    const desktop = resolveProductImageUrl(TRANSFORM_SOURCE, "catalog_card_desktop", [
      urlParamTransformStrategy,
      passthroughStrategy,
    ]);
    const thumb = resolveProductImageUrl(TRANSFORM_SOURCE, "line_item_thumb", [
      urlParamTransformStrategy,
      passthroughStrategy,
    ]);
    expect(desktop).toContain("width=560");
    expect(thumb).toContain("width=128");
  });

  it("falls back to passthrough for unsupported URLs", () => {
    expect(
      resolveProductImageUrl(PASSTHROUGH_SOURCE, "catalog_card_desktop", [
        urlParamTransformStrategy,
        passthroughStrategy,
      ]),
    ).toBe(PASSTHROUGH_SOURCE);
  });

  it("maps local media to existing _300/_600/_900 names", () => {
    expect(resolveProductImageUrl(LOCAL_ORIGINAL, "catalog_card_desktop")).toBe(
      "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_600.jpg",
    );
    expect(resolveProductImageUrl(LOCAL_ORIGINAL, "catalog_card_compact")).toBe(
      "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_900.jpg",
    );
    expect(resolveProductImageUrl(LOCAL_ORIGINAL, "pdp_hero")).toBe(
      "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_900.jpg",
    );
    expect(resolveProductImageUrl(LOCAL_ORIGINAL, "pdp_gallery_thumb")).toBe(
      "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg",
    );
    expect(resolveLineItemThumbUrl(LOCAL_ORIGINAL)).toBe(
      "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg",
    );
  });

  it("rewrites an already-suffixed local variant from the original stem", () => {
    const from600 = "/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_600.jpg";
    expect(
      resolveProductImageUrl(from600, "line_item_thumb", [localMediaVariantStrategy, passthroughStrategy]),
    ).toBe("/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_300.jpg");
  });

  it("does not rewrite remote http URLs as local media", () => {
    expect(resolveProductImageUrl("https://cdn.example/p.jpg", "catalog_card_desktop")).toBe(
      "https://cdn.example/p.jpg",
    );
  });

  it("resolves each ImageContext through default chain without throwing", () => {
    for (const context of CONTEXTS) {
      expect(resolveProductImageUrl(TRANSFORM_SOURCE, context)).toContain("width=");
    }
  });
});

describe("isAboveFoldPriority", () => {
  const desktop = { columns: 4, priorityRows: 1 };
  const compact = { columns: 2, priorityRows: 1 };

  it("marks desktop indices 0..3 as priority", () => {
    expect(isAboveFoldPriority(0, desktop)).toBe(true);
    expect(isAboveFoldPriority(3, desktop)).toBe(true);
    expect(isAboveFoldPriority(4, desktop)).toBe(false);
  });

  it("marks compact indices 0..1 as priority", () => {
    expect(isAboveFoldPriority(0, compact)).toBe(true);
    expect(isAboveFoldPriority(1, compact)).toBe(true);
    expect(isAboveFoldPriority(2, compact)).toBe(false);
  });

  it("handles edge product counts", () => {
    for (const index of [0, 1, 2, 3, 4, 5]) {
      const expected = index < 4;
      expect(isAboveFoldPriority(index, desktop)).toBe(expected);
    }
    expect(isAboveFoldPriority(0, { columns: 4, priorityRows: 1 })).toBe(true);
    expect(isAboveFoldPriority(0, { columns: 2, priorityRows: 1 })).toBe(true);
    expect(isAboveFoldPriority(1, { columns: 2, priorityRows: 1 })).toBe(true);
    expect(isAboveFoldPriority(2, { columns: 2, priorityRows: 1 })).toBe(false);
  });

  it("returns false for negative index", () => {
    expect(isAboveFoldPriority(-1, desktop)).toBe(false);
  });
});

describe("resolveImageLoadingAttrs", () => {
  it("maps priority to eager/high", () => {
    expect(resolveImageLoadingAttrs(true)).toEqual({
      loading: "eager",
      fetchPriority: "high",
    });
  });

  it("maps non-priority to lazy/auto", () => {
    expect(resolveImageLoadingAttrs(false)).toEqual({
      loading: "lazy",
      fetchPriority: "auto",
    });
  });
});

describe("readPdpTransitionPreviewUrl", () => {
  it("passes through an already-resolved desktop card URL without compact rewrite", () => {
    const src = "https://cdn.shopify.com/s/files/x.jpg?width=560";
    expect(readPdpTransitionPreviewUrl(src)).toBe(src);
    expect(resolveCatalogCardPreviewUrl(src)).toContain("width=720");
  });

  it("returns null for empty preview", () => {
    expect(readPdpTransitionPreviewUrl(null)).toBeNull();
    expect(readPdpTransitionPreviewUrl("  ")).toBeNull();
  });

  it("derives preview variants from absolute public media origin URLs", () => {
    const cdnOriginal =
      "https://media.example.com/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg";
    expect(
      resolveProductImageUrl(cdnOriginal, "catalog_card_desktop"),
    ).toBe(
      "https://media.example.com/media/products/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_600.jpg",
    );
  });

});
