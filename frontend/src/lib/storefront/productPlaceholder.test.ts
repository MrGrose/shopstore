import { describe, expect, it } from "vitest";

import productPlaceholderAsset from "../../assets/placeholders/product-placeholder.webp";
import { PRODUCT_PLACEHOLDER } from "./productPlaceholder";

describe("PRODUCT_PLACEHOLDER", () => {
  it("points at the shared product-placeholder asset", () => {
    expect(PRODUCT_PLACEHOLDER).toBe(productPlaceholderAsset);
  });
});
