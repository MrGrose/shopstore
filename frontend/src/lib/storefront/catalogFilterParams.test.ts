import { describe, expect, it } from "vitest";
import {
  applyCatalogSearchQueryToSearchParams,
  applyCatalogFiltersToSearchParams,
  buildCatalogFacetResetPatch,
  buildCatalogSearchNavigateTarget,
  buildPdpVariantSearchParams,
  buildVariantConstraintPreset,
  buildVariantConstraintPresetFromSearchParams,
  filterFacetOptions,
  parseFacetListValue,
  toggleFacetListValue,
  pickVariantConstraintPreset,
  readCatalogSearchQuery,
} from "./catalogFilterParams";

const options = [
  { value: "nike", label_ru: "Nike", count: 10 },
  { value: "adidas", label_ru: "Adidas", count: 5 },
  { value: "bullpadel", label_ru: "Bullpadel", count: 3 },
];

describe("filterFacetOptions", () => {
  it("returns all options for empty query", () => {
    expect(filterFacetOptions(options, "")).toEqual(options);
    expect(filterFacetOptions(options, "   ")).toEqual(options);
  });

  it("filters by label and value case-insensitively", () => {
    expect(filterFacetOptions(options, "ad")).toEqual([
      { value: "adidas", label_ru: "Adidas", count: 5 },
      { value: "bullpadel", label_ru: "Bullpadel", count: 3 },
    ]);
    expect(filterFacetOptions(options, "NIKE")).toEqual([options[0]]);
  });

  it("does not keep selected values when query does not match", () => {
    expect(filterFacetOptions(options, "zzz")).toEqual([]);
  });
});

describe("parseFacetListValue", () => {
  it("parses pipe-separated facet state", () => {
    expect(parseFacetListValue("Black|Blue", "color")).toEqual(["Black", "Blue"]);
  });

  it("keeps decimal comma size as single token", () => {
    expect(parseFacetListValue("37,5", "size")).toEqual(["37,5"]);
  });

  it("keeps comma inside opaque color values", () => {
    expect(parseFacetListValue("black, black", "color")).toEqual(["black, black"]);
  });

  it("keeps comma inside opaque gender values", () => {
    expect(parseFacetListValue("foo, bar", "gender")).toEqual(["foo, bar"]);
  });

  it("splits legacy comma-separated brands", () => {
    expect(parseFacetListValue("Nike, Adidas", "brand")).toEqual(["Nike", "Adidas"]);
  });
});

describe("toggleFacetListValue round-trip", () => {
  it("preserves compound color through toggle and parse", () => {
    const next = toggleFacetListValue("", "black, black", "color");
    expect(parseFacetListValue(next, "color")).toEqual(["black, black"]);
    const cleared = toggleFacetListValue(next, "black, black", "color");
    expect(cleared).toBe("");
  });

  it("supports pipe-separated color multi-select", () => {
    const first = toggleFacetListValue("", "Black", "color");
    const both = toggleFacetListValue(first, "Blue", "color");
    expect(parseFacetListValue(both, "color")).toEqual(["Black", "Blue"]);
  });

  it("preserves decimal size through round-trip", () => {
    const next = toggleFacetListValue("", "37,5", "size");
    expect(parseFacetListValue(next, "size")).toEqual(["37,5"]);
  });
});

describe("buildVariantConstraintPreset", () => {
  it("builds groups from pipe-separated filter state", () => {
    expect(
      buildVariantConstraintPreset({ color: "Black|Blue", size: "M" }),
    ).toEqual([
      { id: "color", tokens: ["Black", "Blue"] },
      { id: "size", tokens: ["M"] },
    ]);
  });

  it("omits empty facets", () => {
    expect(buildVariantConstraintPreset({ color: "", size: "32" })).toEqual([
      { id: "size", tokens: ["32"] },
    ]);
  });
});

describe("buildVariantConstraintPresetFromSearchParams", () => {
  it("builds preset from PDP URL query", () => {
    const params = new URLSearchParams("color=Black&size=M");
    expect(buildVariantConstraintPresetFromSearchParams(params)).toEqual([
      { id: "color", tokens: ["Black"] },
      { id: "size", tokens: ["M"] },
    ]);
  });
});

describe("buildPdpVariantSearchParams", () => {
  it("writes only first token per facet for share URL", () => {
    const params = buildPdpVariantSearchParams({ color: "Black|Blue", size: "M|L" });
    expect(params.get("color")).toBe("Black");
    expect(params.get("size")).toBe("M");
  });
});

describe("pickVariantConstraintPreset", () => {
  const urlPreset = [{ id: "color", tokens: ["Black"] }] as const;
  const statePreset = [{ id: "color", tokens: ["Black", "Blue"] }] as const;

  it("prefers state preset when defined", () => {
    expect(pickVariantConstraintPreset(statePreset, urlPreset)).toEqual(statePreset);
  });

  it("falls back to URL preset when state is undefined", () => {
    expect(pickVariantConstraintPreset(undefined, urlPreset)).toEqual(urlPreset);
  });

  it("uses empty state preset without falling back to URL", () => {
    expect(pickVariantConstraintPreset([], urlPreset)).toEqual([]);
  });
});


describe("catalog search query", () => {
  it("reads trimmed q from URL", () => {
    expect(readCatalogSearchQuery(new URLSearchParams("q=  bullpadel  "))).toBe("bullpadel");
    expect(readCatalogSearchQuery(new URLSearchParams())).toBe("");
  });

  it("applies q to existing params", () => {
    const base = new URLSearchParams("section=shoes&brand=nike");
    const next = applyCatalogSearchQueryToSearchParams(base, "bullpadel");
    expect(next.get("q")).toBe("bullpadel");
    expect(next.get("section")).toBe("shoes");
    expect(next.get("brand")).toBe("nike");
  });

  it("clears q without touching filters", () => {
    const base = new URLSearchParams("q=test&size=43");
    const next = applyCatalogSearchQueryToSearchParams(base, "  ");
    expect(next.has("q")).toBe(false);
    expect(next.get("size")).toBe("43");
  });
});

describe("buildCatalogFacetResetPatch", () => {
  it("clears facet filters only", () => {
    expect(buildCatalogFacetResetPatch()).toEqual({
      brand: "",
      gender: "",
      color: "",
      size: "",
      priceMin: "",
      priceMax: "",
      sortPrice: "",
    });
  });

  it("keeps section and q when applied to URL", () => {
    const base = new URLSearchParams("q=test&section=shoes&brand=nike&size=43");
    const next = applyCatalogFiltersToSearchParams(base, buildCatalogFacetResetPatch(), {
      useMappingParams: true,
    });
    expect(next.get("q")).toBe("test");
    expect(next.get("section")).toBe("shoes");
    expect(next.get("brand")).toBeNull();
    expect(next.get("size")).toBeNull();
  });
});

describe("buildCatalogSearchNavigateTarget", () => {
  it("preserves catalog filters when searching on listing page", () => {
    expect(
      buildCatalogSearchNavigateTarget(
        "/catalog/padel",
        "?section=shoes&size=43",
        "bullpadel",
      ),
    ).toEqual({
      pathname: "/catalog/padel",
      search: "?section=shoes&size=43&q=bullpadel",
    });
  });

  it("navigates to catalog all when searching outside listing", () => {
    expect(buildCatalogSearchNavigateTarget("/", "", "nike")).toEqual({
      pathname: "/catalog",
      search: "?q=nike",
    });
  });

  it("clears q on PDP via catalog all path", () => {
    expect(
      buildCatalogSearchNavigateTarget("/catalog/product/1", "?color=Black&q=test", ""),
    ).toEqual({ pathname: "/catalog", search: "" });
  });
});
