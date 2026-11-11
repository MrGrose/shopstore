import { afterEach, describe, expect, it } from "vitest";

import {
  catalogLocationKey,
  clearCatalogScrollSnapshot,
  getCatalogScrollRoot,
  peekCatalogScrollSnapshot,
  restoreCatalogScroll,
  saveCatalogScrollSnapshot,
  shouldPopProductBack,
  clearSkipCatalogEnterAnimation,
  shouldSkipCatalogEnterAnimation,
  shouldSkipUnmountScrollZero,
  shouldZeroCatalogScrollOnUnmount,
  writeCatalogScrollTop,
} from "./catalogScrollRestore";

describe("catalogLocationKey", () => {
  it("keeps pathname when search is empty", () => {
    expect(catalogLocationKey("/catalog", "")).toBe("/catalog");
    expect(catalogLocationKey("/catalog", "?")).toBe("/catalog");
  });

  it("joins search with or without leading ?", () => {
    expect(catalogLocationKey("/catalog", "?brand=babolat")).toBe("/catalog?brand=babolat");
    expect(catalogLocationKey("/catalog/padel", "sort_price=asc")).toBe(
      "/catalog/padel?sort_price=asc",
    );
  });
});

describe("shouldPopProductBack", () => {
  it("pops when PDP was opened from a catalog listing", () => {
    expect(shouldPopProductBack("/catalog")).toBe(true);
    expect(shouldPopProductBack("/catalog?brand=babolat")).toBe(true);
    expect(shouldPopProductBack("/catalog/padel?sort_price=asc")).toBe(true);
  });

  it("does not pop for direct PDP, other sections, or missing from", () => {
    expect(shouldPopProductBack(undefined)).toBe(false);
    expect(shouldPopProductBack("/catalog/product/12")).toBe(false);
    expect(shouldPopProductBack("/cart")).toBe(false);
    expect(shouldPopProductBack("https://example.com/catalog")).toBe(false);
  });
});

describe("catalog scroll snapshot", () => {
  afterEach(() => {
    clearCatalogScrollSnapshot();
    clearSkipCatalogEnterAnimation();
  });

  it("stores one pending restore and overwrites it", () => {
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 400,
      productId: 1,
      itemCount: 24,
    });
    saveCatalogScrollSnapshot({
      url: "/catalog?brand=babolat",
      top: 800,
      productId: 9,
      itemCount: 48,
    });
    expect(peekCatalogScrollSnapshot()).toEqual({
      url: "/catalog?brand=babolat",
      top: 800,
      productId: 9,
      itemCount: 48,
    });
    clearCatalogScrollSnapshot();
    expect(peekCatalogScrollSnapshot()).toBeNull();
  });
});

describe("getCatalogScrollRoot", () => {
  it("uses overflowing main when present", () => {
    const main = document.createElement("main");
    main.style.overflowY = "auto";
    const child = document.createElement("section");
    main.appendChild(child);
    document.body.appendChild(main);
    expect(getCatalogScrollRoot(child)).toBe(main);
    main.remove();
  });

  it("falls back to window when main does not scroll", () => {
    const main = document.createElement("main");
    const child = document.createElement("section");
    main.appendChild(child);
    document.body.appendChild(main);
    expect(getCatalogScrollRoot(child)).toBe(window);
    main.remove();
  });
});

describe("restoreCatalogScroll", () => {
  it("writes saved top when the container is tall enough", () => {
    const root = document.createElement("div");
    Object.defineProperty(root, "scrollHeight", { configurable: true, value: 4000 });
    writeCatalogScrollTop(root, 0);
    restoreCatalogScroll(root, {
      url: "/catalog",
      top: 640,
      productId: 3,
      itemCount: 24,
    });
    expect(root.scrollTop).toBe(640);
  });

  it("still writes saved top when the container is shorter than the snapshot", () => {
    const root = document.createElement("div");
    Object.defineProperty(root, "scrollHeight", { configurable: true, value: 200 });
    restoreCatalogScroll(root, {
      url: "/catalog",
      top: 640,
      productId: 3,
      itemCount: 24,
    });
    expect(root.scrollTop).toBe(640);
  });
});

describe("shouldZeroCatalogScrollOnUnmount", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("zeros when the committed route is the product page", () => {
    window.history.replaceState({}, "", "/catalog/product/12");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(true);
  });

  it("does not zero when catalog remounts on the listing route", () => {
    window.history.replaceState({}, "", "/catalog");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(false);
    window.history.replaceState({}, "", "/catalog/padel");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(false);
    window.history.replaceState({}, "", "/catalog?brand=babolat");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(false);
  });

  it("treats Mini App /app catalog URLs as listings", () => {
    window.history.replaceState({}, "", "/app/catalog");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(false);
    window.history.replaceState({}, "", "/app/catalog/padel");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(false);
  });

  it("still zeros Mini App and web product URLs", () => {
    window.history.replaceState({}, "", "/app/catalog/product/12");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(true);
    window.history.replaceState({}, "", "/app/product/12");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(true);
    window.history.replaceState({}, "", "/product/12");
    expect(shouldZeroCatalogScrollOnUnmount()).toBe(true);
  });
});

describe("shouldSkipUnmountScrollZero", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("skips zeroing shared main when leaving catalog for PDP", () => {
    const main = document.createElement("main");
    main.style.overflowY = "auto";
    document.body.appendChild(main);
    window.history.replaceState({}, "", "/app/catalog/product/12");
    expect(shouldSkipUnmountScrollZero(main, "/catalog/product/12")).toBe(true);
    expect(shouldSkipUnmountScrollZero(main)).toBe(true);
    main.remove();
  });

  it("still zeros window root on PDP", () => {
    window.history.replaceState({}, "", "/catalog/product/12");
    expect(shouldSkipUnmountScrollZero(window, "/catalog/product/12")).toBe(false);
  });

  it("still zeros shared main when leaving for cart", () => {
    const main = document.createElement("main");
    main.style.overflowY = "auto";
    expect(shouldSkipUnmountScrollZero(main, "/cart")).toBe(false);
  });
});

describe("skip catalog enter animation flag", () => {
  afterEach(() => {
    clearCatalogScrollSnapshot();
    clearSkipCatalogEnterAnimation();
  });

  it("marks skip on save snapshot until explicitly cleared", () => {
    expect(shouldSkipCatalogEnterAnimation()).toBe(false);
    saveCatalogScrollSnapshot({
      url: "/catalog",
      top: 100,
      productId: 1,
      itemCount: 20,
    });
    expect(shouldSkipCatalogEnterAnimation()).toBe(true);
    clearCatalogScrollSnapshot();
    expect(shouldSkipCatalogEnterAnimation()).toBe(true);
    clearSkipCatalogEnterAnimation();
    expect(shouldSkipCatalogEnterAnimation()).toBe(false);
  });
});
