import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { invalidateUserQuery, syncUserQueryCache, useUser, userQueryKey } from "./useUser";

vi.mock("../lib/storefront/session", () => ({
  fetchCurrentUser: vi.fn(),
}));

import { fetchCurrentUser } from "../lib/storefront/session";

const mockFetchCurrentUser = vi.mocked(fetchCurrentUser);

function createWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useUser", () => {
  afterEach(() => {
    mockFetchCurrentUser.mockReset();
  });

  it("returns user data from query", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCurrentUser.mockResolvedValue({
      id: 1,
      email: "buyer@example.com",
    });

    const { result } = renderHook(() => useUser(), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.user).toEqual({
      id: 1,
      email: "buyer@example.com",
    });
    expect(result.current.error).toBeNull();
    expect(mockFetchCurrentUser).toHaveBeenCalledTimes(1);
  });

  it("dedupes /users/me when hook is reused with the same query client", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCurrentUser.mockResolvedValue(null);

    const wrapper = createWrapper(client);
    const first = renderHook(() => useUser(), { wrapper });
    const second = renderHook(() => useUser(), { wrapper });

    await waitFor(() => expect(first.result.current.isLoading).toBe(false));
    await waitFor(() => expect(second.result.current.isLoading).toBe(false));

    expect(mockFetchCurrentUser).toHaveBeenCalledTimes(1);
    expect(first.result.current.user).toBeNull();
    expect(second.result.current.user).toBeNull();
  });

  it("syncUserQueryCache updates query data", () => {
    const client = new QueryClient();
    syncUserQueryCache(client, { id: 7, email: "a@b.c" });
    expect(client.getQueryData(userQueryKey)).toEqual({ id: 7, email: "a@b.c" });
  });

  it("invalidateUserQuery refetches user", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mockFetchCurrentUser.mockResolvedValue({ id: 3, email: "x@y.z" });
    client.setQueryData(userQueryKey, null);

    await invalidateUserQuery(client);

    expect(mockFetchCurrentUser).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(userQueryKey)).toEqual({ id: 3, email: "x@y.z" });
  });
});
