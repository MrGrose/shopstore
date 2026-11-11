import { beforeEach, describe, expect, it, vi } from "vitest";
import { addCartItem, changeCartQty } from "./cart";

vi.mock("./api", () => ({
  storefrontApiFetch: vi.fn(),
}));

import { storefrontApiFetch } from "./api";

const mockFetch = vi.mocked(storefrontApiFetch);

describe("addCartItem", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("POSTs product_id and quantity", async () => {
    mockFetch.mockResolvedValue({ items: [{ product_id: 1, quantity: 1 }] });
    await addCartItem(42);
    expect(mockFetch).toHaveBeenCalledWith("/cart/me/items", {
      method: "POST",
      body: JSON.stringify({ product_id: 42, quantity: 1 }),
    });
  });

  it("includes variant_id when provided", async () => {
    mockFetch.mockResolvedValue({ items: [] });
    await addCartItem(42, 7, 2);
    expect(mockFetch).toHaveBeenCalledWith("/cart/me/items", {
      method: "POST",
      body: JSON.stringify({ product_id: 42, quantity: 2, variant_id: 7 }),
    });
  });

  it("returns empty cart when API returns null", async () => {
    mockFetch.mockResolvedValue(null);
    const cart = await addCartItem(1);
    expect(cart).toEqual({ items: [] });
  });
});

describe("changeCartQty", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("PUTs quantity for positive qty", async () => {
    mockFetch.mockResolvedValue({ items: [] });
    await changeCartQty(10, 3, 5);
    expect(mockFetch).toHaveBeenCalledWith("/cart/me/items/10?variant_id=5", {
      method: "PUT",
      body: JSON.stringify({ quantity: 3 }),
    });
  });

  it("DELETEs when quantity is zero", async () => {
    mockFetch.mockResolvedValue(null);
    await changeCartQty(10, 0);
    expect(mockFetch).toHaveBeenCalledWith("/cart/me/items/10", {
      method: "DELETE",
    });
  });
});
