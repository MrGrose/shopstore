import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PaymentDialog } from "./PaymentDialog";
import {
  PAYMENT_NETWORK_RETRY_DELAYS_MS,
  PAYMENT_POLL_INTERVAL_MS,
} from "../../lib/storefront/paymentStatus";

vi.mock("../../lib/storefront/api", () => ({
  storefrontApiFetch: vi.fn(),
}));

vi.mock("../../lib/storefront/useStorefrontSurface", () => ({
  useStorefrontCompact: () => false,
  useStorefrontBottomNav: () => false,
}));

vi.mock("qrcode", () => ({
  default: {
    toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,mockqr"),
  },
}));

import { storefrontApiFetch } from "../../lib/storefront/api";
import QRCode from "qrcode";

const mockFetch = vi.mocked(storefrontApiFetch);
const mockQr = vi.mocked(QRCode.toDataURL);

const initResponse = {
  order_id: 42,
  provider: "sbp",
  payment_attempt_id: 7,
  payment_state: "waiting",
  payment_qr_payload: "https://qr.test/pay",
  qr_expires_at: "2030-01-01T00:15:00Z",
  is_paid: false,
  is_test_mode: true,
};

const waitingStatus = {
  order_id: 42,
  status: "processing",
  payment_attempt_id: 7,
  payment_state: "waiting",
  is_paid: false,
  qr_expires_at: "2030-01-01T00:15:00Z",
};

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("PaymentDialog", () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockFetch.mockReset();
    mockQr.mockClear();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("calls init and renders QR on open", async () => {
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValue(waitingStatus);

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await flushPromises();

    expect(mockFetch).toHaveBeenCalledWith("/orders/42/payment/init", {
      method: "POST",
    });
    expect(screen.getByAltText("QR-код для оплаты СБП")).toBeTruthy();
    expect(mockQr).toHaveBeenCalledWith(
      "https://qr.test/pay",
      expect.objectContaining({ width: 260 }),
    );
  });

  it("polls payment status with attempt id while waiting", async () => {
    vi.useFakeTimers();
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValue(waitingStatus);

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAYMENT_POLL_INTERVAL_MS);
      await Promise.resolve();
    });

    expect(
      mockFetch.mock.calls.some(
        (call) => call[0] === "/orders/42/payment/status?payment_attempt_id=7",
      ),
    ).toBe(true);
  });

  it("shows success when payment_state is paid", async () => {
    const onPaid = vi.fn();
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValueOnce({
      ...waitingStatus,
      payment_state: "paid",
      is_paid: true,
    });

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
        onPaid={onPaid}
      />,
    );

    await flushPromises();

    expect(screen.getByText("Оплата подтверждена")).toBeTruthy();
    expect(onPaid).toHaveBeenCalledTimes(1);
  });

  it("shows error on failed payment_state", async () => {
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValueOnce({
      ...waitingStatus,
      payment_state: "failed",
      is_paid: false,
    });

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await flushPromises();

    expect(screen.getByText(/Оплата не прошла\. Попробуйте снова/)).toBeTruthy();
  });

  it("shows countdown for qr_expires_at", async () => {
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValue(waitingStatus);

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await flushPromises();

    expect(screen.getByText(/QR действует:/)).toBeTruthy();
  });

  it("hides QR and checks status when countdown expires", async () => {
    vi.useFakeTimers({ now: new Date("2030-01-01T00:14:50Z") });
    mockFetch.mockResolvedValueOnce({
      ...initResponse,
      qr_expires_at: "2030-01-01T00:15:00Z",
    });
    mockFetch.mockResolvedValue({
      ...waitingStatus,
      payment_state: "failed",
      qr_expires_at: "2030-01-01T00:15:00Z",
    });

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(12_000);
      await Promise.resolve();
    });

    expect(screen.queryByAltText("QR-код для оплаты СБП")).toBeNull();
  });

  it("stops polling on close", async () => {
    vi.useFakeTimers();
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch.mockResolvedValue(waitingStatus);

    const { rerender } = render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const callsAfterInit = mockFetch.mock.calls.length;

    rerender(
      <PaymentDialog
        open={false}
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAYMENT_POLL_INTERVAL_MS * 3);
      await Promise.resolve();
    });

    expect(mockFetch.mock.calls.length).toBe(callsAfterInit);
  });

  it("retries network errors during polling", async () => {
    vi.useFakeTimers();
    mockFetch.mockResolvedValueOnce(initResponse);
    mockFetch
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce(waitingStatus);

    render(
      <PaymentDialog
        open
        orderId={42}
        totalAmount="100.00"
        onClose={() => undefined}
      />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAYMENT_POLL_INTERVAL_MS);
      await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAYMENT_NETWORK_RETRY_DELAYS_MS[0]);
      await Promise.resolve();
    });

    expect(
      mockFetch.mock.calls.filter(
        (call) => call[0] === "/orders/42/payment/status?payment_attempt_id=7",
      ).length,
    ).toBeGreaterThan(0);
  });
});
