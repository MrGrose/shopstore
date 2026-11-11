import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCatalogNavigation } from "./useCatalogNavigation";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchCatalogNavigation: vi.fn(),
  };
});

import { fetchCatalogNavigation } from "../lib/storefront/catalog";

const mockFetchCatalogNavigation = vi.mocked(fetchCatalogNavigation);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useCatalogNavigation", () => {
  afterEach(() => {
    mockFetchCatalogNavigation.mockReset();
  });

  it("loads navigation for sport scope", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogNavigation.mockResolvedValue({
      top_category: "Padel",
      use_mapping_params: true,
      sub: "rackets",
      category_type: "",
      url_params: { section: "rackets" },
      breadcrumbs: [],
      subcategories: [{ slug: "rackets", label: "Ракетки", types: [] }],
    });

    const { result } = renderHook(
      () =>
        useCatalogNavigation(
          { topCategory: "Padel", sub: "rackets", productType: "" },
          true,
        ),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.navigation?.sub).toBe("rackets"));
    expect(mockFetchCatalogNavigation).toHaveBeenCalledWith(
      expect.objectContaining({
        top_category: "Padel",
        sub: "rackets",
        section: "rackets",
      }),
    );
  });
});
