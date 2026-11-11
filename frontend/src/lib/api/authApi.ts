import { storefrontApiFetch } from "../storefront/api";
import { clearAuthSession } from "../storefront/session";
import type { TelegramWebAppDiagnostics } from "../storefront/telegramWebApp";

export type MiniAppAuthProbePhase = "mount" | "fail" | "retry" | "visible";

export type TelegramWidgetUser = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
};

// Отправляет диагностику Mini App auth в логи API (без initData).
export async function reportMiniAppAuthProbe(
  phase: MiniAppAuthProbePhase,
  diagnostics: TelegramWebAppDiagnostics,
  errorMessage?: string,
): Promise<void> {
  try {
    await fetch("/auth/telegram/miniapp-probe", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        phase,
        platform: diagnostics.platform,
        init_data_len: diagnostics.initDataLen,
        has_telegram: diagnostics.hasTelegram,
        has_webapp: diagnostics.hasWebApp,
        version: diagnostics.version,
        inside_webapp: diagnostics.insideWebApp,
        error_message: errorMessage ?? null,
      }),
    });
  } catch {
    // ignore
  }
}

// Авторизация Mini App через Telegram.WebApp.initData.
export async function loginWithTelegramMiniApp(
  initData: string,
): Promise<{ access_token: string }> {
  const data = await storefrontApiFetch<{ access_token: string }>(
    "/auth/telegram/unified-login",
    {
      method: "POST",
      body: JSON.stringify({
        source: "miniapp",
        init_data: initData,
      }),
    },
  );
  if (data?.access_token) {
    localStorage.setItem("access_token", data.access_token);
  }
  return data as { access_token: string };
}

// Авторизация web через Telegram Login Widget.
export async function loginWithTelegramWidget(
  user: TelegramWidgetUser,
): Promise<{ access_token: string }> {
  const data = await storefrontApiFetch<{ access_token: string }>(
    "/auth/telegram/unified-login",
    {
      method: "POST",
      body: JSON.stringify({
        source: "widget",
        id: user.id,
        first_name: user.first_name,
        last_name: user.last_name,
        username: user.username,
        photo_url: user.photo_url,
        auth_date: user.auth_date,
        hash: user.hash,
      }),
    },
  );
  if (data?.access_token) {
    localStorage.setItem("access_token", data.access_token);
  }
  return data as { access_token: string };
}

// Завершает сессию на клиенте и на API.
export async function logout(): Promise<void> {
  await clearAuthSession();
}
