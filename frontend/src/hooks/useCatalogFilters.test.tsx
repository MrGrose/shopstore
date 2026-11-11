import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import type { CatalogTaxonomy } from "../lib/storefront/catalog";
import { useCatalogFilters } from "./useCatalogFilters";

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

function createWrapper(initialEntry = "/catalog/padel") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/catalog/padel" element={children} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe("useCatalogFilters", () => {
  it("reads brand from URL on mount", () => {
    const { result } = renderHook(
      () =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: false,
          filterToTopCategory: "Padel",
        }),
      { wrapper: createWrapper("/catalog/padel?brand=nike") },
    );

    expect(result.current.brand).toBe("nike");
    expect(result.current.searchQ).toBe("");
  });

  it("writes filter patch to URL", async () => {
    const { result } = renderHook(
      () =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: false,
          filterToTopCategory: "Padel",
        }),
      { wrapper: createWrapper("/catalog/padel") },
    );

    act(() => {
      result.current.patchSearchParams({ brand: "adidas" });
    });

    await waitFor(() => {
      expect(result.current.brand).toBe("adidas");
      expect(result.current.searchParams.get("brand")).toBe("adidas");
    });
  });

  it("writes section param when mapping params are enabled", async () => {
    const { result } = renderHook(
      () =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: true,
          filterToTopCategory: "Padel",
        }),
      { wrapper: createWrapper("/catalog/padel") },
    );

    act(() => {
      result.current.patchSearchParams({ sub: "rackets", productType: "" });
    });

    await waitFor(() => {
      expect(result.current.subCategory).toBe("rackets");
      expect(result.current.searchParams.get("section")).toBe("rackets");
    });
  });

  it("keeps sub selection when taxonomy loads after patch", async () => {
    const { result, rerender } = renderHook(
      ({ taxonomy }: { taxonomy: CatalogTaxonomy | null }) =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: true,
          filterToTopCategory: "Padel",
          catalogTaxonomy: taxonomy,
        }),
      {
        wrapper: createWrapper("/catalog/padel"),
        initialProps: { taxonomy: null },
      },
    );

    act(() => {
      result.current.patchSearchParams({ sub: "rackets", productType: "" });
    });

    await waitFor(() => {
      expect(result.current.subCategory).toBe("rackets");
      expect(result.current.searchParams.get("section")).toBe("rackets");
    });

    rerender({ taxonomy: padelTaxonomy });

    await waitFor(() => {
      expect(result.current.subCategory).toBe("rackets");
      expect(result.current.searchParams.get("section")).toBe("rackets");
    });
  });

  it("writes q to URL via submitCatalogSearch", async () => {
    const { result } = renderHook(
      () =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: true,
          filterToTopCategory: "Padel",
        }),
      { wrapper: createWrapper("/catalog/padel?section=shoes&size=43") },
    );

    act(() => {
      result.current.submitCatalogSearch("bullpadel");
    });

    await waitFor(() => {
      expect(result.current.searchQ).toBe("bullpadel");
      expect(result.current.searchParams.get("q")).toBe("bullpadel");
      expect(result.current.searchParams.get("section")).toBe("shoes");
      expect(result.current.searchParams.get("size")).toBe("43");
    });
  });

  it("clears q without removing section filters", async () => {
    const { result } = renderHook(
      () =>
        useCatalogFilters({
          sportSlug: "padel",
          useMappingParams: true,
          filterToTopCategory: "Padel",
        }),
      { wrapper: createWrapper("/catalog/padel?q=test&section=shoes") },
    );

    act(() => {
      result.current.clearSearchQuery();
    });

    await waitFor(() => {
      expect(result.current.searchQ).toBe("");
      expect(result.current.searchParams.has("q")).toBe(false);
      expect(result.current.searchParams.get("section")).toBe("shoes");
    });
  });
});
