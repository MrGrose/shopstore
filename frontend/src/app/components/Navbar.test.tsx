import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { Navbar } from "./Navbar";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    isAuthenticated: false,
    user: null,
    logout: vi.fn(),
  }),
}));

vi.mock("../../lib/storefront/useStorefrontSurface", () => ({
  useStorefrontCompact: () => false,
}));

vi.mock("../../hooks/useCart", () => ({
  cartQueryKey: ["cart", "me"],
  useCart: vi.fn(() => ({
    cart: { items: [{ product_id: 1, quantity: 2 }] },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

function renderNavbar() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Navbar", () => {
  it("shows cart count from useCart without direct fetch", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderNavbar();

    expect(screen.getByLabelText("Корзина, 2 товаров")).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
