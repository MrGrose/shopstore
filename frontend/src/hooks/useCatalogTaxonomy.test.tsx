import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCatalogTaxonomy } from "./useCatalogTaxonomy";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchCatalogTaxonomy: vi.fn(),
  };
});

import { fetchCatalogTaxonomy } from "../lib/storefront/catalog";

const mockFetchCatalogTaxonomy = vi.mocked(fetchCatalogTaxonomy);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useCatalogTaxonomy", () => {
  afterEach(() => {
    mockFetchCatalogTaxonomy.mockReset();
  });

  it("dedupes taxonomy fetch for the same query client", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCatalogTaxonomy.mockResolvedValue({ sports: [], sub_slug_aliases: {} });

    const wrapper = createWrapper(client);
    const first = renderHook(() => useCatalogTaxonomy(), { wrapper });
    const second = renderHook(() => useCatalogTaxonomy(), { wrapper });

    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    await waitFor(() => expect(second.result.current.isLoading).toBe(false));

    expect(mockFetchCatalogTaxonomy).toHaveBeenCalledTimes(1);
    expect(first.result.current.taxonomy).toEqual({ sports: [], sub_slug_aliases: {} });
  });
});
