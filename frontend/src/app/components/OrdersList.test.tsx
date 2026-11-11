import { describe, expect, it } from "vitest";
import { canOpenTracking, orderItemL2LabelRu, type Order } from "./OrdersList";

function order(over: Partial<Order> = {}): Order {
  return {
    id: 1,
    status: "created",
    total_amount: 100,
    ...over,
  };
}

describe("canOpenTracking", () => {
  it("is true when a shipment exists", () => {
    expect(
      canOpenTracking(
        order({
          shipments: [
            {
              id: 1,
              seq: 1,
              status: "preparing",
              status_label: "Готовится",
              supplier_tracking: {
                carrier: null,
                tracking_number: null,
                tracking_url: null,
              },
              customer_tracking: {
                carrier: null,
                tracking_number: null,
                tracking_url: null,
              },
            },
          ],
        }),
      ),
    ).toBe(true);
  });

  it("is true for legacy TP id and allowed status", () => {
    expect(
      canOpenTracking(order({ supplier_order_id: "TP-1", status: "assembling" })),
    ).toBe(true);
  });

  it("is false without shipments or TP id", () => {
    expect(canOpenTracking(order({ status: "delivery" }))).toBe(false);
  });

  it("is false for TP id with a status that is not yet shipping", () => {
    expect(
      canOpenTracking(order({ supplier_order_id: "TP-1", status: "processing" })),
    ).toBe(false);
  });
});

describe("orderItemL2LabelRu", () => {
  it("shows L2 RU label above the title contract", () => {
    expect(
      orderItemL2LabelRu({
        category_l2_label_ru: "Подарки",
        category_l3_label_ru: "Развлекательные товары",
      }),
    ).toBe("Подарки");
  });

  it("does not fall back to L3", () => {
    expect(
      orderItemL2LabelRu({
        category_l2_label_ru: null,
        category_l3_label_ru: "Футболки",
      }),
    ).toBeNull();
  });

  it("hides category when snapshot is missing", () => {
    expect(orderItemL2LabelRu({})).toBeNull();
  });
});
