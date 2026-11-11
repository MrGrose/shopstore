import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getRequestMetricsSnapshot,
  installRequestMetrics,
  recordRequest,
  resetRequestMetrics,
} from "./requestMetrics";

describe("requestMetrics", () => {
  beforeEach(() => {
    resetRequestMetrics();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-06T10:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    resetRequestMetrics();
    delete window.__metrics;
  });

  it("counts requests", () => {
    recordRequest("GET", "/products");
    recordRequest("POST", "/cart/me/items");

    expect(getRequestMetricsSnapshot().requestCount).toBe(2);
  });

  it("detects duplicate requests within one second", () => {
    recordRequest("GET", "/products/facets?top_category=Padel");
    recordRequest("GET", "/products/facets?top_category=Padel");

    const snapshot = getRequestMetricsSnapshot();
    expect(snapshot.duplicateCount).toBe(1);
    expect(snapshot.duplicates).toHaveLength(1);
    expect(snapshot.duplicates[0]?.url).toBe(
      "/products/facets?top_category=Padel",
    );
  });

  it("does not count duplicates after one second", () => {
    recordRequest("GET", "/cart/me");
    vi.advanceTimersByTime(1001);
    recordRequest("GET", "/cart/me");

    expect(getRequestMetricsSnapshot().duplicateCount).toBe(0);
  });

  it("installs window.__metrics and wraps fetch", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("ok"));
    window.fetch = fetchMock;
    installRequestMetrics();

    await window.fetch("/catalog/taxonomy");
    await window.fetch("/catalog/taxonomy");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(window.__metrics?.requests().requestCount).toBe(2);
    expect(window.__metrics?.requests().duplicateCount).toBe(1);
  });
});
