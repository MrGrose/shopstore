import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { logout as apiLogout } from "../../lib/api/authApi";
import { useMiniAppAuthState } from "../../hooks/useMiniAppAuthState";
import { type StorefrontUser } from "../../lib/storefront/session";
import { invalidateUserQuery, syncUserQueryCache, useUser } from "../../hooks/useUser";

type AuthContextValue = {
  user: StorefrontUser | null;
  isAuthenticated: boolean;
  loading: boolean;
  bootstrapping: boolean;
  miniAppAuthError: string | null;
  miniAppAuthDebug: string | null;
  loginUnavailable: boolean;
  refresh: () => Promise<void>;
  retryMiniAppLogin: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { user: userData, isLoading } = useUser();
  const user = userData ?? null;
  const {
    bootstrapping,
    miniAppAuthError,
    miniAppAuthDebug,
    loginUnavailable,
    retryMiniAppLogin,
    clearMiniAppAuthError,
  } = useMiniAppAuthState(queryClient, user);

  const refresh = useCallback(async () => {
    await invalidateUserQuery(queryClient);
  }, [queryClient]);

  const logout = useCallback(async () => {
    await apiLogout();
    syncUserQueryCache(queryClient, null);
    clearMiniAppAuthError();
    window.dispatchEvent(new CustomEvent("telegram-auth-logout"));
  }, [queryClient, clearMiniAppAuthError]);

  useEffect(() => {
    const onSuccess = () => {
      void refresh();
    };
    window.addEventListener("telegram-auth-success", onSuccess);
    return () => window.removeEventListener("telegram-auth-success", onSuccess);
  }, [refresh]);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      loading: isLoading || bootstrapping,
      bootstrapping,
      miniAppAuthError,
      miniAppAuthDebug,
      loginUnavailable,
      refresh,
      retryMiniAppLogin,
      logout,
    }),
    [
      user,
      isLoading,
      bootstrapping,
      miniAppAuthError,
      miniAppAuthDebug,
      loginUnavailable,
      refresh,
      retryMiniAppLogin,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
