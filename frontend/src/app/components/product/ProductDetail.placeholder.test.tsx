import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";

import { resolveProductImageUrl } from "../../../lib/storefront/imageResolver";
import { PRODUCT_PLACEHOLDER } from "../../../lib/storefront/productPlaceholder";
import { ProductDetail, type ProductDetailData } from "./ProductDetail";

beforeEach(() => {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("offline");
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function product(overrides: Partial<ProductDetailData> = {}): ProductDetailData {
  return {
    id: 7,
    title: "Shirt",
    brand: "Adidas",
    sale_price: 1000,
    ...overrides,
  };
}

function renderDetail(item: ProductDetailData) {
  return render(
    <MemoryRouter>
      <ProductDetail
        product={item}
        cartQty={0}
        cartBusy={false}
        onAddToCart={async () => undefined}
        onChangeQty={async () => undefined}
        variantConstraintPreset={[]}
      />
    </MemoryRouter>,
  );
}

function heroImg() {
  return document.querySelector('[data-pdp-hero="image"]');
}

function hero() {
  return heroImg();
}

function gallerySlideKey(position: number, url: string) {
  return `${position}:${url}`;
}

function slideByKey(position: number, url: string) {
  return document.querySelector(`[data-pdp-gallery-key="${gallerySlideKey(position, url)}"]`);
}

function exhaustImage(node: Element | null | undefined) {
  if (!node) throw new Error("missing image node");
  fireEvent.error(node);
  fireEvent.error(node);
}

function thumbs() {
  return document.querySelectorAll('[data-pdp-thumb]');
}

function thumbRow() {
  return document.querySelector('[data-pdp-thumb-row="true"]');
}

function expectThumbRowHidden() {
  const row = thumbRow();
  expect(row?.classList.contains("invisible")).toBe(true);
  expect(row?.classList.contains("visible")).toBe(false);
}

function expectThumbRowVisible() {
  const row = thumbRow();
  expect(row?.classList.contains("visible")).toBe(true);
  expect(row?.classList.contains("invisible")).toBe(false);
}

function placeholderEmptyState() {
  return document.querySelectorAll('[data-pdp-placeholder="true"]');
}

function fourPhotoProduct(extra: Partial<ProductDetailData> = {}) {
  return product({
    images: [0, 1, 2, 3].map((position) => ({
      id: position + 1,
      url: `/media/products/${position}.jpg`,
      position,
      fallback_url: "https://cdn.shopify.com/s/files/1/x.jpg",
    })),
    ...extra,
  });
}

describe("ProductDetail image placeholder", () => {
  it("scenario D: shows one placeholder and no thumbnails when there are no images", () => {
    const item = product();
    renderDetail(item);
    expect(hero()?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
    expect(hero()?.getAttribute("data-pdp-placeholder")).toBe("true");
    expect(thumbs()).toHaveLength(0);
    expect(placeholderEmptyState()).toHaveLength(1);
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
  });

  it("keeps the managed image when it loads", () => {
    renderDetail(
      product({
        images: [{ id: 1, url: "/media/products/ok.jpg", position: 0 }],
      }),
    );
    expect(hero()?.getAttribute("src")).toBe("/media/products/ok_900.jpg");
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
    expect(placeholderEmptyState()).toHaveLength(0);
  });

  it("scenario C: uses the supplier image when the managed image fails", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/p.jpg";
    renderDetail(
      product({
        images: [
          { id: 1, url: "/media/products/broken.jpg", position: 0, fallback_url: fallback },
        ],
      }),
    );
    fireEvent.error(hero() as Element);
    expect(hero()?.getAttribute("src")).toBe(resolveProductImageUrl(fallback, "pdp_hero"));
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
    expect(placeholderEmptyState()).toHaveLength(0);
  });

  it("shows one empty-state placeholder when the only image is exhausted", () => {
    const item = product({
      images: [
        {
          id: 1,
          url: "/media/products/broken.jpg",
          position: 0,
          fallback_url: "https://cdn.shopify.com/s/files/1/p.jpg",
        },
      ],
    });
    renderDetail(item);
    exhaustImage(hero());
    expect(hero()?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
    expect(hero()?.getAttribute("data-pdp-placeholder")).toBe("true");
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
    expect(thumbs()).toHaveLength(0);
  });
});

describe("ProductDetail available gallery", () => {
  it("scenario A: removes all exhausted slides and shows one placeholder without placeholder thumbnails", () => {
    const item = fourPhotoProduct({ sport_type: "tennis" });
    renderDetail(item);
    for (const position of [0, 1, 2, 3]) {
      exhaustImage(slideByKey(position, `/media/products/${position}.jpg`));
    }
    expect(document.querySelectorAll("[data-pdp-gallery-key]")).toHaveLength(0);
    expect(thumbs()).toHaveLength(0);
    expect(placeholderEmptyState()).toHaveLength(1);
    expect(hero()?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
  });

  it("scenario B: keeps only available slides and thumbnails when some images exhaust", () => {
    renderDetail(fourPhotoProduct({ sport_type: "running" }));
    exhaustImage(slideByKey(1, "/media/products/1.jpg"));
    exhaustImage(slideByKey(3, "/media/products/3.jpg"));
    expect(thumbs()).toHaveLength(2);
    expect(document.querySelectorAll("[data-pdp-gallery-key]")).toHaveLength(3);
    expect(placeholderEmptyState()).toHaveLength(0);
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
  });

  it("never uses category placeholder src on gallery slide elements", () => {
    const item = fourPhotoProduct({ sport_type: "tennis" });
    const categoryPlaceholder = PRODUCT_PLACEHOLDER;
    renderDetail(item);
    for (const node of document.querySelectorAll("[data-pdp-gallery-key]")) {
      expect(node.getAttribute("src")).not.toBe(categoryPlaceholder);
    }
    exhaustImage(slideByKey(2, "/media/products/2.jpg"));
    for (const node of document.querySelectorAll("[data-pdp-gallery-key]")) {
      expect(node.getAttribute("src")).not.toBe(categoryPlaceholder);
    }
  });
});

function thumbImage(position: number, url: string) {
  return document.querySelector(
    `[data-pdp-thumb-image="true"][data-pdp-gallery-key="${gallerySlideKey(position, url)}"]`,
  );
}

function thumbSkeletons() {
  return document.querySelectorAll("[data-pdp-thumb] [data-slot='skeleton']");
}

describe("ProductDetail gallery thumbnails", () => {
  it("mounts thumbnails before the hero loads", () => {
    renderDetail(fourPhotoProduct());
    expect(hero()).toBeTruthy();
    expect(thumbs()).toHaveLength(4);
  });

  it("shows a skeleton and hides the image until the thumbnail loads", () => {
    renderDetail(fourPhotoProduct());
    expectThumbRowHidden();
    expect(thumbSkeletons()).toHaveLength(4);
    for (const position of [0, 1, 2, 3]) {
      const image = thumbImage(position, `/media/products/${position}.jpg`);
      expect(image?.className).toContain("opacity-0");
      expect(image?.getAttribute("src")).toBe(`/media/products/${position}_300.jpg`);
    }
  });

  it("keeps the skeleton while managed thumb falls back to supplier", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/p.jpg";
    renderDetail(
      product({
        images: [
          { id: 1, url: "/media/products/broken.jpg", position: 0, fallback_url: fallback },
          { id: 2, url: "/media/products/ok.jpg", position: 1 },
        ],
      }),
    );
    const broken = thumbImage(0, "/media/products/broken.jpg");
    fireEvent.error(broken as Element);
    expect(thumbs()).toHaveLength(2);
    expect(broken?.getAttribute("src")).toBe(resolveProductImageUrl(fallback, "pdp_gallery_thumb"));
    expect(broken?.className).toContain("opacity-0");
    expect(thumbSkeletons()).toHaveLength(2);
    expectThumbRowHidden();
  });

  it("reveals the thumbnail image after supplier load", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/p.jpg";
    renderDetail(
      product({
        images: [
          { id: 1, url: "/media/products/broken.jpg", position: 0, fallback_url: fallback },
          { id: 2, url: "/media/products/ok.jpg", position: 1 },
        ],
      }),
    );
    const broken = thumbImage(0, "/media/products/broken.jpg");
    fireEvent.error(broken as Element);
    expectThumbRowHidden();
    fireEvent.load(broken as Element);
    expectThumbRowVisible();
    expect(broken?.className).not.toContain("opacity-0");
    expect(broken?.closest("[data-pdp-thumb]")?.querySelector("[data-slot='skeleton']")).toBeNull();
    expect(thumbImage(1, "/media/products/ok.jpg")?.className).toContain("opacity-0");
  });

  it("shows a cached thumbnail without waiting for a load event", () => {
    const completeSpy = vi
      .spyOn(HTMLImageElement.prototype, "complete", "get")
      .mockReturnValue(true);
    const widthSpy = vi
      .spyOn(HTMLImageElement.prototype, "naturalWidth", "get")
      .mockReturnValue(120);
    try {
      renderDetail(fourPhotoProduct());
      expect(thumbs()).toHaveLength(4);
      expectThumbRowVisible();
      expect(thumbSkeletons()).toHaveLength(0);
      for (const position of [0, 1, 2, 3]) {
        expect(thumbImage(position, `/media/products/${position}.jpg`)?.className).not.toContain(
          "opacity-0",
        );
      }
    } finally {
      completeSpy.mockRestore();
      widthSpy.mockRestore();
    }
  });

  it("removes a thumbnail when managed and supplier both fail", () => {
    renderDetail(fourPhotoProduct());
    const node = thumbImage(1, "/media/products/1.jpg");
    fireEvent.error(node as Element);
    fireEvent.error(node as Element);
    expect(thumbImage(1, "/media/products/1.jpg")).toBeNull();
    expect(thumbs()).toHaveLength(3);
    expect(placeholderEmptyState()).toHaveLength(0);
  });

  it("shows the row after a later thumbnail loads when the first one fails", () => {
    renderDetail(
      product({
        images: [0, 1, 2].map((position) => ({
          id: position + 1,
          url: `/media/products/${position}.jpg`,
          position,
          fallback_url: "https://cdn.shopify.com/s/files/1/x.jpg",
        })),
      }),
    );
    expectThumbRowHidden();
    exhaustImage(thumbImage(0, "/media/products/0.jpg"));
    expect(thumbs()).toHaveLength(2);
    expectThumbRowHidden();
    fireEvent.load(thumbImage(1, "/media/products/1.jpg") as Element);
    expectThumbRowVisible();
  });

  it("hides the row again when the only loaded thumbnail is exhausted", () => {
    renderDetail(
      product({
        images: [0, 1, 2].map((position) => ({
          id: position + 1,
          url: `/media/products/${position}.jpg`,
          position,
          fallback_url: "https://cdn.shopify.com/s/files/1/x.jpg",
        })),
      }),
    );
    fireEvent.load(thumbImage(0, "/media/products/0.jpg") as Element);
    expectThumbRowVisible();
    exhaustImage(thumbImage(0, "/media/products/0.jpg"));
    expect(thumbImage(0, "/media/products/0.jpg")).toBeNull();
    expect(thumbs()).toHaveLength(2);
    expectThumbRowHidden();
  });

  it("does not wait for the hero before mounting thumbnails", () => {
    renderDetail(fourPhotoProduct());
    expect(hero()?.className).toContain("opacity-0");
    expect(hero()?.getAttribute("src")).toBe("/media/products/0_900.jpg");
    expectThumbRowHidden();
    expect(thumbs()).toHaveLength(4);
    expect(thumbImage(0, "/media/products/0.jpg")?.getAttribute("src")).toBe(
      "/media/products/0_300.jpg",
    );
  });

  it("keeps loaded and pending thumbnails stable when the gallery index changes", () => {
    renderDetail(fourPhotoProduct());
    fireEvent.load(thumbImage(0, "/media/products/0.jpg") as Element);
    expectThumbRowVisible();
    fireEvent.click(thumbs()[2] as Element);
    expectThumbRowVisible();
    expect(thumbs()).toHaveLength(4);
    expect(heroImg()?.dataset.pdpGalleryKey).toBe("2:/media/products/2.jpg");
    expect(thumbImage(0, "/media/products/0.jpg")?.className).not.toContain("opacity-0");
    expect(thumbImage(2, "/media/products/2.jpg")?.className).toContain("opacity-0");
    expect(thumbImage(0, "/media/products/0.jpg")?.closest("[data-pdp-thumb]")?.querySelector(
      "[data-slot='skeleton']",
    )).toBeNull();
    expect(thumbSkeletons()).toHaveLength(3);
  });

  it("still shows one placeholder and no thumbnails when every slide is exhausted", () => {
    const item = fourPhotoProduct({ sport_type: "tennis" });
    renderDetail(item);
    expect(thumbs()).toHaveLength(4);
    expectThumbRowHidden();
    for (const position of [0, 1, 2, 3]) {
      exhaustImage(slideByKey(position, `/media/products/${position}.jpg`));
    }
    expect(thumbs()).toHaveLength(0);
    expect(thumbRow()).toBeNull();
    expect(placeholderEmptyState()).toHaveLength(1);
    expect(hero()?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
  });
});

function heroFrameSkeleton() {
  return document.querySelector('[data-pdp-hero="frame"] [data-slot="skeleton"]');
}

describe("ProductDetail hero loading", () => {
  it("hides the hero image behind a skeleton until it loads", () => {
    renderDetail(
      product({
        images: [
          { id: 1, url: "/media/products/ok.jpg", alt: "P000000456120300.jpg", position: 0 },
        ],
      }),
    );
    expect(heroFrameSkeleton()).toBeTruthy();
    expect(hero()?.className).toContain("opacity-0");
    expect(hero()?.getAttribute("alt")).toBe("P000000456120300.jpg");
  });

  it("keeps the hero skeleton from a managed error until the supplier image loads", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/p.jpg";
    renderDetail(
      product({
        images: [
          {
            id: 1,
            url: "/media/products/broken.jpg",
            alt: "P000000456120300.jpg",
            position: 0,
            fallback_url: fallback,
          },
        ],
      }),
    );
    fireEvent.error(hero() as Element);
    expect(hero()?.getAttribute("src")).toBe(resolveProductImageUrl(fallback, "pdp_hero"));
    expect(hero()?.className).toContain("opacity-0");
    expect(heroFrameSkeleton()).toBeTruthy();
    fireEvent.load(hero() as Element);
    expect(hero()?.className).not.toContain("opacity-0");
    expect(heroFrameSkeleton()).toBeNull();
  });

  it("removes a hero without showing a broken image when managed and supplier both fail", () => {
    renderDetail(
      product({
        title: "Shirt",
        images: [
          {
            id: 1,
            url: "/media/products/broken.jpg",
            alt: "P000000456120300.jpg",
            position: 0,
            fallback_url: "https://cdn.shopify.com/s/files/1/p.jpg",
          },
        ],
      }),
    );
    fireEvent.error(hero() as Element);
    expect(hero()?.className).toContain("opacity-0");
    expect(hero()?.getAttribute("alt")).toBe("P000000456120300.jpg");
    fireEvent.error(hero() as Element);
    expect(hero()?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
    expect(hero()?.getAttribute("data-pdp-placeholder")).toBe("true");
    expect(hero()?.getAttribute("alt")).toBe("Shirt");
    expect(hero()?.className ?? "").not.toContain("opacity-0");
    expect(heroFrameSkeleton()).toBeNull();
  });

  it("shows a cached hero without leaving the skeleton", () => {
    const completeSpy = vi
      .spyOn(HTMLImageElement.prototype, "complete", "get")
      .mockReturnValue(true);
    const widthSpy = vi
      .spyOn(HTMLImageElement.prototype, "naturalWidth", "get")
      .mockReturnValue(120);
    try {
      renderDetail(
        product({
          images: [{ id: 1, url: "/media/products/ok.jpg", alt: "cached.jpg", position: 0 }],
        }),
      );
      expect(heroFrameSkeleton()).toBeNull();
      expect(hero()?.className ?? "").not.toContain("opacity-0");
    } finally {
      completeSpy.mockRestore();
      widthSpy.mockRestore();
    }
  });

  it("hides the previous hero image while the next slide is loading", () => {
    renderDetail(
      product({
        images: [
          { id: 1, url: "/media/products/a.jpg", alt: "first.jpg", position: 0 },
          { id: 2, url: "/media/products/b.jpg", alt: "second.jpg", position: 1 },
        ],
      }),
    );
    fireEvent.load(hero() as Element);
    expect(hero()?.className ?? "").not.toContain("opacity-0");
    fireEvent.click(document.querySelector('[aria-label="Следующее фото"]') as Element);
    expect(hero()?.getAttribute("data-pdp-gallery-key")).toBe("1:/media/products/b.jpg");
    expect(hero()?.getAttribute("src")).toBe("/media/products/b_900.jpg");
    expect(hero()?.className).toContain("opacity-0");
    expect(heroFrameSkeleton()).toBeTruthy();
    expect(hero()?.getAttribute("alt")).toBe("second.jpg");
    fireEvent.load(hero() as Element);
    expect(hero()?.className ?? "").not.toContain("opacity-0");
    expect(heroFrameSkeleton()).toBeNull();
  });
});
