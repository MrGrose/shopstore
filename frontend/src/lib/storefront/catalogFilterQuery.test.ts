import { describe, expect, it } from "vitest";

import { applyCatalogFiltersToSearchParams } from "./catalogFilterParams";
import { catalogFilterQueryString } from "./catalogFilterQuery";

describe("catalogFilterQueryString", () => {
  it("serializes navigation url_params for facet and product query keys", () => {
    const qs = catalogFilterQueryString({
      topCategory: "Padel",
      sub: "rackets",
      type: "pro",
      useMappingParams: false,
      categoryUrlParams: { section: "rackets", node: "pro" },
      brand: "",
      gender: "",
      color: "",
      size: "",
      priceMin: "",
      priceMax: "",
      searchQ: "",
    });

    const params = new URLSearchParams(qs);
    expect(params.get("top_category")).toBe("Padel");
    expect(params.get("section")).toBe("rackets");
    expect(params.get("node")).toBe("pro");
    expect(params.get("sub")).toBeNull();
    expect(params.get("category_type")).toBeNull();
  });
});

describe("applyCatalogFiltersToSearchParams", () => {
  it("writes section when mapping enabled", () => {
    const params = applyCatalogFiltersToSearchParams(
      new URLSearchParams(),
      { sub: "rackets", productType: "" },
      { useMappingParams: true },
    );
    expect(params.get("section")).toBe("rackets");
  });
});
