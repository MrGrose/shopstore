import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCatalogFacetsBundle } from "./useCatalogFacetsBundle";

vi.mock("./useCatalogFacets", () => ({
  useCatalogFacets: vi.fn(() => ({
    facets: undefined,
    isLoading: false,
    isFetching: false,
    error: null,
  })),
}));

import { useCatalogFacets } from "./useCatalogFacets";

const mockUseCatalogFacets = vi.mocked(useCatalogFacets);

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

const metaFacets = {
  brands: [{ value: "Babolat", label_ru: "Babolat", count: 4 }],
  genders: [{ value: "men", label_ru: "Мужской", count: 2 }],
  colors: [],
  sizes: [],
  price_min: 1000,
  price_max: 50000,
};


function expectDedicatedEnabled(enabled: boolean) {
  expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "brands", enabled);
  expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "genders", enabled);
  expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "colors", enabled);
  expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "sizes", enabled);
}

describe("useCatalogFacetsBundle", () => {
  afterEach(() => {
    mockUseCatalogFacets.mockReset();
    mockUseCatalogFacets.mockImplementation(() => ({
      facets: undefined,
      isLoading: false,
      isFetching: false,
      error: null,
    }));
  });

  it("uses meta facets and skips option facet queries when filters are empty", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { result } = renderHook(
      () => useCatalogFacetsBundle(baseOpts, true, metaFacets, false),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.facets?.brands).toHaveLength(1));
    expect(result.current.brands).toEqual(["Babolat"]);
    expect(result.current.facets?.price_min).toBe(1000);
    expect(result.current.facets?.price_max).toBe(50000);
    expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "brands", false);
    expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "sizes", false);
  });

  it("keeps option facet queries when a facet filter is active", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const filteredOpts = { ...baseOpts, brand: "Babolat" };

    renderHook(() => useCatalogFacetsBundle(filteredOpts, true, metaFacets, false), {
      wrapper: createWrapper(client),
    });

    expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "brands", true);
    expect(mockUseCatalogFacets).toHaveBeenCalledWith(expect.any(String), "sizes", true);
  });

  it("prefers dedicated size facets over stale meta sizes after clearing size filter", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const filteredMeta = {
      ...metaFacets,
      sizes: [{ value: "43", label_ru: "43", count: 1 }],
    };
    const clearedOpts = { ...baseOpts, size: "" };

    mockUseCatalogFacets.mockImplementation((_key, include) => {
      if (include === "sizes") {
        return {
          facets: {
            brands: [],
            genders: [],
            colors: [],
            sizes: [
              { value: "42", label_ru: "42", count: 2 },
              { value: "43", label_ru: "43", count: 3 },
            ],
            price_min: null,
            price_max: null,
          },
          isLoading: false,
          isFetching: false,
          error: null,
        };
      }
      return {
        facets: undefined,
        isLoading: false,
        isFetching: false,
        error: null,
      };
    });

    const { result } = renderHook(
      () => useCatalogFacetsBundle(clearedOpts, true, filteredMeta, false),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.facets?.sizes).toHaveLength(2));
    expect(result.current.facets?.sizes?.map((item) => item.value)).toEqual(["42", "43"]);
    expect(result.current.facets?.price_min).toBe(1000);
  });


  it("skips dedicated facet queries on cold load while meta is still loading", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { result } = renderHook(
      () => useCatalogFacetsBundle(baseOpts, true, undefined, true),
      { wrapper: createWrapper(client) },
    );

    expectDedicatedEnabled(false);
    expect(result.current.facets).toBeNull();
    expect(result.current.facetsLoading).toBe(true);
    expect(result.current.facetsOptionsLoading).toBe(false);
  });

  it("enables dedicated facet queries on deep-link filters before meta resolves", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const deepLinkOpts = { ...baseOpts, brand: "Babolat" };

    const { result } = renderHook(
      () => useCatalogFacetsBundle(deepLinkOpts, true, undefined, true),
      { wrapper: createWrapper(client) },
    );

    expectDedicatedEnabled(true);
    expect(result.current.facetsLoading).toBe(true);
  });

  it("enables dedicated queries when a facet filter is applied mid-flight", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { rerender } = renderHook(
      ({ opts }) => useCatalogFacetsBundle(opts, true, metaFacets, false),
      { wrapper: createWrapper(client), initialProps: { opts: baseOpts } },
    );

    expectDedicatedEnabled(false);
    mockUseCatalogFacets.mockClear();

    rerender({ opts: { ...baseOpts, brand: "Babolat" } });
    expectDedicatedEnabled(true);
  });

  it("skips dedicated queries when the mobile sheet is closed", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { result } = renderHook(
      () => useCatalogFacetsBundle(baseOpts, false, undefined, false),
      { wrapper: createWrapper(client) },
    );

    expectDedicatedEnabled(false);
    expect(result.current.facets).toBeNull();
    expect(result.current.facetsLoading).toBe(false);
  });

  it("keeps price bounds from meta when price filter is active", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const pricedOpts = { ...baseOpts, priceMin: "1000", priceMax: "5000" };

    const { result } = renderHook(
      () => useCatalogFacetsBundle(pricedOpts, true, metaFacets, false),
      { wrapper: createWrapper(client) },
    );

    await waitFor(() => expect(result.current.facets?.price_min).toBe(1000));
    expect(result.current.facets?.price_max).toBe(50000);
    expect(mockUseCatalogFacets).not.toHaveBeenCalledWith(expect.any(String), "core", expect.anything());
    expectDedicatedEnabled(true);
  });
});
