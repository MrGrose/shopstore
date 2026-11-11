import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PRODUCT_PLACEHOLDER } from "../../../lib/storefront/productPlaceholder";
import { CatalogProductCard } from "./CatalogProductCard";
import { catalogGalleryCandidateKey, type CatalogProductCardData } from "./catalogProductTypes";

afterEach(() => {
  cleanup();
});

function cardProduct(
  overrides: Partial<CatalogProductCardData> = {},
): CatalogProductCardData {
  return {
    id: 11,
    title: "Air Veron",
    brand: "Babolat",
    sale_price: 18000,
    regular_price: 20000,
    ...overrides,
  };
}

const threePhotos = [
  { url: "/media/products/a.jpg", position: 0 },
  { url: "/media/products/b.jpg", position: 1 },
  { url: "/media/products/c.jpg", position: 2 },
];

function renderCard(product: CatalogProductCardData, compact = false) {
  const onOpen = vi.fn();
  return {
    onOpen,
    product,
    ...render(
      <CatalogProductCard
        product={product}
        animationIndex={0}
        cartLine={null}
        cartBusy={false}
        onOpen={onOpen}
        onAddToCart={vi.fn(async () => undefined)}
        onChangeCartQty={vi.fn()}
        compact={compact}
      />,
    ),
  };
}

function activeSlide() {
  return document.querySelector('[data-catalog-card-slide][data-catalog-card-active="true"]');
}

function renderedSlides() {
  return document.querySelectorAll("[data-catalog-card-slide]");
}

function renderedDots() {
  return document.querySelectorAll("[data-catalog-card-dot]");
}

function slideByKey(position: number, url: string) {
  const key = catalogGalleryCandidateKey({ position, url });
  return document.querySelector(`[data-catalog-slide-key="${key}"]`);
}

function exhaustImage(node: Element | null | undefined) {
  if (!node) throw new Error("missing slide");
  fireEvent.error(node);
  fireEvent.error(node);
}

function imageArea() {
  return document
    .querySelector("[data-catalog-product-id]")
    ?.querySelector(".relative.w-full.overflow-hidden") as HTMLElement;
}

function swipe(fromX: number, toX: number) {
  const area = imageArea();
  fireEvent.touchStart(area, { changedTouches: [{ clientX: fromX, clientY: 20 }] });
  fireEvent.touchEnd(area, { changedTouches: [{ clientX: toX, clientY: 24 }] });
}

function swipeNext() {
  swipe(180, 40);
}

function swipePrev() {
  swipe(40, 180);
}

function fivePhotoProduct(extra: Partial<CatalogProductCardData> = {}) {
  return cardProduct({
    images: [0, 1, 2, 3, 4].map((position) => ({
      url: `/media/products/${position}.jpg`,
      position,
    })),
    ...extra,
  });
}

describe("CatalogProductCard gallery", () => {
  it("switches photos on desktop hover zones without opening PDP", () => {
    const { onOpen } = renderCard(
      cardProduct({
        images: [
          { url: "/media/products/a.jpg", position: 1 },
          { url: "/media/products/b.jpg", position: 0 },
          { url: "/media/products/c.jpg", position: 2 },
        ],
      }),
    );

    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_600.jpg");
    const zone = document.querySelector('[data-catalog-card-hover-zone="1"]');
    expect(zone).toBeTruthy();
    fireEvent.mouseEnter(zone as Element);
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_600.jpg");
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("does not wrap desktop hover past the last photo", () => {
    renderCard(cardProduct({ images: threePhotos }));
    const lastZone = document.querySelector('[data-catalog-card-hover-zone="2"]');
    fireEvent.mouseEnter(lastZone as Element);
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/c_600.jpg");
    fireEvent.mouseEnter(lastZone as Element);
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/c_600.jpg");
  });

  it("does not call onOpen from dots or swipe", () => {
    const { onOpen } = renderCard(
      cardProduct({
        images: [
          { url: "/media/products/a.jpg", position: 0 },
          { url: "/media/products/b.jpg", position: 1 },
        ],
      }),
    );

    fireEvent.click(screen.getByLabelText("Фото 2"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_600.jpg");
    expect(onOpen).not.toHaveBeenCalled();

    swipePrev();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_600.jpg");
    fireEvent.click(imageArea());
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("opens PDP on a regular card click", () => {
    const { onOpen } = renderCard(
      cardProduct({
        images: [
          { url: "/media/products/a.jpg", position: 0 },
          { url: "/media/products/b.jpg", position: 1 },
        ],
      }),
    );
    fireEvent.click(screen.getByText("Air Veron"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0]).toBe(11);
  });

  it("shows the product placeholder when there are no photos", () => {
    const product = cardProduct();
    renderCard(product);
    const placeholder = document.querySelector("[data-catalog-card-placeholder]");
    expect(placeholder?.getAttribute("src")).toBe(PRODUCT_PLACEHOLDER);
    expect(renderedDots()).toHaveLength(0);
    expect(renderedSlides()).toHaveLength(0);
  });

  it("tries the supplier fallback before removing the slide", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/p.jpg";
    renderCard(
      cardProduct({
        images: [{ url: "/media/products/broken.jpg", fallback_url: fallback, position: 0 }],
      }),
    );
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/broken_600.jpg");
    fireEvent.error(activeSlide() as Element);
    expect(activeSlide()?.getAttribute("src")).toBe(fallback);
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
    expect(renderedSlides()).toHaveLength(1);
    exhaustImage(activeSlide());
    expect(document.querySelector("[data-catalog-card-placeholder]")?.getAttribute("src")).toBe(
      PRODUCT_PLACEHOLDER,
    );
    expect(renderedSlides()).toHaveLength(0);
  });

  it("does not show the placeholder when the managed image loads", () => {
    renderCard(
      cardProduct({
        images: [
          {
            url: "/media/products/ok.jpg",
            fallback_url: "https://cdn.shopify.com/s/files/1/p.jpg",
            position: 0,
          },
        ],
      }),
    );
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/ok_600.jpg");
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
  });

  it("shows the product placeholder when the only image is exhausted", () => {
    const product = cardProduct({ images: [{ url: "/media/products/broken.jpg", position: 0 }] });
    renderCard(product);
    exhaustImage(activeSlide());
    expect(document.querySelector("[data-catalog-card-placeholder]")?.getAttribute("src")).toBe(
      PRODUCT_PLACEHOLDER,
    );
    expect(renderedSlides()).toHaveLength(0);
  });

  it("keeps the supplier image when the fallback loads", () => {
    const fallback = "https://cdn.shopify.com/s/files/1/ok.jpg";
    renderCard(
      cardProduct({
        images: [{ url: "/media/products/broken.jpg", fallback_url: fallback, position: 0 }],
      }),
    );
    fireEvent.error(activeSlide() as Element);
    expect(activeSlide()?.getAttribute("src")).toBe(fallback);
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
  });

  it("does not break the next slide when one image uses its fallback", () => {
    renderCard(
      cardProduct({
        images: [
          {
            url: "/media/products/a.jpg",
            fallback_url: "https://cdn.shopify.com/s/files/1/a.jpg",
            position: 0,
          },
          { url: "/media/products/b.jpg", position: 1 },
        ],
      }),
    );
    fireEvent.error(activeSlide() as Element);
    expect(activeSlide()?.getAttribute("src")).toBe("https://cdn.shopify.com/s/files/1/a.jpg");
    fireEvent.click(screen.getByLabelText("Фото 2"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_600.jpg");
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
    expect(renderedDots()).toHaveLength(2);
  });
});

describe("CatalogProductCard available gallery slides", () => {
  it("scenario A: keeps five available slides when all managed images load", () => {
    renderCard(fivePhotoProduct());
    expect(renderedSlides()).toHaveLength(5);
    expect(renderedDots()).toHaveLength(5);
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
  });

  it("scenario B: keeps five slides when supplier fallback succeeds", () => {
    renderCard(
      fivePhotoProduct({
        images: [0, 1, 2, 3, 4].map((position) => ({
          url: `/media/products/${position}.jpg`,
          position,
          fallback_url:
            position === 1 ? "https://cdn.shopify.com/s/files/1/supplier.jpg" : undefined,
        })),
      }),
    );
    fireEvent.error(slideByKey(1, "/media/products/1.jpg") as Element);
    expect(renderedSlides()).toHaveLength(5);
    expect(renderedDots()).toHaveLength(5);
    expect(
      [...renderedSlides()].some(
        (node) => node.getAttribute("src") === "https://cdn.shopify.com/s/files/1/supplier.jpg",
      ),
    ).toBe(true);
  });

  it("scenario C: removes fully exhausted images instead of placeholder slots", () => {
    renderCard(fivePhotoProduct());
    exhaustImage(slideByKey(2, "/media/products/2.jpg"));
    exhaustImage(slideByKey(4, "/media/products/4.jpg"));
    expect(renderedSlides()).toHaveLength(3);
    expect(renderedDots()).toHaveLength(3);
    expect(document.querySelector("[data-catalog-card-placeholder]")).toBeNull();
  });

  it("never mounts category placeholder as a gallery slide", () => {
    const product = fivePhotoProduct({ sport_type: "padel" });
    const categoryPlaceholder = PRODUCT_PLACEHOLDER;
    renderCard(product);
    for (const slide of renderedSlides()) {
      expect(slide.getAttribute("src")).not.toBe(categoryPlaceholder);
    }
    exhaustImage(slideByKey(0, "/media/products/0.jpg"));
    expect(document.querySelectorAll('[data-image-placeholder="true"]')).toHaveLength(0);
    for (const slide of renderedSlides()) {
      expect(slide.getAttribute("src")).not.toBe(categoryPlaceholder);
    }
  });

  it("scenario D: shows one placeholder when every image is exhausted", () => {
    const product = fivePhotoProduct();
    renderCard(product);
    for (const position of [0, 1, 2, 3, 4]) {
      exhaustImage(slideByKey(position, `/media/products/${position}.jpg`));
    }
    expect(renderedSlides()).toHaveLength(0);
    expect(renderedDots()).toHaveLength(0);
    expect(document.querySelector("[data-catalog-card-placeholder]")?.getAttribute("src")).toBe(
      PRODUCT_PLACEHOLDER,
    );
  });

  it("moves activeIndex to the next available slide when the active slide is exhausted", () => {
    renderCard(fivePhotoProduct());
    fireEvent.click(screen.getByLabelText("Фото 3"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/2_600.jpg");
    exhaustImage(slideByKey(2, "/media/products/2.jpg"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/3_600.jpg");
    expect(renderedSlides()).toHaveLength(4);
  });

  it("does not mark the active slide failed when an inactive slide exhausts", () => {
    renderCard(
      cardProduct({
        images: [
          { url: "/media/products/a.jpg", position: 0 },
          { url: "/media/products/b.jpg", position: 1 },
          { url: "/media/products/c.jpg", position: 2 },
        ],
      }),
    );
    fireEvent.click(screen.getByLabelText("Фото 2"));
    exhaustImage(slideByKey(0, "/media/products/a.jpg"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_600.jpg");
    expect(renderedSlides()).toHaveLength(2);
    expect(renderedDots()).toHaveLength(2);
  });

  it("resets gallery state when the product changes", () => {
    const first = renderCard(fivePhotoProduct({ id: 1 }));
    exhaustImage(slideByKey(2, "/media/products/2.jpg"));
    expect(renderedSlides()).toHaveLength(4);
    first.unmount();
    renderCard(fivePhotoProduct({ id: 2 }));
    expect(renderedSlides()).toHaveLength(5);
  });
});

describe("CatalogProductCard mobile circular swipe", () => {
  it("wraps last → first", () => {
    renderCard(cardProduct({ images: threePhotos }), true);
    fireEvent.click(screen.getByLabelText("Фото 3"));
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/c_900.jpg");
    swipeNext();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_900.jpg");
    expect(screen.getByLabelText("Фото 1")).toBeTruthy();
  });

  it("wraps first → last", () => {
    renderCard(cardProduct({ images: threePhotos }), true);
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_900.jpg");
    swipePrev();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/c_900.jpg");
  });

  it("moves next and previous without wrapping in the middle", () => {
    renderCard(cardProduct({ images: threePhotos }), true);
    swipeNext();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_900.jpg");
    swipeNext();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/c_900.jpg");
    swipePrev();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/b_900.jpg");
  });

  it("does not show dots or swipe with a single photo", () => {
    renderCard(
      cardProduct({ images: [{ url: "/media/products/a.jpg", position: 0 }] }),
      true,
    );
    expect(renderedDots()).toHaveLength(0);
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_900.jpg");
    swipeNext();
    swipePrev();
    expect(activeSlide()?.getAttribute("src")).toBe("/media/products/a_900.jpg");
  });
});

describe("catalog card enter animation", () => {
  it("plays enter animation on a normal catalog visit", () => {
    renderCard(cardProduct());
    expect(document.querySelector("[data-catalog-enter]")?.getAttribute("data-catalog-enter")).toBe(
      "play",
    );
  });

  it("skips enter animation after a POP remount", () => {
    render(
      <CatalogProductCard
        product={cardProduct()}
        animationIndex={0}
        cartLine={null}
        cartBusy={false}
        onOpen={() => undefined}
        onAddToCart={async () => undefined}
        onChangeCartQty={() => undefined}
        skipEnterAnimation
      />,
    );
    expect(document.querySelector("[data-catalog-enter]")?.getAttribute("data-catalog-enter")).toBe(
      "skip",
    );
  });
});
