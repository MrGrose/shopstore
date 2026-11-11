import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRefreshOnPageActive } from "./useRefreshOnPageActive";

describe("useRefreshOnPageActive", () => {
  it("calls refresh when window receives focus", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnPageActive(refresh, true));

    window.dispatchEvent(new Event("focus"));

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not call refresh when disabled", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnPageActive(refresh, false));

    window.dispatchEvent(new Event("focus"));

    expect(refresh).not.toHaveBeenCalled();
  });
});
