import { useEffect, useRef, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { useAuth } from "./AuthContext";
import { MiniAppAccessDenied } from "../components/auth/MiniAppAccessDenied";
import { isLoginUnavailableError } from "../../lib/storefront/authErrors";
import { isTelegramMiniAppRoute } from "../../lib/storefront/miniApp";

type Props = {
  children: ReactNode;
};

export function RequireAuth({ children }: Props) {
  const {
    isAuthenticated,
    loading,
    bootstrapping,
    miniAppAuthError,
    miniAppAuthDebug,
    loginUnavailable,
    retryMiniAppLogin,
  } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const miniApp = isTelegramMiniAppRoute();
  const retriedRef = useRef(false);

  useEffect(() => {
    if (loading || bootstrapping || isAuthenticated || miniApp) return;
    const next = `${location.pathname}${location.search}`;
    navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
  }, [loading, bootstrapping, isAuthenticated, miniApp, location.pathname, location.search, navigate]);

  // Повтор входа, если при старте initData ещё не был готов.
  useEffect(() => {
    if (!miniApp || isAuthenticated || loading || bootstrapping || retriedRef.current) {
      return;
    }
    retriedRef.current = true;
    void retryMiniAppLogin();
  }, [miniApp, isAuthenticated, loading, bootstrapping, retryMiniAppLogin]);

  if (loading || bootstrapping) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-sp-text-secondary">
        Загрузка…
      </div>
    );
  }

  if (!isAuthenticated) {
    if (miniApp) {
      if (loginUnavailable || isLoginUnavailableError({ message: miniAppAuthError ?? "" })) {
        return <MiniAppAccessDenied />;
      }
      return (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 px-6 text-center text-sp-text-secondary">
          <p className="m-0">{miniAppAuthError ?? "Не удалось войти через Telegram."}</p>
          {miniAppAuthDebug ? (
            <p className="m-0 text-xs text-sp-text-muted">{miniAppAuthDebug}</p>
          ) : null}
          <button
            type="button"
            className="rounded-full border border-sp-border px-4 py-2 text-sm text-sp-text-primary"
            onClick={() => {
              retriedRef.current = false;
              void retryMiniAppLogin();
            }}
          >
            Повторить вход
          </button>
        </div>
      );
    }
    return null;
  }

  return children;
}
