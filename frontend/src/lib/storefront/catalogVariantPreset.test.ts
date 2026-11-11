import { describe, expect, it } from "vitest";

import { resolveVariantSelectionFromConstraints } from "./catalogVariantPreset";
import type { VariantConstraintPreset } from "./variantConstraintTypes";
import type { VariantSelectionProduct } from "./variantSelection";

const shoeProduct: VariantSelectionProduct = {
  variants: [
    { id: 1, option1: "Blue", option2: "36", inventory_quantity: 1, available: true },
    { id: 2, option1: "Blue", option2: "37", inventory_quantity: 1, available: true },
    { id: 3, option1: "Black", option2: "37", inventory_quantity: 1, available: true },
    { id: 4, option1: "Blue", option2: "38", inventory_quantity: 0, available: false },
  ],
};

const apparelProduct: VariantSelectionProduct = {
  variants: [
    { id: 10, option1: "M", option2: "Black", inventory_quantity: 1, available: true },
    { id: 11, option1: "L", option2: "Black", inventory_quantity: 1, available: true },
    { id: 12, option1: "M", option2: "Blue", inventory_quantity: 1, available: true },
  ],
};

const hiddenOptionProduct: VariantSelectionProduct = {
  variants: shoeProduct.variants,
  variant_options_hidden: ["option1"],
};

const decimalShoeProduct: VariantSelectionProduct = {
  variants: [
    { id: 1, option1: "Blue", option2: "37,5", inventory_quantity: 1, available: true },
  ],
};

describe("resolveVariantSelectionFromConstraints", () => {
  it("returns null for empty preset", () => {
    expect(resolveVariantSelectionFromConstraints(shoeProduct, [])).toBeNull();
  });

  it("resolves shoes size on option2", () => {
    const preset: VariantConstraintPreset = [{ id: "size", tokens: ["37"] }];
    expect(resolveVariantSelectionFromConstraints(shoeProduct, preset)).toEqual({
      option1: "Blue",
      option2: "37",
    });
  });

  it("resolves apparel size on option1", () => {
    const preset: VariantConstraintPreset = [
      { id: "color", tokens: ["Black"] },
      { id: "size", tokens: ["M"] },
    ];
    expect(resolveVariantSelectionFromConstraints(apparelProduct, preset)).toEqual({
      option1: "M",
      option2: "Black",
    });
  });

  it("resolves OR inside a group", () => {
    const preset: VariantConstraintPreset = [
      { id: "color", tokens: ["Black", "Blue"] },
      { id: "size", tokens: ["37"] },
    ];
    expect(resolveVariantSelectionFromConstraints(shoeProduct, preset)).toEqual({
      option1: "Black",
      option2: "37",
    });
  });

  it("skips hidden options", () => {
    const preset: VariantConstraintPreset = [{ id: "color", tokens: ["Blue"] }];
    expect(resolveVariantSelectionFromConstraints(hiddenOptionProduct, preset)).toBeNull();
  });

  it("ignores out-of-stock-only matches when requireInStock is true", () => {
    const preset: VariantConstraintPreset = [{ id: "size", tokens: ["38"] }];
    expect(resolveVariantSelectionFromConstraints(shoeProduct, preset)).toBeNull();
  });

  it("returns null when no variant matches", () => {
    const preset: VariantConstraintPreset = [{ id: "size", tokens: ["99"] }];
    expect(resolveVariantSelectionFromConstraints(shoeProduct, preset)).toBeNull();
  });

  it("matches decimal size tokens case-insensitively", () => {
    const preset: VariantConstraintPreset = [{ id: "size", tokens: ["37,5"] }];
    expect(resolveVariantSelectionFromConstraints(decimalShoeProduct, preset)).toEqual({
      option1: "Blue",
      option2: "37,5",
    });
  });

  it("matches color tokens case-insensitively", () => {
    const preset: VariantConstraintPreset = [{ id: "color", tokens: ["blue"] }];
    expect(resolveVariantSelectionFromConstraints(shoeProduct, preset)).toEqual({
      option1: "Blue",
      option2: "36",
    });
  });
});
