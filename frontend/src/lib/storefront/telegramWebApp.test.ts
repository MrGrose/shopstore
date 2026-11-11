import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SDK_SRC = "https://telegram.org/js/telegram-web-app.js";
const INIT_PARAMS_KEY = "__telegram__initParams";
const LAUNCH_HASH =
  "#tgWebAppData=query_id%3De2e%26user%3D%7B%22id%22%3A1%7D%26auth_date%3D1%26hash%3Dabc&tgWebAppVersion=7.0&tgWebAppPlatform=ios";

async function loadAdapter() {
  return import("./telegramWebApp");
}

describe("telegramWebApp adapter", () => {
  beforeEach(() => {
    vi.resetModules();
    document.querySelectorAll(`script[src="${SDK_SRC}"]`).forEach((node) => node.remove());
    delete window.Telegram;
    window.sessionStorage.removeItem(INIT_PARAMS_KEY);
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    document.querySelectorAll(`script[src="${SDK_SRC}"]`).forEach((node) => node.remove());
    delete window.Telegram;
    window.sessionStorage.removeItem(INIT_PARAMS_KEY);
  });

  it("does not inject the SDK on web routes", async () => {
    const { loadTelegramWebAppScript } = await loadAdapter();
    await loadTelegramWebAppScript();
    expect(document.querySelector(`script[src="${SDK_SRC}"]`)).toBeNull();
  });

  it("injects async telegram-web-app.js on Mini App routes", async () => {
    window.history.pushState({}, "", "/app/catalog");
    const { loadTelegramWebAppScript } = await loadAdapter();
    const pending = loadTelegramWebAppScript();
    const script = document.querySelector<HTMLScriptElement>(`script[src="${SDK_SRC}"]`);
    expect(script).not.toBeNull();
    expect(script?.async).toBe(true);
    script?.dispatchEvent(new Event("load"));
    await pending;
  });

  it("keeps tgWebAppData after React Router clears location.hash", async () => {
    window.history.pushState({}, "", `/app/catalog${LAUNCH_HASH}`);
    const { persistTelegramLaunchParams, readTelegramInitData } = await loadAdapter();
    persistTelegramLaunchParams();
    window.history.replaceState({}, "", "/app/catalog");
    delete window.Telegram;

    expect(window.location.hash).toBe("");
    expect(readTelegramInitData()).toContain("query_id=e2e");
    const stored = JSON.parse(window.sessionStorage.getItem(INIT_PARAMS_KEY) ?? "{}") as {
      tgWebAppData?: string;
    };
    expect(stored.tgWebAppData).toContain("query_id=e2e");
  });

  it("does not write empty initParams on web routes without launch hash", async () => {
    window.history.pushState({}, "", "/catalog/padel");
    const { persistTelegramLaunchParams } = await loadAdapter();
    persistTelegramLaunchParams();
    expect(window.sessionStorage.getItem(INIT_PARAMS_KEY)).toBeNull();
  });

  it("waitForTelegramInitData returns persisted data without WebApp", async () => {
    window.history.pushState({}, "", `/app/catalog${LAUNCH_HASH}`);
    const { persistTelegramLaunchParams, waitForTelegramInitData } = await loadAdapter();
    persistTelegramLaunchParams();
    window.history.replaceState({}, "", "/app/catalog");
    delete window.Telegram;

    await expect(waitForTelegramInitData(200)).resolves.toContain("query_id=e2e");
  });
});
