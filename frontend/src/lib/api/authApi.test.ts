import { afterEach, describe, expect, it, vi } from "vitest";

import { loginWithTelegramMiniApp } from "./authApi";

vi.mock("../storefront/api", () => ({
  storefrontApiFetch: vi.fn(),
}));

import { storefrontApiFetch } from "../storefront/api";

const mockStorefrontApiFetch = vi.mocked(storefrontApiFetch);

describe("authApi", () => {
  afterEach(() => {
    mockStorefrontApiFetch.mockReset();
    localStorage.clear();
  });

  it("stores access token after miniapp unified login", async () => {
    mockStorefrontApiFetch.mockResolvedValue({ access_token: "jwt-test" });

    const result = await loginWithTelegramMiniApp("init-data");

    expect(mockStorefrontApiFetch).toHaveBeenCalledWith(
      "/auth/telegram/unified-login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ source: "miniapp", init_data: "init-data" }),
      }),
    );
    expect(result.access_token).toBe("jwt-test");
    expect(localStorage.getItem("access_token")).toBe("jwt-test");
  });
});
