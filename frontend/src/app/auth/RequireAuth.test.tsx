import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "./RequireAuth";

const retryMiniAppLogin = vi.fn();

const authState = {
  isAuthenticated: false,
  loading: false,
  bootstrapping: false,
  miniAppAuthError: null as string | null,
  miniAppAuthDebug: null as string | null,
  loginUnavailable: false,
  retryMiniAppLogin,
};

vi.mock("./AuthContext", () => ({
  useAuth: () => authState,
}));

function renderGate(path = "/account") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RequireAuth>
        <div>account-ok</div>
      </RequireAuth>
    </MemoryRouter>,
  );
}

describe("RequireAuth Mini App", () => {
  afterEach(() => {
    cleanup();
    retryMiniAppLogin.mockReset();
    authState.isAuthenticated = false;
    authState.loading = false;
    authState.bootstrapping = false;
    authState.miniAppAuthError = null;
    authState.loginUnavailable = false;
    window.history.pushState({}, "", "/");
  });

  it("renders Account when Mini App auth is authenticated", () => {
    window.history.pushState({}, "", "/app/account");
    authState.isAuthenticated = true;
    renderGate("/account");
    expect(screen.getByText("account-ok")).toBeTruthy();
  });

  it("renders Support when Mini App auth is authenticated", () => {
    window.history.pushState({}, "", "/app/account?tab=support");
    authState.isAuthenticated = true;
    renderGate("/account?tab=support");
    expect(screen.getByText("account-ok")).toBeTruthy();
  });

  it("shows retry when Mini App bootstrap finished unauthenticated", () => {
    window.history.pushState({}, "", "/app/account");
    authState.miniAppAuthError = "Telegram SDK не загрузился. Проверьте интернет и откройте магазин снова из бота.";
    renderGate("/account");
    expect(screen.getByRole("button", { name: "Повторить вход" })).toBeTruthy();
    expect(screen.queryByText("account-ok")).toBeNull();
  });
});
