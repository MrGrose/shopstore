import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCatalogCount } from "./useCatalogCount";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchCatalogProductCount: vi.fn(),
  };
});

import { fetchCatalogProductCount } from "../lib/storefront/catalog";

const mockFetchCatalogProductCount = vi.mocked(fetchCatalogProductCount);

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

describe("useCatalogCount", () => {
  afterEach(() => {
    mockFetchCatalogProductCount.mockReset();
  });

  it("loads total for filter key", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogProductCount.mockResolvedValue(42);

    const { result } = renderHook(() => useCatalogCount(baseOpts, true), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.total).toBe(42));
    expect(mockFetchCatalogProductCount).toHaveBeenCalledWith(
      expect.objectContaining({ top_category: "Padel", sub: "rackets" }),
    );
  });

  it("uses navigation url_params for category keys when provided", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogProductCount.mockResolvedValue(7);

    const { result } = renderHook(
      () =>
        useCatalogCount(
          {
            ...baseOpts,
            categoryUrlParams: { section: "rackets", node: "pro" },
          },
          true,
        ),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.total).toBe(7));
    expect(mockFetchCatalogProductCount).toHaveBeenCalledWith(
      expect.objectContaining({
        section: "rackets",
        node: "pro",
        sub: undefined,
        category_type: undefined,
      }),
    );
  });
});
