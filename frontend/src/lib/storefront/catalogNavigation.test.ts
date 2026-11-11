import { describe, expect, it } from "vitest";
import {
  catalogAllPath,
  catalogSportPath,
  isCatalogListingPath,
  isCatalogRouteSlug,
  productPath,
  resolveCatalogTopFromSlug,
  storefrontHomePath,
} from "./catalogNavigation";

describe("catalogNavigation paths", () => {
  it("builds storefront home route", () => {
    expect(storefrontHomePath()).toBe("/");
  });

  it("builds catalog all-products route", () => {
    expect(catalogAllPath()).toBe("/catalog");
  });

  it("builds sport catalog routes", () => {
    expect(catalogSportPath("Padel")).toBe("/catalog/padel");
    expect(catalogSportPath("Tennis")).toBe("/catalog/tennis");
    expect(catalogSportPath("Running")).toBe("/catalog/running");
  });

  it("builds catalog product route", () => {
    expect(productPath(42)).toBe("/catalog/product/42");
    expect(productPath("99")).toBe("/catalog/product/99");
  });
});

describe("catalogNavigation slugs", () => {
  it("accepts sport and legacy all slugs", () => {
    expect(isCatalogRouteSlug("padel")).toBe(true);
    expect(isCatalogRouteSlug("all")).toBe(true);
    expect(isCatalogRouteSlug("unknown")).toBe(false);
  });

  it("resolves top scope from slug", () => {
    expect(resolveCatalogTopFromSlug("all")).toBe("All");
    expect(resolveCatalogTopFromSlug("padel")).toBe("Padel");
  });
});


describe("isCatalogListingPath", () => {
  it("matches catalog listing routes only", () => {
    expect(isCatalogListingPath("/catalog")).toBe(true);
    expect(isCatalogListingPath("/catalog/padel")).toBe(true);
    expect(isCatalogListingPath("/catalog/product/42")).toBe(false);
    expect(isCatalogListingPath("/")).toBe(false);
  });
});
