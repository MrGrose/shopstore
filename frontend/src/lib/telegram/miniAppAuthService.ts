import { loginWithTelegramMiniApp, reportMiniAppAuthProbe } from "../api/authApi";
import { StorefrontApiError } from "../storefront/api";
import { LOGIN_UNAVAILABLE_CODE, isLoginUnavailableError } from "../storefront/authErrors";
import { mapApiErrorToUserMessage } from "../errorMessages";
import {
  getTelegramWebAppDiagnostics,
  initTelegramWebAppChrome,
  isInsideTelegramWebApp,
  loadTelegramWebAppScript,
  type TelegramWebAppDiagnostics,
  waitForTelegramInitData,
} from "../storefront/telegramWebApp";

export type MiniAppAuthPhase = "mount" | "retry" | "visible";

export type MiniAppAuthAttemptSuccess = {
  status: "success";
  debug: string;
};

export type MiniAppAuthAttemptFailure = {
  status: "login_unavailable" | "error";
  debug: string | null;
  userMessage: string | null;
  probeMessage: string;
};

export type MiniAppAuthAttemptResult = MiniAppAuthAttemptSuccess | MiniAppAuthAttemptFailure;

const SDK_RETRY_DELAY_MS = 400;

// В Mini App всегда обновляем сессию по initData (старый JWT в WebView часто блокирует вход).
export async function bootstrapTelegramMiniAppAuth(): Promise<void> {
  localStorage.removeItem("access_token");
  await loadTelegramWebAppScript();
  initTelegramWebAppChrome();
  const initData = await waitForTelegramInitData();
  if (!initData) {
    throw new Error("initData empty");
  }
  await loginWithTelegramMiniApp(initData);
}

// Одна повторная попытка при сбое загрузки Telegram SDK.
async function bootstrapTelegramMiniAppAuthWithRetry(): Promise<void> {
  try {
    await bootstrapTelegramMiniAppAuth();
  } catch (error) {
    const retryable =
      error instanceof Error &&
      (error.message.includes("Telegram SDK") || error.message.includes("загрузить Telegram SDK"));
    if (!retryable) throw error;
    await new Promise((resolve) => window.setTimeout(resolve, SDK_RETRY_DELAY_MS));
    await bootstrapTelegramMiniAppAuth();
  }
}

export function formatMiniAppAuthDebug(diagnostics: TelegramWebAppDiagnostics): string {
  return `SDK: tg=${diagnostics.hasTelegram ? "да" : "нет"}, webapp=${diagnostics.hasWebApp ? "да" : "нет"}, platform=${diagnostics.platform}, initData=${diagnostics.initDataLen}`;
}

export function resolveMiniAppAuthErrorMessage(
  error: unknown,
  diagnostics: TelegramWebAppDiagnostics,
): string {
  if (error instanceof Error && error.message === "initData empty") {
    if (!diagnostics.hasWebApp) {
      return "Telegram SDK не загрузился. Проверьте интернет и откройте магазин снова из бота.";
    }
    if (!isInsideTelegramWebApp()) {
      return "Откройте магазин кнопкой «Открыть магазин» в боте, не через браузер.";
    }
    return "Telegram не передал данные входа. Закройте Mini App и откройте снова из бота.";
  }
  if (error instanceof Error && error.message.includes("Telegram SDK")) {
    return "Не удалось загрузить Telegram SDK. Откройте магазин снова из бота.";
  }
  if (error instanceof StorefrontApiError) {
    return mapApiErrorToUserMessage(error, {
      fallback: "Сервер отклонил вход через Telegram.",
    });
  }
  return "Не удалось войти через Telegram.";
}

// Загружает SDK, логинит через initData и шлёт probe; без React Query.
export async function attemptMiniAppLogin(
  phase: MiniAppAuthPhase,
): Promise<MiniAppAuthAttemptResult> {
  const diagnostics = getTelegramWebAppDiagnostics();
  const debug = formatMiniAppAuthDebug(diagnostics);
  try {
    await bootstrapTelegramMiniAppAuthWithRetry();
    return { status: "success", debug };
  } catch (error) {
    if (isLoginUnavailableError(error)) {
      void reportMiniAppAuthProbe(phase, getTelegramWebAppDiagnostics(), LOGIN_UNAVAILABLE_CODE);
      return {
        status: "login_unavailable",
        debug: null,
        userMessage: null,
        probeMessage: LOGIN_UNAVAILABLE_CODE,
      };
    }
    const failDiagnostics = getTelegramWebAppDiagnostics();
    const failDebug = formatMiniAppAuthDebug(failDiagnostics);
    const probeMessage = error instanceof Error ? error.message : "unknown";
    void reportMiniAppAuthProbe(phase, failDiagnostics, probeMessage);
    return {
      status: "error",
      debug: failDebug,
      userMessage: resolveMiniAppAuthErrorMessage(error, failDiagnostics),
      probeMessage,
    };
  }
}
