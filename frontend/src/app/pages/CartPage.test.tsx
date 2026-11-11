import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { CartPage } from "./CartPage";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    isAuthenticated: true,
  }),
}));

vi.mock("../../lib/storefront/useStorefrontSurface", () => ({
  useStorefrontCompact: () => false,
  useStorefrontCompactPagePad: () => "",
}));

vi.mock("../../lib/storefront/useRefreshOnPageActive", () => ({
  useRefreshOnPageActive: () => {},
}));

vi.mock("../../hooks/useCart", () => ({
  cartQueryKey: ["cart", "me"],
  useCart: vi.fn(() => ({
    cart: { items: [{ product_id: 1, quantity: 1, product_title: "Racket" }] },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  })),
}));

function renderCartPage() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CartPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CartPage", () => {
  it("renders cart from useCart without direct fetch", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderCartPage();

    expect(screen.getByRole("heading", { name: "Корзина" })).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
