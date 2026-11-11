import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CheckoutContent } from "./CheckoutPage";

vi.stubGlobal(
  "ResizeObserver",
  class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

document.elementFromPoint = () => null;

vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: {
      telegram_id: 123,
      telegram_username: "linked_user",
      identities: [{ provider: "telegram", telegram_username: "linked_user" }],
    },
    refresh: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock("../../lib/storefront/identities", () => ({
  createTelegramLink: vi.fn().mockResolvedValue({ url: "https://t.me/test" }),
  sendLinkEmailCode: vi.fn().mockResolvedValue(undefined),
  verifyLinkEmail: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../auth/RequireAuth", () => ({
  RequireAuth: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("../components/PaymentDialog", () => ({
  PaymentDialog: ({ open, orderId, title }: { open: boolean; orderId: number; title?: string }) =>
    open ? <div data-testid="payment-dialog">{title || orderId}</div> : null,
}));

vi.mock("../../lib/storefront/useStorefrontSurface", () => ({
  useStorefrontCompact: () => false,
  useStorefrontCompactPagePad: () => "",
  useStorefrontBottomNav: () => false,
}));

vi.mock("../../lib/storefront/deliveryProfile", () => ({
  fetchDeliveryProfile: vi.fn().mockResolvedValue({
    last_name: "Ivanov",
    first_name: "Ivan",
    street: "Tverskaya",
    house: "1",
    apartment: "",
    city: "Moscow",
    postal_code: "101000",
    phone: "+79991234567",
  }),
}));

vi.mock("../../lib/storefront/api", () => {
  class StorefrontApiError extends Error {
    apiDetail?: unknown;
    status: number;
    userMessage: string;

    constructor(userMessage: string, status: number, apiDetail?: unknown) {
      super(userMessage);
      this.name = "StorefrontApiError";
      this.userMessage = userMessage;
      this.status = status;
      this.apiDetail = apiDetail;
    }
  }

  return {
    StorefrontApiError,
    storefrontApiFetch: vi.fn(),
  };
});

import { StorefrontApiError, storefrontApiFetch } from "../../lib/storefront/api";
import { useAuth } from "../auth/AuthContext";
import {
  createTelegramLink,
  sendLinkEmailCode,
  verifyLinkEmail,
} from "../../lib/storefront/identities";

const mockFetch = vi.mocked(storefrontApiFetch);

const cartResponse = {
  items: [
    {
      product_id: 1,
      quantity: 1,
      price_snapshot: "100.00",
      product_title: "Racket",
    },
  ],
};

const previewResponse = {
  total_amount: "100.00",
  items_subtotal_amount: "100.00",
  discount_items_amount: "0",
  delivery_fee_amount: "0",
};

function renderCheckout() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CheckoutContent />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function submitOrder(created: Record<string, unknown>) {
  mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/cart/me") return cartResponse;
    if (url === "/storefront/social") return { bot_username: "test_bot" };
    if (url === "/orders/checkout/preview") return previewResponse;
    if (url === "/orders/checkout" && init?.method === "POST") return created;
    return null;
  });

  renderCheckout();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Оформить заказ — недоступно" }),
    ).toBeTruthy(),
  );
  const checkboxes = screen.getAllByRole("checkbox");
  await userEvent.click(checkboxes[0]);
  await userEvent.click(checkboxes[2]);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Оформить заказ" })).toBeTruthy(),
  );
  await userEvent.click(screen.getByRole("button", { name: "Оформить заказ" }));
}

describe("CheckoutPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.mocked(useAuth).mockReturnValue({
      user: {
        telegram_id: 123,
        telegram_username: "linked_user",
        identities: [{ provider: "telegram", telegram_username: "linked_user" }],
      },
      refresh: vi.fn().mockResolvedValue(undefined),
    } as never);
  });

  afterEach(async () => {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    cleanup();
  });

  it("opens PaymentDialog immediately after successful checkout", async () => {
    await submitOrder({
      id: 42,
      payment_allowed: true,
      payment_gateway_enabled: true,
      total_amount: "100.00",
      availability_confirmation_status: "not_required",
    });

    await waitFor(() => {
      expect(screen.getByTestId("payment-dialog")).toBeTruthy();
    });
    expect(screen.getByText("Оплата заказа №42")).toBeTruthy();
    expect(screen.queryByText("Заказ принят")).toBeNull();
  });

  it("shows disabled pending payment button after checkout", async () => {
    await submitOrder({
      id: 43,
      payment_allowed: false,
      payment_gateway_enabled: true,
      total_amount: "100.00",
      availability_confirmation_status: "pending",
    });

    await waitFor(() => {
      expect(screen.getByText("Заказ №43 оформлен")).toBeTruthy();
    });
    expect(screen.getByRole("button", { name: "Оплатить" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.queryByTestId("payment-dialog")).toBeNull();
  });

  it("shows gateway unavailable message when sbp disabled", async () => {
    await submitOrder({
      id: 44,
      payment_allowed: true,
      payment_gateway_enabled: false,
      total_amount: "100.00",
      availability_confirmation_status: "not_required",
    });

    await waitFor(() => {
      expect(screen.getByText("Оплата временно недоступна")).toBeTruthy();
    });
    expect(screen.queryByTestId("payment-dialog")).toBeNull();
  });

  it("blocks checkout without telegram and shows widget", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { identities: [{ provider: "phone" }] },
      refresh: vi.fn().mockResolvedValue(undefined),
    } as never);
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      return null;
    });

    renderCheckout();
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
    await userEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(screen.getByRole("button", { name: "Подключить Telegram" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Оформить заказ — недоступно" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("refreshes auth when returning to checkout without telegram", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useAuth).mockReturnValue({
      user: { identities: [{ provider: "phone" }] },
      refresh,
    } as never);
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      return null;
    });

    renderCheckout();
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
    refresh.mockClear();
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    refresh.mockClear();
    act(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("unblocks checkout after telegram refresh", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useAuth)
      .mockReturnValueOnce({
        user: { identities: [{ provider: "phone" }] },
        refresh,
      } as never)
      .mockReturnValue({
        user: {
          telegram_id: 42,
          telegram_username: "buyer",
          identities: [{ provider: "telegram", telegram_username: "buyer" }],
        },
        refresh,
      } as never);
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      return null;
    });

    const { rerender } = renderCheckout();
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <CheckoutContent />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
    expect(
      screen.getByRole("button", { name: "Оформить заказ — недоступно" }),
    ).toHaveProperty("disabled", true);
  });

  it("does not preview promo while typing until Apply is clicked", async () => {
    let previewCalls = 0;
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") {
        previewCalls += 1;
        const body = JSON.parse(String(init?.body ?? "{}")) as { promo_code?: string | null };
        return {
          ...previewResponse,
          promo_code_applied: body.promo_code ? "SAVE10" : null,
        };
      }
      return null;
    });

    renderCheckout();
    await waitFor(() => expect(previewCalls).toBe(1));

    const input = screen.getByPlaceholderText("Введите промокод");
    await userEvent.type(input, "SAVE10");
    expect(previewCalls).toBe(1);

    await userEvent.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() => expect(previewCalls).toBe(2));
    expect(screen.getByText(/SAVE10/)).toBeTruthy();
  });

  it("shows telegram block again on structured 409", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: {
        telegram_id: 1,
        identities: [{ provider: "telegram" }],
      },
      refresh: vi.fn().mockResolvedValue(undefined),
    } as never);
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      if (url === "/orders/checkout" && init?.method === "POST") {
        throw new StorefrontApiError("Привяжите Telegram", 409, {
          code: "telegram_required",
          message: "Привяжите Telegram",
        });
      }
      return null;
    });

    renderCheckout();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Оформить заказ — недоступно" }),
      ).toBeTruthy(),
    );
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]);
    await userEvent.click(checkboxes[2]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Оформить заказ" })).toBeTruthy(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Оформить заказ" }));
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
  });

  it("shows and verifies the email notification channel", async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      return null;
    });

    renderCheckout();
    await waitFor(() => expect(screen.getByText("Каналы уведомлений")).toBeTruthy());
    await userEvent.click(screen.getByText("Email"));

    const email = screen.getByPlaceholderText("you@example.com");
    await userEvent.type(email, "buyer@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Получить код" }));
    expect(vi.mocked(sendLinkEmailCode)).toHaveBeenCalledWith("buyer@example.com");

    await userEvent.type(screen.getByLabelText("Введите код из письма"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Email подтверждён")).toBeTruthy(),
    );
    expect(vi.mocked(verifyLinkEmail)).toHaveBeenCalledWith("buyer@example.com", "123456");
  });

  it("allows both selected notification channels after both identities are ready", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: {
        telegram_id: 123,
        identities: [
          { provider: "telegram", telegram_username: "linked_user" },
          { provider: "email", email: "buyer@example.com" },
        ],
      },
      refresh: vi.fn().mockResolvedValue(undefined),
    } as never);
    mockFetch.mockImplementation(async (url: string) => {
      if (url === "/cart/me") return cartResponse;
      if (url === "/storefront/social") return { bot_username: "test_bot" };
      if (url === "/orders/checkout/preview") return previewResponse;
      return null;
    });

    renderCheckout();
    await userEvent.click(screen.getByText("Telegram"));
    await userEvent.click(screen.getByText("Email"));
    await waitFor(() =>
      expect(screen.getByLabelText("Email подтверждён")).toBeTruthy(),
    );
    expect(screen.getAllByRole("checkbox").filter((item) => (item as HTMLInputElement).checked)).toHaveLength(2);
  });
});
