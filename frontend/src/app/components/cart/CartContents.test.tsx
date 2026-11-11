import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { CartContents } from "./CartContents";
import type { ApiCart } from "../../../lib/storefront/checkoutUi";

vi.mock("../../../lib/storefront/miniAppUi", () => ({
  miniAppPillClass: () => "mini-pill",
}));

const cart: ApiCart = {
  items: [
    {
      product_id: 101,
      variant_id: 1,
      quantity: 2,
      price_snapshot: 5000,
      product_title: "Test Racket",
      product_brand: "Nox",
      product_image_url: "https://cdn.example/img.jpg",
      available_stock: 5,
    },
  ],
  total_amount: 10000,
  delivery_fee_amount: 0,
  total_with_delivery_amount: 10000,
};

describe("CartContents product links", () => {
  it("renders product title as link with return path state", () => {
    render(
      <MemoryRouter initialEntries={["/cart?promo=SAVE"]}>
        <CartContents
          cart={cart}
          loading={false}
          error={null}
          onChangeQty={vi.fn()}
          onCheckout={vi.fn()}
        />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "Test Racket" });
    expect(link.getAttribute("href")).toBe("/catalog/product/101");
  });
});
