import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useProducts } from "./useProducts";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchProducts: vi.fn(),
  };
});

import { fetchProducts } from "../lib/storefront/catalog";

const mockFetchProducts = vi.mocked(fetchProducts);

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

describe("useProducts", () => {
  afterEach(() => {
    mockFetchProducts.mockReset();
  });

  it("loads first page for filter key", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchProducts.mockResolvedValue({
      items: [{ id: 1 }],
      has_more: true,
      total_pages: 2,
    });

    const { result } = renderHook(() => useProducts(baseOpts, 20, true), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(result.current.hasMore).toBe(true);
    expect(mockFetchProducts).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, page_size: 20, top_category: "Padel" }),
    );
  });

  it("uses navigation url_params for category keys when provided", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchProducts.mockResolvedValue({
      items: [],
      has_more: false,
      total_pages: 1,
    });

    const { result } = renderHook(
      () =>
        useProducts(
          {
            ...baseOpts,
            useMappingParams: false,
            categoryUrlParams: { section: "rackets", node: "pro" },
          },
          20,
          true,
        ),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.isFetched).toBe(true));
    expect(mockFetchProducts).toHaveBeenCalledWith(
      expect.objectContaining({
        section: "rackets",
        node: "pro",
        sub: undefined,
        category_type: undefined,
      }),
    );
  });

  it("loads next page when fetchNextPage is called", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchProducts
      .mockResolvedValueOnce({
        items: [{ id: 1 }],
        has_more: true,
        total_pages: 2,
      })
      .mockResolvedValueOnce({
        items: [{ id: 2 }],
        has_more: false,
        total_pages: 2,
      });

    const { result } = renderHook(() => useProducts(baseOpts, 20, true), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.items).toHaveLength(1));
    result.current.fetchNextPage();
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(mockFetchProducts).toHaveBeenCalledTimes(2);
  });

  it("keeps previous items while the next filter query loads", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchProducts.mockResolvedValueOnce({
      items: [{ id: 1 }],
      has_more: false,
      total_pages: 1,
    });

    const { result, rerender } = renderHook(
      ({ opts }) => useProducts(opts, 20, true),
      {
        wrapper: createWrapper(client),
        initialProps: { opts: baseOpts },
      },
    );

    await waitFor(() => expect(result.current.items).toHaveLength(1));

    let resolveNext: (value: Awaited<ReturnType<typeof fetchProducts>>) => void = () => {};
    mockFetchProducts.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveNext = resolve;
        }),
    );

    rerender({ opts: { ...baseOpts, brand: "Nike" } });

    expect(result.current.items).toHaveLength(1);
    expect(result.current.isPlaceholderData).toBe(true);

    resolveNext({
      items: [{ id: 2 }],
      has_more: false,
      total_pages: 1,
    });
    await waitFor(() => expect(result.current.items[0]?.id).toBe(2));
    expect(result.current.isPlaceholderData).toBe(false);
  });
});
