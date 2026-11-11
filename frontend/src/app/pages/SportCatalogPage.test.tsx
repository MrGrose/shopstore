import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SportCatalogPage } from "./SportCatalogPage";

vi.mock("../components/ProductGrid", () => ({
  ProductGrid: ({ sectionTitle }: { sectionTitle?: string }) => (
    <div>{sectionTitle ?? "sport-grid"}</div>
  ),
}));

vi.mock("../../lib/storefront/useStorefrontSurface", () => ({
  useStorefrontCompactPagePad: () => "p-0",
}));

describe("SportCatalogPage", () => {
  afterEach(() => {
    cleanup();
  });

  it("redirects legacy /catalog/all to /catalog", () => {
    render(
      <MemoryRouter initialEntries={["/catalog/all"]}>
        <Routes>
          <Route path="/catalog" element={<div>catalog-all</div>} />
          <Route path="/catalog/:sport" element={<SportCatalogPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("catalog-all")).toBeTruthy();
  });

  it("renders sport catalog for padel", () => {
    render(
      <MemoryRouter initialEntries={["/catalog/padel"]}>
        <Routes>
          <Route path="/catalog/:sport" element={<SportCatalogPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("sport-grid")).toBeTruthy();
  });
});
