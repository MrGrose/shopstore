import { describe, expect, it } from "vitest";

import {
  isStorefrontVariantBuyable,
  resolveVariantBuyableQty,
  stockStatusExtraClass,
} from "./variantStock";

describe("variantStock API fields", () => {
  it("prefers buyable_qty from API", () => {
    expect(
      resolveVariantBuyableQty({
        inventory_quantity: 0,
        available: true,
        buyable_qty: 3,
      }),
    ).toBe(3);
  });

  it("uses stock_status for buyable check", () => {
    expect(
      isStorefrontVariantBuyable({
        inventory_quantity: 5,
        available: true,
        stock_status: "out_of_stock",
      }),
    ).toBe(false);
    expect(
      isStorefrontVariantBuyable({
        inventory_quantity: 0,
        available: false,
        stock_status: "in_stock",
      }),
    ).toBe(true);
  });

  it("maps stock_status to badge class", () => {
    expect(stockStatusExtraClass("out_of_stock")).toBe("out-of-stock");
    expect(stockStatusExtraClass("low")).toBe("stock-badge--low");
    expect(stockStatusExtraClass("in_stock")).toBe("");
  });
});
