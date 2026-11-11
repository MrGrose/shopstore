import { isTelegramMiniAppRoute } from "./miniApp";

type TelegramWebApp = {
  initData: string;
  ready: () => void;
  expand?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  openLink?: (url: string) => void;
  requestContact?: (callback: (shared: boolean) => void) => void;
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  MainButton?: {
    text: string;
    show: () => void;
    hide: () => void;
    enable: () => void;
    disable: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

const MINI_APP_CHROME_BG = "#F5F5F7";
const TELEGRAM_INIT_PARAMS_KEY = "__telegram__initParams";

let scriptPromise: Promise<void> | null = null;

function urlSafeDecode(urlencoded: string): string {
  try {
    return decodeURIComponent(urlencoded.replace(/\+/g, "%20"));
  } catch {
    return urlencoded;
  }
}

/** Разбирает Telegram launch hash (`tgWebAppData=...&tgWebAppVersion=...`). */
function parseTelegramHashParams(locationHash: string): Record<string, string> {
  const hash = locationHash.replace(/^#/, "");
  if (!hash || (!hash.includes("=") && !hash.includes("?"))) return {};
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : hash;
  const params: Record<string, string> = {};
  for (const part of query.split("&")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    params[urlSafeDecode(part.slice(0, eq))] = urlSafeDecode(part.slice(eq + 1));
  }
  return params;
}

function readPersistedTelegramInitData(): string {
  try {
    const raw = window.sessionStorage.getItem(TELEGRAM_INIT_PARAMS_KEY);
    if (!raw) return "";
    const stored = JSON.parse(raw) as { tgWebAppData?: unknown };
    return String(stored.tgWebAppData ?? "").trim();
  } catch {
    return "";
  }
}

/**
 * Telegram SDK читает location.hash только в момент своего выполнения.
 * React Router (`Navigate`, setSearchParams → navigate("?...")) стирает hash.
 * Пишем launch params в тот же sessionStorage, что читает telegram-web-app.js.
 */
export function persistTelegramLaunchParams(): void {
  if (typeof window === "undefined") return;
  let hash = "";
  try {
    hash = window.location.hash.toString();
  } catch {
    return;
  }
  if (!hash.includes("tgWebAppData")) return;
  const params = parseTelegramHashParams(hash);
  if (!params.tgWebAppData) return;
  try {
    const prevRaw = window.sessionStorage.getItem(TELEGRAM_INIT_PARAMS_KEY);
    const prev = prevRaw ? (JSON.parse(prevRaw) as Record<string, string>) : {};
    window.sessionStorage.setItem(
      TELEGRAM_INIT_PARAMS_KEY,
      JSON.stringify({ ...prev, ...params }),
    );
  } catch {
    // private mode / disabled storage
  }
}

persistTelegramLaunchParams();

/** Подгружает telegram-web-app.js один раз. */
export function loadTelegramWebAppScript(): Promise<void> {
  persistTelegramLaunchParams();
  if (!isTelegramMiniAppRoute()) return Promise.resolve();
  // Только live initData: пустой stub WebApp не должен блокировать загрузку SDK.
  if (String(window.Telegram?.WebApp?.initData ?? "").trim()) return Promise.resolve();
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[src="https://telegram.org/js/telegram-web-app.js"]',
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("Telegram SDK")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-web-app.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Не удалось загрузить Telegram SDK"));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

/** BackButton доступен с Telegram WebApp 6.1+. */
export function telegramBackButtonSupported(): boolean {
  const tg = window.Telegram?.WebApp;
  if (!tg?.BackButton) return false;
  const isVersionAtLeast = (
    tg as TelegramWebApp & { isVersionAtLeast?: (v: string) => boolean }
  ).isVersionAtLeast;
  if (typeof isVersionAtLeast === "function") {
    return isVersionAtLeast("6.1");
  }
  const version = Number.parseFloat(String(tg.version ?? "0"));
  return Number.isFinite(version) && version >= 6.1;
}

/** Настраивает Telegram WebApp chrome под SHOPSTORE light theme. */
export function initTelegramWebAppChrome(): void {
  const tg = window.Telegram?.WebApp;
  if (!tg) return;
  tg.ready();
  tg.expand?.();
  tg.setHeaderColor?.(MINI_APP_CHROME_BG);
  tg.setBackgroundColor?.(MINI_APP_CHROME_BG);
}

export type TelegramWebAppDiagnostics = {
  hasTelegram: boolean;
  hasWebApp: boolean;
  platform: string;
  initDataLen: number;
  version: string;
  insideWebApp: boolean;
};

/** Снимок состояния Telegram WebApp SDK (для диагностики Mini App). */
export function getTelegramWebAppDiagnostics(): TelegramWebAppDiagnostics {
  const hasTelegram = Boolean(window.Telegram);
  const tg = window.Telegram?.WebApp;
  const platform = String(tg?.platform ?? "").trim();
  return {
    hasTelegram,
    hasWebApp: Boolean(tg),
    platform: platform || "—",
    initDataLen: readTelegramInitData().length,
    version: String(tg?.version ?? "").trim() || "—",
    insideWebApp: isInsideTelegramWebApp(),
  };
}

/** initData для unified-login (пустая строка вне Telegram). */
export function readTelegramInitData(): string {
  const live = String(window.Telegram?.WebApp?.initData ?? "").trim();
  if (live) return live;
  return readPersistedTelegramInitData();
}

/** Ждёт initData после открытия WebView (иногда bridge отдаёт его с задержкой). */
export async function waitForTelegramInitData(maxMs = 8000): Promise<string> {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    const initData = readTelegramInitData();
    if (initData) return initData;
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  return "";
}

/** true, если страница открыта внутри Telegram WebView (не обычный браузер). */
export function isInsideTelegramWebApp(): boolean {
  const platform = String(window.Telegram?.WebApp?.platform ?? "").trim();
  return platform.length > 0 && platform !== "unknown";
}

// Просит Telegram отправить боту контакт текущего пользователя.
export function requestTelegramContact(): Promise<boolean> {
  return new Promise((resolve) => {
    const requestContact = window.Telegram?.WebApp?.requestContact;
    if (!requestContact) {
      resolve(false);
      return;
    }
    requestContact((shared) => resolve(Boolean(shared)));
  });
}
