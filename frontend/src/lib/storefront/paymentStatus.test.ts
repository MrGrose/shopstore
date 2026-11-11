import { describe, expect, it } from "vitest";
import {
  formatCountdown,
  isPaymentFinalErrorState,
  isPaymentSuccessState,
  isPaymentWaitingState,
  qrCountdownMs,
} from "./paymentStatus";

describe("paymentStatus helpers", () => {
  it("detects success state", () => {
    expect(isPaymentSuccessState("paid", false)).toBe(true);
    expect(isPaymentSuccessState("waiting", true)).toBe(true);
    expect(isPaymentSuccessState("waiting", false)).toBe(false);
  });

  it("detects waiting states", () => {
    expect(isPaymentWaitingState("waiting")).toBe(true);
    expect(isPaymentWaitingState("initializing")).toBe(true);
    expect(isPaymentWaitingState("failed")).toBe(false);
  });

  it("detects final error state", () => {
    expect(isPaymentFinalErrorState("failed")).toBe(true);
    expect(isPaymentFinalErrorState("exhausted")).toBe(true);
    expect(isPaymentFinalErrorState("waiting")).toBe(false);
  });

  it("formats countdown", () => {
    expect(formatCountdown(125_000)).toBe("2:05");
    expect(formatCountdown(0)).toBe("0:00");
  });

  it("computes qr countdown ms", () => {
    const now = Date.parse("2030-01-01T00:00:00Z");
    const remaining = qrCountdownMs("2030-01-01T00:10:00Z", now);
    expect(remaining).toBe(10 * 60 * 1000);
  });

  it("treats naive UTC qr_expires_at as UTC", () => {
    const now = Date.parse("2030-01-01T00:00:00Z");
    const remaining = qrCountdownMs("2030-01-01T00:10:00", now);
    expect(remaining).toBe(10 * 60 * 1000);
  });
});
