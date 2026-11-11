import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MiniAppBottomNav } from "./MiniAppBottomNav";

const navigate = vi.fn();

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock("../../hooks/useCart", () => ({
  useCart: vi.fn(() => ({
    cart: { items: [{ product_id: 1, quantity: 2 }] },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

function renderNav(initialEntry = "/account?tab=profile") {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <MiniAppBottomNav />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MiniAppBottomNav", () => {
  afterEach(() => {
    cleanup();
    navigate.mockReset();
  });

  it("navigates to support tab from Поддержка button", async () => {
    const user = userEvent.setup();
    renderNav();

    await user.click(screen.getByRole("button", { name: "Поддержка" }));
    expect(navigate).toHaveBeenCalledWith("/account?tab=support");
  });

  it("shows cart count from useCart without direct fetch", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderNav("/catalog");

    expect(screen.getByText("2")).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
