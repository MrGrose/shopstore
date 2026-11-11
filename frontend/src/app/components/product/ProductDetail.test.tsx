import { describe, expect, it } from "vitest";
import {
  getVariantOptionKeys,
  getVariantValues,
  getVisibleVariantOptionKeys,
} from "./ProductDetail";

const padelVariants = [
  {
    id: 1,
    option1: "full-surface",
    option2: "2",
    inventory_quantity: 1,
    available: true,
  },
];

const padelMultiSurfaceVariants = [
  { id: 1, option1: "full-surface", inventory_quantity: 1, available: true },
  { id: 2, option1: "rough-surface", inventory_quantity: 1, available: true },
];

const tennisVariants = [
  {
    id: 10,
    option1: "full-surface",
    option2: "3",
    inventory_quantity: 1,
    available: true,
  },
];

const shoeVariants = [
  { id: 1, option1: "Blue", option2: "36", inventory_quantity: 1, available: true },
  { id: 2, option1: "Blue", option2: "37", inventory_quantity: 1, available: true },
  { id: 3, option1: "Blue", option2: "37,5", inventory_quantity: 1, available: true },
  { id: 4, option1: "Blue", option2: "38", inventory_quantity: 1, available: true },
  { id: 5, option1: "Blue", option2: "40", inventory_quantity: 1, available: true },
  { id: 6, option1: "Blue", option2: "42", inventory_quantity: 1, available: true },
  { id: 7, option1: "Blue", option2: "44", inventory_quantity: 1, available: true },
  { id: 8, option1: "Blue", option2: "39,5", inventory_quantity: 1, available: true },
  { id: 9, option1: "Blue", option2: "41,5", inventory_quantity: 1, available: true },
  { id: 10, option1: "Blue", option2: "43,5", inventory_quantity: 1, available: true },
];

describe("getVariantValues", () => {
  it("keeps API size order with comma decimals between whole sizes", () => {
    const ordered = [
      "36",
      "37",
      "37,5",
      "38",
      "39,5",
      "40",
      "41,5",
      "42",
      "43,5",
      "44",
    ];
    expect(getVariantValues(shoeVariants, "option2", ordered)).toEqual(ordered);
  });
});

describe("getVisibleVariantOptionKeys", () => {
  it("hides redundant padel surface option1", () => {
    const keys = getVisibleVariantOptionKeys({
      variants: padelVariants,
      variant_options_hidden: ["option1"],
    });
    expect(keys).toEqual(["option2"]);
    expect(getVariantOptionKeys(padelVariants)).toEqual(["option1", "option2"]);
  });

  it("keeps tennis surface selector visible", () => {
    const keys = getVisibleVariantOptionKeys({
      variants: tennisVariants,
      variant_options_hidden: [],
    });
    expect(keys).toEqual(["option1", "option2"]);
  });

  it("keeps padel surface when multiple values exist", () => {
    const keys = getVisibleVariantOptionKeys({
      variants: padelMultiSurfaceVariants,
      variant_options_hidden: [],
    });
    expect(keys).toEqual(["option1"]);
  });
});
