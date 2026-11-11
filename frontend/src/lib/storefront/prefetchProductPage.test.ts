import { describe, expect, it, vi } from "vitest";

import { prefetchProductPageChunk } from "./prefetchProductPage";

vi.mock("../../app/pages/ProductPage", () => ({
  ProductPage: () => null,
}));

describe("prefetchProductPageChunk", () => {
  it("can be called repeatedly without throwing", () => {
    expect(() => {
      prefetchProductPageChunk();
      prefetchProductPageChunk();
    }).not.toThrow();
  });
});
