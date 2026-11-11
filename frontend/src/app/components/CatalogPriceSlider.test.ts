import { describe, expect, it } from "vitest";

import {
  isCatalogPriceSliderFiltered,
  mergeCatalogPriceSliderRange,
  resolveCatalogPriceRangeCommit,
} from "./CatalogPriceSlider";

const bounds = { minBound: 764, maxBound: 30_243 };

describe("mergeCatalogPriceSliderRange", () => {
  it("returns filter range when no price filter is active", () => {
    expect(mergeCatalogPriceSliderRange([10_004, 20_000], [764, 30_243], "", "")).toEqual([
      764, 30_243,
    ]);
  });

  it("anchors min thumb to facet bound when only max is in URL", () => {
    expect(mergeCatalogPriceSliderRange([10_004, 30_243], [764, 20_000], "", "20000")).toEqual([
      764, 20_000,
    ]);
  });

  it("anchors max thumb to facet bound when only min is in URL", () => {
    expect(
      mergeCatalogPriceSliderRange([10_004, 30_243], [10_004, 30_243], "10000", ""),
    ).toEqual([10_004, 30_243]);
  });

  it("clamps URL values into stable bounds", () => {
    expect(
      mergeCatalogPriceSliderRange([10_080, 10_150], [10_050, 10_100], "10080", "10150"),
    ).toEqual([10_080, 10_100]);
  });
});

describe("resolveCatalogPriceRangeCommit", () => {
  it("writes max filter when only the upper thumb moves", () => {
    expect(resolveCatalogPriceRangeCommit(764, 20_000, bounds)).toEqual({
      priceMin: "",
      priceMax: "20000",
    });
  });

  it("writes both filters when min and max are narrowed", () => {
    const narrowedBounds = { minBound: 10_004, maxBound: 19_904 };
    expect(resolveCatalogPriceRangeCommit(12_000, 19_904, narrowedBounds)).toEqual({
      priceMin: "12000",
      priceMax: "19904",
    });
  });

  it("clears both filters when thumbs return to full range", () => {
    expect(resolveCatalogPriceRangeCommit(764, 30_243, bounds)).toEqual({
      priceMin: "",
      priceMax: "",
    });
  });

  it("keeps a narrowed window after max then min adjustments", () => {
    const narrowBounds = { minBound: 10_000, maxBound: 10_100 };
    expect(resolveCatalogPriceRangeCommit(10_020, 10_080, narrowBounds)).toEqual({
      priceMin: "10020",
      priceMax: "10080",
    });
  });
});

describe("isCatalogPriceSliderFiltered", () => {
  const facetBounds = { minBound: 10_004, maxBound: 19_904 };

  it("is true when price params are in URL even if thumbs sit on facet bounds", () => {
    expect(isCatalogPriceSliderFiltered(10_004, 19_904, facetBounds, "10000", "20000")).toBe(true);
  });

  it("is false for full range without URL price filter", () => {
    expect(isCatalogPriceSliderFiltered(764, 30_243, bounds, "", "")).toBe(false);
  });
});
