import { describe, expect, it } from "vitest";

import { resolveCatalogCategoryApiParams } from "./catalog";

describe("resolveCatalogCategoryApiParams", () => {
  it("prefers navigation url_params over scope passthrough", () => {
    expect(
      resolveCatalogCategoryApiParams("rackets", "pro", {
        section: "rackets",
        node: "pro",
      }),
    ).toEqual({
      section: "rackets",
      node: "pro",
      sub: undefined,
      category_type: undefined,
    });
  });

  it("passthrough scope keys for backend compat when url_params empty", () => {
    expect(resolveCatalogCategoryApiParams("rackets", "pro", {})).toEqual({
      sub: "rackets",
      section: "rackets",
      category_type: "pro",
      node: "pro",
    });
    expect(resolveCatalogCategoryApiParams("rackets", "", null)).toEqual({
      sub: "rackets",
      section: "rackets",
      category_type: undefined,
      node: undefined,
    });
  });
});
