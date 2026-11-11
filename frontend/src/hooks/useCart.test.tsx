import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { cartQueryKey, invalidateCartQuery, syncCartQueryCache, useCart } from "./useCart";

vi.mock("../lib/storefront/cart", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/storefront/cart")>();
  return {
    ...actual,
    fetchCart: vi.fn(),
  };
});

import { fetchCart } from "../lib/storefront/cart";

const mockFetchCart = vi.mocked(fetchCart);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useCart", () => {
  afterEach(() => {
    mockFetchCart.mockReset();
  });

  it("returns cart data from query", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCart.mockResolvedValue({
      items: [{ product_id: 1, quantity: 2 }],
    });

    const { result } = renderHook(() => useCart(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.cart).toEqual({
      items: [{ product_id: 1, quantity: 2 }],
    });
    expect(result.current.error).toBeNull();
    expect(mockFetchCart).toHaveBeenCalledTimes(1);
  });

  it("dedupes /cart/me when hook is reused with the same query client", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCart.mockResolvedValue({ items: [] });

    const wrapper = createWrapper(client);
    const first = renderHook(() => useCart(), { wrapper });
    const second = renderHook(() => useCart(), { wrapper });

    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    await waitFor(() => expect(second.result.current.isLoading).toBe(false));

    expect(mockFetchCart).toHaveBeenCalledTimes(1);
    expect(first.result.current.cart).toEqual({ items: [] });
    expect(second.result.current.cart).toEqual({ items: [] });
  });

  it("syncCartQueryCache updates query data and broadcasts count", () => {
    const client = new QueryClient();
    const events: number[] = [];
    window.addEventListener("store:cart:count", ((e: CustomEvent<{ count: number }>) => {
      events.push(e.detail.count);
    }) as EventListener);

    syncCartQueryCache(client, { items: [{ product_id: 1, quantity: 3 }] });

    expect(client.getQueryData(cartQueryKey)).toEqual({
      items: [{ product_id: 1, quantity: 3 }],
    });
    expect(events).toEqual([3]);
  });

  it("invalidateCartQuery refetches cart", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCart.mockResolvedValue({ items: [{ product_id: 2, quantity: 1 }] });
    client.setQueryData(cartQueryKey, { items: [] });

    await invalidateCartQuery(client);

    expect(mockFetchCart).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(cartQueryKey)).toEqual({
      items: [{ product_id: 2, quantity: 1 }],
    });
  });
});
