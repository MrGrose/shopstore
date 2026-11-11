import { afterEach, describe, expect, it, vi } from "vitest";

import type { TelegramWebAppDiagnostics } from "../storefront/telegramWebApp";

const baseDiagnostics: TelegramWebAppDiagnostics = {
  hasTelegram: true,
  hasWebApp: true,
  platform: "ios",
  initDataLen: 0,
  version: "7.0",
  insideWebApp: true,
};

vi.mock("../api/authApi", () => ({
  loginWithTelegramMiniApp: vi.fn(),
  reportMiniAppAuthProbe: vi.fn(),
}));

vi.mock("../storefront/telegramWebApp", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../storefront/telegramWebApp")>();
  return {
    ...actual,
    loadTelegramWebAppScript: vi.fn().mockResolvedValue(undefined),
    initTelegramWebAppChrome: vi.fn(),
    waitForTelegramInitData: vi.fn().mockResolvedValue("init"),
    getTelegramWebAppDiagnostics: vi.fn(() => baseDiagnostics),
  };
});

import { loginWithTelegramMiniApp } from "../api/authApi";
import {
  attemptMiniAppLogin,
  formatMiniAppAuthDebug,
  resolveMiniAppAuthErrorMessage,
} from "./miniAppAuthService";

const mockLoginWithTelegramMiniApp = vi.mocked(loginWithTelegramMiniApp);

describe("miniAppAuthService", () => {
  afterEach(() => {
    mockLoginWithTelegramMiniApp.mockReset();
    localStorage.clear();
  });

  it("formats diagnostics debug line", () => {
    expect(formatMiniAppAuthDebug(baseDiagnostics)).toContain("platform=ios");
    expect(formatMiniAppAuthDebug(baseDiagnostics)).toContain("initData=0");
  });

  it("maps empty initData without webapp to SDK message", () => {
    const message = resolveMiniAppAuthErrorMessage(new Error("initData empty"), {
      ...baseDiagnostics,
      hasWebApp: false,
    });
    expect(message).toContain("Telegram SDK не загрузился");
  });

  it("maps empty initData outside webview to bot button hint", () => {
    const message = resolveMiniAppAuthErrorMessage(new Error("initData empty"), {
      ...baseDiagnostics,
      insideWebApp: false,
    });
    expect(message).toContain("Откройте магазин");
  });

  it("returns success after bootstrap login", async () => {
    mockLoginWithTelegramMiniApp.mockResolvedValue({ access_token: "jwt" });

    const result = await attemptMiniAppLogin("mount");

    expect(result.status).toBe("success");
    if (result.status === "success") {
      expect(result.debug).toContain("platform=ios");
    }
  });
});
