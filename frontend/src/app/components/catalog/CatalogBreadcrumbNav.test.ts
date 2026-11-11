import type { CatalogTaxonomy } from "../../../lib/storefront/catalog";
import { describe, expect, it } from "vitest";

import {
  buildCatalogBreadcrumbTrail,
  buildCatalogBreadcrumbTrailFromNavigation,
  buildCatalogPathFromUrlParams,
  hasCatalogBreadcrumbScope,
} from "./CatalogBreadcrumbNav";

describe("buildCatalogPathFromUrlParams", () => {
  it("builds mapping section path", () => {
    expect(
      buildCatalogPathFromUrlParams("Padel", { section: "rackets", node: "pro" }),
    ).toBe("/catalog/padel?section=rackets&node=pro");
  });

  it("builds legacy sub path", () => {
    expect(
      buildCatalogPathFromUrlParams("Tennis", { sub: "rackets", category_type: "pro" }),
    ).toBe("/catalog/tennis?sub=rackets&category_type=pro");
  });
});

describe("buildCatalogBreadcrumbTrailFromNavigation", () => {
  it("nulls last crumb and keeps sport linkable when filters present", () => {
    const trail = buildCatalogBreadcrumbTrailFromNavigation(
      "Padel",
      [
        { label: "Падел", url_params: {} },
        { label: "Ракетки", url_params: { section: "rackets" } },
      ],
      true,
    );
    expect(trail).toEqual([
      { label: "Падел", to: "/catalog/padel" },
      { label: "Ракетки", to: null },
    ]);
  });

  it("nulls sport crumb when scope is only top category", () => {
    const trail = buildCatalogBreadcrumbTrailFromNavigation(
      "Padel",
      [{ label: "Падел", url_params: {} }],
      false,
    );
    expect(trail).toEqual([{ label: "Падел", to: null }]);
  });
});

describe("hasCatalogBreadcrumbScope", () => {
  it("detects facet-only scope", () => {
    expect(
      hasCatalogBreadcrumbScope({
        subCategory: "",
        productType: "",
        category: "",
        brand: "head",
        gender: "",
        color: "",
        size: "",
        priceMin: "",
        priceMax: "",
        sortPrice: "",
      }),
    ).toBe(true);
  });
});

const padelTaxonomy: CatalogTaxonomy = {
  sports: [
    {
      sport: "Padel",
      slug: "padel",
      label: "Падел",
      sections: [
        {
          slug: "rackets",
          label: "Ракетки",
          chips: [{ display_key: "padel.rackets.pro", slug: "pro", label: "Про" }],
        },
      ],
      subcategories: [],
    },
  ],
  sub_slug_aliases: {},
};

describe("buildCatalogBreadcrumbTrail taxonomy fallback", () => {
  it("builds sub crumb from taxonomy when navigation breadcrumbs are unavailable", () => {
    const trail = buildCatalogBreadcrumbTrail({
      fixedTopCategory: "Padel",
      searchQ: "",
      catalogLabels: null,
      catalogTaxonomy: padelTaxonomy,
      subCategory: "rackets",
      productType: "",
      category: "",
      brand: "",
      gender: "",
      color: "",
      size: "",
      priceMin: "",
      priceMax: "",
      sortPrice: "",
      catalogSubcategories: [],
      useMappingParams: true,
    });

    expect(trail.map((segment) => segment.label)).toEqual(["Падел", "Ракетки"]);
    expect(trail[1]?.to).toBeNull();
  });
});
