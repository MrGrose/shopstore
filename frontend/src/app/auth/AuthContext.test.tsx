import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./AuthContext";

vi.mock("../../hooks/useUser", () => ({
  useUser: () => ({
    user: { id: 1, name: "Anna", phone: "+79990000000", email: null, telegram_id: null, telegram_username: null, is_active: true },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
  userQueryKey: ["user", "me"],
  invalidateUserQuery: vi.fn(),
  syncUserQueryCache: vi.fn(),
}));

vi.mock("../../hooks/useMiniAppAuthState", () => ({
  useMiniAppAuthState: () => ({
    bootstrapping: false,
    miniAppAuthError: null,
    miniAppAuthDebug: null,
    loginUnavailable: false,
    retryMiniAppLogin: vi.fn(),
    clearMiniAppAuthError: vi.fn(),
  }),
}));

function Probe() {
  const { isAuthenticated, user } = useAuth();
  return (
    <div>
      {isAuthenticated ? "auth-yes" : "auth-no"}
      <span>{user?.name}</span>
    </div>
  );
}

describe("AuthProvider", () => {
  it("exposes authenticated user from useUser", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("auth-yes")).toBeTruthy();
    expect(screen.getByText("Anna")).toBeTruthy();
  });
});
