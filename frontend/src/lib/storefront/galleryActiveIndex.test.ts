import { describe, expect, it } from "vitest";

import { adjustGalleryActiveIndex } from "./galleryActiveIndex";

describe("adjustGalleryActiveIndex", () => {
  it("keeps the same index when the active slide is removed", () => {
    expect(adjustGalleryActiveIndex(2, 2, 5)).toBe(2);
  });

  it("shifts left when a slide before the active one is removed", () => {
    expect(adjustGalleryActiveIndex(2, 0, 2)).toBe(1);
  });

  it("keeps the active index when a later slide is removed", () => {
    expect(adjustGalleryActiveIndex(1, 3, 3)).toBe(1);
  });

  it("returns zero when no slides remain", () => {
    expect(adjustGalleryActiveIndex(4, 0, 0)).toBe(0);
  });
});
