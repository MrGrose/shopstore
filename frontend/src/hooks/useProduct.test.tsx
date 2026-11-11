import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useProduct } from "./useProduct";

vi.mock("../lib/storefront/catalog", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/catalog")>();
  return {
    ...actual,
    fetchProduct: vi.fn(),
  };
});

import { fetchProduct } from "../lib/storefront/catalog";

const mockFetchProduct = vi.mocked(fetchProduct);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useProduct", () => {
  afterEach(() => {
    mockFetchProduct.mockReset();
  });

  it("loads product by id", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchProduct.mockResolvedValue({ id: 42, title: "Racket" });

    const { result } = renderHook(() => useProduct(42, true), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.product?.id).toBe(42));
    expect(mockFetchProduct).toHaveBeenCalledWith(42);
  });
});
