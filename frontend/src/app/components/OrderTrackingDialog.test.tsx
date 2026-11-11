import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { storefrontApiFetch } from "../../lib/storefront/api";
import type { OrderShipment } from "./OrdersList";
import {
  OrderTrackingDialog,
  orderTrackingUi,
  SHIPMENT_INFO_DISMISSED_KEY,
} from "./OrderTrackingDialog";

vi.mock("../../lib/storefront/api", () => ({
  storefrontApiFetch: vi.fn(),
}));

vi.mock("./StorefrontModalFrame", () => ({
  StorefrontModalFrame: ({
    title,
    titleAddon,
    children,
  }: {
    title: string;
    titleAddon?: ReactNode;
    children: ReactNode;
  }) => (
    <section aria-label={title}>
      {titleAddon}
      {children}
    </section>
  ),
}));

const mockFetch = vi.mocked(storefrontApiFetch);

const emptyTracking = {
  carrier: null,
  tracking_number: null,
  tracking_url: null,
};

const basePayload = {
  available: true,
  current_stage: "in_transit",
  current_status: "В пути",
  current_description: null,
  carrier_label: "DHL / Russian Post",
  last_updated_at: "2026-07-07T12:00:00Z",
  events: [
    {
      key: "latest",
      at: "2026-07-07T17:17:59Z",
      stage: "in_transit",
      title: "В пути",
    },
    {
      key: "paid",
      at: "2026-07-05T10:00:00Z",
      stage: "paid",
      title: "Заказ оплачен",
      description: "Оплата прошла успешно",
    },
  ],
};


function makeTwoShipments(): OrderShipment[] {
  return [
    makeShipment({ id: 1, seq: 1 }),
    makeShipment({ id: 2, seq: 2 }),
  ];
}

function makeShipment(over: Partial<OrderShipment> = {}): OrderShipment {
  return {
    id: 11,
    seq: 1,
    status: "in_transit",
    status_label: "В пути",
    supplier_tracking: { ...emptyTracking },
    customer_tracking: { ...emptyTracking },
    ...over,
  };
}

describe("orderTrackingUi", () => {
  it("marks first event as current when order is active", () => {
    expect(
      orderTrackingUi.resolveTimelineState(0, { key: "1", stage: "in_transit", title: "В пути", at: "x" }, false),
    ).toBe("current");
    expect(
      orderTrackingUi.resolveTimelineState(1, { key: "2", stage: "paid", title: "Оплачен", at: "x" }, false),
    ).toBe("completed");
  });

  it("always shows description under current status", () => {
    expect(
      orderTrackingUi.resolveCurrentDescription({
        available: true,
        current_stage: "in_transit",
        current_status: "В пути",
        events: [],
      }),
    ).toBe("Посылка движется к вам.");
    expect(
      orderTrackingUi.resolveCurrentDescription({
        available: true,
        current_stage: "in_transit",
        current_status: "В пути",
        current_description: "Из API",
        events: [],
      }),
    ).toBe("Из API");
  });

  it("treats missing event time as muted", () => {
    expect(
      orderTrackingUi.resolveTimelineState(0, { key: "1", stage: "in_transit", title: "В пути" }, false),
    ).toBe("muted");
  });
});

describe("OrderTrackingDialog", () => {
  afterEach(() => {
    cleanup();
    mockFetch.mockReset();
    localStorage.clear();
  });

  it("renders status and timeline in one card", async () => {
    mockFetch.mockResolvedValue(basePayload);

    render(<OrderTrackingDialog orderId={42} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(mockFetch).toHaveBeenCalledWith("/orders/42/tracking");
    expect(screen.getByText("№42")).toBeTruthy();
    expect(screen.getAllByText("В пути").length).toBeGreaterThan(0);
    expect(screen.getByText("Посылка движется к вам.")).toBeTruthy();
    expect(screen.getByText("История заказа")).toBeTruthy();
    expect(screen.getByText("Заказ оплачен")).toBeTruthy();
    expect(screen.queryByText("Germany")).toBeNull();
  });

  it("shows loading skeleton before data arrives", () => {
    mockFetch.mockReturnValue(new Promise(() => undefined));

    render(<OrderTrackingDialog orderId={42} onClose={() => undefined} />);

    expect(screen.getByLabelText("Загрузка движения заказа")).toBeTruthy();
  });

  it("shows error state with retry", async () => {
    mockFetch.mockRejectedValueOnce(new Error("network"));
    mockFetch.mockResolvedValueOnce(basePayload);

    render(<OrderTrackingDialog orderId={42} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(screen.getByText("Повторить")).toBeTruthy();
    fireEvent.click(screen.getByText("Повторить"));
    await act(async () => Promise.resolve());

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("В пути").length).toBeGreaterThan(0);
  });

  it("shows empty state when timeline is unavailable", async () => {
    mockFetch.mockResolvedValue({
      ...basePayload,
      available: false,
      events: [],
    });

    render(<OrderTrackingDialog orderId={42} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(screen.getByText("Этапы появятся здесь")).toBeTruthy();
  });

  it("renders delivered order without current pulse state", async () => {
    mockFetch.mockResolvedValue({
      ...basePayload,
      current_stage: "delivered",
      current_status: "Доставлен",
      events: [
        {
          key: "delivered",
          at: "2026-07-08T16:00:00Z",
          stage: "delivered",
          title: "Доставлен",
        },
      ],
    });

    render(<OrderTrackingDialog orderId={42} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(screen.getAllByText("Доставлен").length).toBeGreaterThan(0);
    expect(orderTrackingUi.isTerminalStage("delivered")).toBe(true);
  });

  it("renders fallback carrier events like regular timeline", async () => {
    mockFetch.mockResolvedValue({
      available: true,
      current_stage: "in_transit",
      current_status: "В пути",
      current_description: null,
      carrier_label: "DHL",
      last_updated_at: "2026-07-07T12:00:00Z",
      events: [
        {
          key: "carrier",
          at: "2026-07-07T17:17:59Z",
          stage: "in_transit",
          title: "В пути",
        },
        {
          key: "paid",
          at: "2026-07-05T10:00:00Z",
          stage: "paid",
          title: "Заказ оплачен",
        },
      ],
    });

    render(<OrderTrackingDialog orderId={7} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(screen.getAllByText("В пути").length).toBeGreaterThan(0);
  });

  it("calls legacy tracking when shipments are empty", async () => {
    mockFetch.mockResolvedValue(basePayload);

    render(<OrderTrackingDialog orderId={42} shipments={[]} onClose={() => undefined} />);
    await act(async () => Promise.resolve());

    expect(mockFetch).toHaveBeenCalledWith("/orders/42/tracking");
    expect(screen.getByText("История заказа")).toBeTruthy();
  });

  it("does not fetch tracking when shipments are present", async () => {
    render(
      <OrderTrackingDialog
        orderId={42}
        shipments={[makeShipment()]}
        onClose={() => undefined}
      />,
    );
    await act(async () => Promise.resolve());

    expect(mockFetch).not.toHaveBeenCalled();
    expect(screen.queryByText("История заказа")).toBeNull();
    expect(screen.getByText("Посылка 1")).toBeTruthy();
  });

  it("renders two shipment cards", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({ id: 1, seq: 1, status_label: "Доставлена", status: "delivered" }),
          makeShipment({ id: 2, seq: 2, status_label: "В пути", status: "in_transit" }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Посылка 1")).toBeTruthy();
    expect(screen.getByText("Посылка 2")).toBeTruthy();
    expect(screen.getByText("Доставлена")).toBeTruthy();
    expect(screen.getByText("В пути")).toBeTruthy();
  });

  it("shows CJ and DHL/Pochta links from customer_tracking.links", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            supplier_tracking: {
              carrier: "DHL",
              tracking_number: "CJ123456",
              tracking_url: "https://www.dhl.com/track?id=CJ123456",
            },
            customer_tracking: {
              carrier: "Почта России",
              tracking_number: "12345678901234",
              tracking_url: null,
              links: [
                {
                  carrier: "DHL",
                  url: "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ123456",
                },
                {
                  carrier: "Pochta",
                  url: "https://www.pochta.ru/tracking?barcode=CJ123456",
                },
              ],
            },
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("CJ123456")).toBeTruthy();
    expect(screen.queryByText("Поставщик → РФ")).toBeNull();
    expect(screen.queryByText("РФ → клиент")).toBeNull();
    expect(screen.queryByText("12345678901234")).toBeNull();
    expect(screen.getByText("Трек-номер")).toBeTruthy();
    expect(screen.queryByText("Отследить DHL")).toBeNull();
    expect(screen.queryByText("Отследить Почта России")).toBeNull();
    const dhl = screen.getByRole("link", { name: "DHL" });
    const pochta = screen.getByRole("link", { name: "Почта России" });
    expect(dhl.getAttribute("href")).toBe(
      "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ123456",
    );
    expect(pochta.getAttribute("href")).toBe("https://www.pochta.ru/tracking?barcode=CJ123456");
    expect(dhl.getAttribute("target")).toBe("_blank");
    expect(dhl.getAttribute("rel")).toBe("noopener noreferrer");
  });


  it("renders links when customer_tracking.tracking_number is null", () => {
    render(
      <OrderTrackingDialog
        orderId={1074}
        shipments={[
          makeShipment({
            supplier_tracking: {
              carrier: "DHL / Russian Post",
              tracking_number: "CJ688018359DE",
              tracking_url:
                "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ688018359DE",
            },
            customer_tracking: {
              carrier: null,
              tracking_number: null,
              tracking_url: null,
              links: [
                {
                  carrier: "DHL",
                  url: "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ688018359DE",
                },
                {
                  carrier: "Pochta",
                  url: "https://www.pochta.ru/tracking?barcode=CJ688018359DE",
                },
              ],
            },
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("CJ688018359DE")).toBeTruthy();
    expect(screen.getByRole("link", { name: "DHL" }).getAttribute("href")).toBe(
      "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ688018359DE",
    );
    expect(
      screen.getByRole("link", { name: "Почта России" }).getAttribute("href"),
    ).toBe("https://www.pochta.ru/tracking?barcode=CJ688018359DE");
  });

  it("hides tracking buttons when CJ exists but links are empty", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            supplier_tracking: {
              carrier: "DHL",
              tracking_number: "CJNOURL",
              tracking_url: null,
            },
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("CJNOURL")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows waiting copy and no links when CJ is missing", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            status: "preparing",
            status_label: "Готовится",
            customer_tracking: {
              carrier: "Почта России",
              tracking_number: "RP-ONLY",
              tracking_url: "https://www.pochta.ru/tracking?barcode=RP-ONLY",
              links: [
                {
                  carrier: "DHL",
                  url: "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=RP-ONLY",
                },
              ],
            },
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Трек-номер ещё не получен")).toBeTruthy();
    expect(screen.queryByText("RP-ONLY")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Готовится")).toBeTruthy();
  });

  it("shows shipment status_label instead of raw status", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[makeShipment({ status: "in_transit", status_label: "В пути" })]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("В пути")).toBeTruthy();
    expect(screen.queryByText("in_transit")).toBeNull();
    expect(screen.queryByText("Ожидает оплаты")).toBeNull();
  });

  it("renders every shipment in one dialog", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({ id: 1, seq: 1 }),
          makeShipment({ id: 2, seq: 2 }),
          makeShipment({ id: 3, seq: 3, status_label: "Готовится", status: "preparing" }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Посылка 1")).toBeTruthy();
    expect(screen.getByText("Посылка 2")).toBeTruthy();
    expect(screen.getByText("Посылка 3")).toBeTruthy();
  });

  it("renders four shipment cards", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({ id: 1, seq: 1 }),
          makeShipment({ id: 2, seq: 2 }),
          makeShipment({ id: 3, seq: 3 }),
          makeShipment({ id: 4, seq: 4 }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Посылка 1")).toBeTruthy();
    expect(screen.getByText("Посылка 2")).toBeTruthy();
    expect(screen.getByText("Посылка 3")).toBeTruthy();
    expect(screen.getByText("Посылка 4")).toBeTruthy();
  });

  it("keeps shipment items on their own card", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            id: 1,
            seq: 1,
            items: [
              { order_item_id: 10, quantity: 1, display_title: "Curva Speed 2026 Padel racket" },
            ],
          }),
          makeShipment({
            id: 2,
            seq: 2,
            items: [{ order_item_id: 11, quantity: 2, product_title: "Racket bag" }],
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Curva Speed 2026 Padel racket")).toBeTruthy();
    expect(screen.getByText("Racket bag")).toBeTruthy();
    expect(screen.getByText("× 1")).toBeTruthy();
    expect(screen.getByText("× 2")).toBeTruthy();
    const first = screen.getByLabelText("Посылка 1");
    const second = screen.getByLabelText("Посылка 2");
    expect(first.textContent).toContain("Curva Speed 2026 Padel racket");
    expect(first.textContent).not.toContain("Racket bag");
    expect(second.textContent).toContain("Racket bag");
    expect(second.textContent).not.toContain("Curva Speed 2026 Padel racket");
  });

  it("shows a neutral empty state when shipment items are missing", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[makeShipment({ items: [] })]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Состав посылки пока недоступен")).toBeTruthy();
    expect(screen.queryByText(/Товары ·/)).toBeNull();
  });

  it("keeps DHL and Pochta URLs on the matching shipment CJ", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            id: 1,
            seq: 1,
            supplier_tracking: {
              carrier: "DHL",
              tracking_number: "CJ-1",
              tracking_url: null,
            },
            customer_tracking: {
              ...emptyTracking,
              links: [
                {
                  carrier: "DHL",
                  url: "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ-1",
                },
                { carrier: "Pochta", url: "https://www.pochta.ru/tracking?barcode=CJ-1" },
              ],
            },
          }),
          makeShipment({
            id: 2,
            seq: 2,
            supplier_tracking: {
              carrier: "DHL",
              tracking_number: "CJ-2",
              tracking_url: null,
            },
            customer_tracking: {
              ...emptyTracking,
              links: [
                {
                  carrier: "DHL",
                  url: "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ-2",
                },
                { carrier: "Pochta", url: "https://www.pochta.ru/tracking?barcode=CJ-2" },
              ],
            },
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    const first = screen.getByLabelText("Посылка 1");
    const second = screen.getByLabelText("Посылка 2");
    expect(first.textContent).toContain("CJ-1");
    expect(first.textContent).not.toContain("CJ-2");
    expect(second.textContent).toContain("CJ-2");
    expect(second.textContent).not.toContain("CJ-1");
    const firstLinks = first.querySelectorAll("a");
    const secondLinks = second.querySelectorAll("a");
    expect([...firstLinks].map((node) => node.getAttribute("href"))).toEqual([
      "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ-1",
      "https://www.pochta.ru/tracking?barcode=CJ-1",
    ]);
    expect([...secondLinks].map((node) => node.getAttribute("href"))).toEqual([
      "https://www.dhl.de/en/privatkunden/pakete-empfangen/verfolgen.html?piececode=CJ-2",
      "https://www.pochta.ru/tracking?barcode=CJ-2",
    ]);
  });

  it("keeps four shipment cards and items isolated", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            id: 1,
            seq: 1,
            items: [{ order_item_id: 10, quantity: 1, display_title: "Item A" }],
          }),
          makeShipment({
            id: 2,
            seq: 2,
            items: [{ order_item_id: 20, quantity: 1, display_title: "Item B" }],
          }),
          makeShipment({
            id: 3,
            seq: 3,
            items: [{ order_item_id: 30, quantity: 1, display_title: "Item C" }],
          }),
          makeShipment({
            id: 4,
            seq: 4,
            items: [{ order_item_id: 40, quantity: 1, display_title: "Item D" }],
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    const cards = [1, 2, 3, 4].map((seq) => screen.getByLabelText(`Посылка ${seq}`));
    expect(cards[0]?.textContent).toContain("Item A");
    expect(cards[0]?.textContent).not.toContain("Item B");
    expect(cards[1]?.textContent).toContain("Item B");
    expect(cards[1]?.textContent).not.toContain("Item C");
    expect(cards[2]?.textContent).toContain("Item C");
    expect(cards[3]?.textContent).toContain("Item D");
    expect(cards[3]?.textContent).not.toContain("Item A");
  });

  it("does not render supplier or internal item fields", () => {
    render(
      <OrderTrackingDialog
        orderId={9}
        shipments={[
          makeShipment({
            supplier_tracking: {
              carrier: "DHL",
              tracking_number: "CJHIDE",
              tracking_url: "https://tracking.parcellab.com/CJHIDE",
            },
            items: [
              {
                order_item_id: 777001,
                quantity: 1,
                display_title: "Visible racket",
              },
            ],
          }),
        ]}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("Visible racket")).toBeTruthy();
    expect(screen.queryByText("777001")).toBeNull();
    expect(screen.queryByText(/unit_supplier/)).toBeNull();
    expect(screen.queryByText(/supplier_order/i)).toBeNull();
    expect(screen.queryByText(/TP-/)).toBeNull();
    expect(screen.queryByText(/parcellab/i)).toBeNull();
    expect(screen.queryByText("Поставщик → РФ")).toBeNull();
  });
  describe("multi-shipment info hint", () => {
    it("hides hint for a single shipment", () => {
      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={[makeShipment()]}
          onClose={() => undefined}
        />,
      );

      expect(screen.queryByText("Информация")).toBeNull();
      expect(screen.queryByText("Как доставляются посылки")).toBeNull();
    });

    it("hides hint for legacy timeline without shipments", async () => {
      mockFetch.mockResolvedValue(basePayload);

      render(<OrderTrackingDialog orderId={42} shipments={[]} onClose={() => undefined} />);
      await act(async () => Promise.resolve());

      expect(screen.queryByText("Информация")).toBeNull();
      expect(screen.queryByText("Как доставляются посылки")).toBeNull();
      expect(screen.getByText("История заказа")).toBeTruthy();
    });

    it("shows expanded hint on first visit with multiple shipments", () => {
      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={makeTwoShipments()}
          onClose={() => undefined}
        />,
      );

      expect(screen.getByText("Информация")).toBeTruthy();
      expect(screen.getByText(/для каждой посылки будет предоставлен отдельный трек-номер/)).toBeTruthy();
      expect(screen.queryByText("Как доставляются посылки")).toBeNull();
    });

    it("dismisses hint, shows compact button, and persists localStorage", () => {
      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={makeTwoShipments()}
          onClose={() => undefined}
        />,
      );

      fireEvent.click(screen.getByLabelText("Скрыть подсказку"));

      expect(screen.queryByText("Информация")).toBeNull();
      expect(screen.getByText("Как доставляются посылки")).toBeTruthy();
      expect(localStorage.getItem(SHIPMENT_INFO_DISMISSED_KEY)).toBe("true");
    });

    it("re-expands hint from the compact button", () => {
      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={makeTwoShipments()}
          onClose={() => undefined}
        />,
      );

      fireEvent.click(screen.getByLabelText("Скрыть подсказку"));
      fireEvent.click(screen.getByText("Как доставляются посылки"));

      expect(screen.getByText("Информация")).toBeTruthy();
    });

    it("shows compact button when localStorage is already dismissed", () => {
      localStorage.setItem(SHIPMENT_INFO_DISMISSED_KEY, "true");

      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={makeTwoShipments()}
          onClose={() => undefined}
        />,
      );

      expect(screen.queryByText("Информация")).toBeNull();
      expect(screen.getByText("Как доставляются посылки")).toBeTruthy();
    });

    it("returns to compact button after second dismiss", () => {
      localStorage.setItem(SHIPMENT_INFO_DISMISSED_KEY, "true");

      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={makeTwoShipments()}
          onClose={() => undefined}
        />,
      );

      fireEvent.click(screen.getByText("Как доставляются посылки"));
      fireEvent.click(screen.getByLabelText("Скрыть подсказку"));

      expect(screen.queryByText("Информация")).toBeNull();
      expect(screen.getByText("Как доставляются посылки")).toBeTruthy();
    });

    it("shows only one hint for four shipments", () => {
      render(
        <OrderTrackingDialog
          orderId={9}
          shipments={[
            makeShipment({ id: 1, seq: 1 }),
            makeShipment({ id: 2, seq: 2 }),
            makeShipment({ id: 3, seq: 3 }),
            makeShipment({ id: 4, seq: 4 }),
          ]}
          onClose={() => undefined}
        />,
      );

      expect(screen.getAllByText("Информация").length).toBe(1);
      expect(screen.queryByText("Как доставляются посылки")).toBeNull();
    });
  });

});
