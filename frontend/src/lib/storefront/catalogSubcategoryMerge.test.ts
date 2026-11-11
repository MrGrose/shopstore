import { describe, expect, it } from "vitest";

import type { CatalogSubCategoryItem } from "./catalog";
import { mergeSubcategoryTypes } from "./catalogSubcategoryMerge";

const sampleItem = (): CatalogSubCategoryItem => ({
  slug: "shoes",
  label: "Обувь",
  types: [{ key: "running", label_ru: "Беговые", count: 2 }],
});

describe("mergeSubcategoryTypes", () => {
  it("appends when slug is missing", () => {
    const loaded = sampleItem();
    expect(mergeSubcategoryTypes([], loaded)).toEqual([loaded]);
  });

  it("replaces matching slug", () => {
    const base = [{ slug: "shoes", label: "Обувь", types: [] }];
    const loaded = sampleItem();
    expect(mergeSubcategoryTypes(base, loaded)).toEqual([loaded]);
  });
});
