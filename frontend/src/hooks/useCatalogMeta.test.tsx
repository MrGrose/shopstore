import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCatalogMeta } from "./useCatalogMeta";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchCatalogProductMeta: vi.fn(),
  };
});

import { fetchCatalogProductMeta } from "../lib/storefront/catalog";

const mockFetchCatalogProductMeta = vi.mocked(fetchCatalogProductMeta);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

const baseOpts = {
  topCategory: "Padel",
  sub: "rackets",
  type: "",
  useMappingParams: false,
  brand: "",
  gender: "",
  color: "",
  size: "",
  priceMin: "",
  priceMax: "",
  searchQ: "",
};

describe("useCatalogMeta", () => {
  afterEach(() => {
    mockFetchCatalogProductMeta.mockReset();
  });

  it("loads total and facets from /products/meta", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogProductMeta.mockResolvedValue({
      total: 12,
      facets: {
        brands: [{ value: "Babolat", label_ru: "Babolat", count: 4 }],
        genders: [],
        colors: [],
        sizes: [],
        price_min: 1000,
        price_max: 50000,
      },
    });

    const { result } = renderHook(() => useCatalogMeta(baseOpts, true), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.total).toBe(12));
    expect(result.current.facets?.brands[0]?.value).toBe("Babolat");
    expect(mockFetchCatalogProductMeta).toHaveBeenCalledWith(
      expect.objectContaining({ top_category: "Padel", include: "all" }),
    );
  });

  it("uses navigation url_params for category keys when provided", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogProductMeta.mockResolvedValue({
      total: 0,
      facets: {
        brands: [],
        genders: [],
        colors: [],
        sizes: [],
        price_min: null,
        price_max: null,
      },
    });

    const { result } = renderHook(
      () =>
        useCatalogMeta(
          {
            ...baseOpts,
            categoryUrlParams: { section: "rackets", node: "pro" },
          },
          true,
        ),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.total).toBe(0));
    expect(mockFetchCatalogProductMeta).toHaveBeenCalledWith(
      expect.objectContaining({
        section: "rackets",
        node: "pro",
        sub: undefined,
        category_type: undefined,
      }),
    );
  });

  it("does not fetch when disabled", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    renderHook(() => useCatalogMeta(baseOpts, false), {
      wrapper: createWrapper(client),
    });

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mockFetchCatalogProductMeta).not.toHaveBeenCalled();
  });
});
