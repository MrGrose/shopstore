import { useCallback, useEffect, useState } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { reportMiniAppAuthProbe } from "../lib/api/authApi";
import { isTelegramMiniAppRoute } from "../lib/storefront/miniApp";
import { type StorefrontUser } from "../lib/storefront/session";
import { getTelegramWebAppDiagnostics } from "../lib/storefront/telegramWebApp";
import {
  attemptMiniAppLogin,
  formatMiniAppAuthDebug,
  type MiniAppAuthPhase,
} from "../lib/telegram/miniAppAuthService";
import { invalidateUserQuery, syncUserQueryCache, userQueryKey } from "./useUser";

export function useMiniAppAuthState(queryClient: QueryClient, user: StorefrontUser | null) {
  const [bootstrapping, setBootstrapping] = useState(isTelegramMiniAppRoute());
  const [miniAppAuthError, setMiniAppAuthError] = useState<string | null>(null);
  const [miniAppAuthDebug, setMiniAppAuthDebug] = useState<string | null>(null);
  const [loginUnavailable, setLoginUnavailable] = useState(false);

  const runMiniAppLogin = useCallback(
    async (phase: MiniAppAuthPhase) => {
      if (!isTelegramMiniAppRoute()) return;
      setBootstrapping(true);
      setMiniAppAuthError(null);
      setLoginUnavailable(false);
      const result = await attemptMiniAppLogin(phase);
      if (result.status === "success") {
        setMiniAppAuthDebug(result.debug);
        setLoginUnavailable(false);
        await invalidateUserQuery(queryClient);
        const me = queryClient.getQueryData<StorefrontUser | null>(userQueryKey);
        if (!me) {
          setMiniAppAuthError("Сессия не установилась после входа.");
          void reportMiniAppAuthProbe(phase, getTelegramWebAppDiagnostics(), "session empty");
        }
      } else if (result.status === "login_unavailable") {
        localStorage.removeItem("access_token");
        syncUserQueryCache(queryClient, null);
        setLoginUnavailable(true);
        setMiniAppAuthError(null);
        setMiniAppAuthDebug(null);
      } else {
        localStorage.removeItem("access_token");
        syncUserQueryCache(queryClient, null);
        setMiniAppAuthDebug(result.debug);
        setMiniAppAuthError(result.userMessage);
      }
      setBootstrapping(false);
    },
    [queryClient],
  );

  const retryMiniAppLogin = useCallback(async () => {
    await runMiniAppLogin("retry");
  }, [runMiniAppLogin]);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      try {
        if (isTelegramMiniAppRoute()) {
          const diagnostics = getTelegramWebAppDiagnostics();
          setMiniAppAuthDebug(formatMiniAppAuthDebug(diagnostics));
          void reportMiniAppAuthProbe("mount", diagnostics);
          await runMiniAppLogin("mount");
        }
      } catch {
        if (!cancelled) syncUserQueryCache(queryClient, null);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [queryClient, runMiniAppLogin]);

  useEffect(() => {
    if (!isTelegramMiniAppRoute()) return;
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (user) return;
      if (loginUnavailable) return;
      void runMiniAppLogin("visible");
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [runMiniAppLogin, user, loginUnavailable]);

  return {
    bootstrapping,
    miniAppAuthError,
    miniAppAuthDebug,
    loginUnavailable,
    retryMiniAppLogin,
    clearMiniAppAuthError: () => setMiniAppAuthError(null),
  };
}
