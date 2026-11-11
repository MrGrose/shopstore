import { describe, expect, it } from "vitest";

import {
  CATALOG_CARD_GALLERY_LIMIT,
  catalogGalleryCandidateKey,
  resolveCatalogCardGalleryCandidates,
  type CatalogProductCardData,
} from "./catalogProductTypes";

const product = (overrides: Partial<CatalogProductCardData> = {}): CatalogProductCardData => ({
  id: 1,
  title: "Racket",
  brand: "Babolat",
  sale_price: 1,
  regular_price: 1,
  ...overrides,
});

describe("resolveCatalogCardGalleryCandidates", () => {
  it("sorts by position, caps at 5, and prefers gallery over cover", () => {
    const candidates = resolveCatalogCardGalleryCandidates(
      product({
        image_url: "/media/products/cover.jpg",
        images: [
          { url: "/media/products/4.jpg", position: 4 },
          { url: "/media/products/1.jpg", position: 1 },
          { url: "/media/products/0.jpg", position: 0 },
          { url: "/media/products/5.jpg", position: 5 },
          { url: "/media/products/2.jpg", position: 2 },
          { url: "/media/products/3.jpg", position: 3 },
          { url: "/media/products/6.jpg", position: 6 },
        ],
      }),
    );
    expect(candidates).toHaveLength(CATALOG_CARD_GALLERY_LIMIT);
    expect(candidates.map((slide) => slide.url)).toEqual([
      "/media/products/0_600.jpg",
      "/media/products/1_600.jpg",
      "/media/products/2_600.jpg",
      "/media/products/3_600.jpg",
      "/media/products/4_600.jpg",
    ]);
    expect(candidates.every((slide) => slide.fallbackUrl === null)).toBe(true);
    expect(candidates[0]?.key).toBe(catalogGalleryCandidateKey({ url: "/media/products/0.jpg", position: 0 }));
  });

  it("falls back to cover when gallery is empty", () => {
    expect(
      resolveCatalogCardGalleryCandidates(product({ image_url: "/media/products/cover.jpg" })),
    ).toEqual([
      {
        key: "cover:/media/products/cover_600.jpg",
        url: "/media/products/cover_600.jpg",
        fallbackUrl: null,
      },
    ]);
  });

  it("uses compact variants on the compact card", () => {
    expect(
      resolveCatalogCardGalleryCandidates(
        product({ images: [{ url: "/media/products/0.jpg", position: 0 }] }),
        true,
      ),
    ).toEqual([
      {
        key: "0:/media/products/0.jpg",
        url: "/media/products/0_900.jpg",
        fallbackUrl: null,
      },
    ]);
  });

  it("applies preview size only to the managed url", () => {
    const [slide] = resolveCatalogCardGalleryCandidates(
      product({
        images: [
          {
            url: "https://cdn.shopstore.example/media/products/foo.jpg",
            fallback_url: "https://cdn.shopify.com/s/files/1/p.jpg",
            position: 0,
          },
        ],
      }),
    );
    expect(slide?.url).toBe("https://cdn.shopstore.example/media/products/foo_600.jpg");
    expect(slide?.fallbackUrl).toBe("https://cdn.shopify.com/s/files/1/p.jpg");
  });
});
