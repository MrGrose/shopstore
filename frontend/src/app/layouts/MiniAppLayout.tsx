import { lazy, Suspense, useEffect } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { captureReferralFromSearch } from "../../lib/storefront/referral";
import { applyPendingReferrerFromCookie } from "../../lib/storefront/referrer";
import { pathToLegalSlug } from "../../lib/storefront/legal";
import { hasAuthToken } from "../../lib/storefront/session";
import type { StorefrontOutletContext } from "../../lib/storefront/miniApp";
import {
  initTelegramWebAppChrome,
  loadTelegramWebAppScript,
  telegramBackButtonSupported,
} from "../../lib/storefront/telegramWebApp";
import { scheduleMiniAppCatalogPrefetch } from "../../lib/storefront/prefetchCatalogSubcategories";
import { MiniAppBottomNav } from "../components/MiniAppBottomNav";
import { PageRouteFallback } from "../components/PageRouteFallback";
import { useAuth } from "../auth/AuthContext";
import { MiniAppAccessDenied } from "../components/auth/MiniAppAccessDenied";

const SupportPage = lazy(() =>
  import("../pages/SupportPage").then((module) => ({ default: module.SupportPage })),
);

export function MiniAppLayout() {
  const { loginUnavailable } = useAuth();
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const outletContext: StorefrontOutletContext = { surface: "miniapp" };

  useEffect(() => {
    scheduleMiniAppCatalogPrefetch();
  }, []);

  useEffect(() => {
    let cancelled = false;
    // SDK больше не в index.html — грузим только на Mini App.
    void loadTelegramWebAppScript()
      .then(() => {
        if (!cancelled) initTelegramWebAppChrome();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    captureReferralFromSearch(search);
    if (!hasAuthToken()) return;
    void applyPendingReferrerFromCookie()
      .then((status) => {
        if (status === "attributed") {
          window.dispatchEvent(new CustomEvent("telegram-auth-success"));
        }
      })
      .catch(() => {});
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    let detach: (() => void) | undefined;

    void loadTelegramWebAppScript()
      .then(() => {
        if (cancelled) return;
        const tg = window.Telegram?.WebApp;
        if (!tg?.BackButton || !telegramBackButtonSupported()) return;

        const showBack =
          pathname.includes("/product/") ||
          pathname.startsWith("/checkout") ||
          pathname.startsWith("/account") ||
          Boolean(pathToLegalSlug(pathname));

        if (!showBack) {
          tg.BackButton.hide();
          return;
        }

        tg.BackButton.show();
        const onBack = () => navigate(-1);
        tg.BackButton.onClick(onBack);
        detach = () => {
          tg.BackButton?.offClick(onBack);
          tg.BackButton?.hide();
        };
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      detach?.();
    };
  }, [pathname, navigate]);

  const isSupportPage = pathname === "/support" || pathname.endsWith("/support");

  if (loginUnavailable && isSupportPage) {
    return (
      <div
        className="flex h-dvh max-h-dvh flex-col overflow-y-auto bg-sp-bg text-sp-text-primary"
        style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
      >
        <Suspense fallback={<PageRouteFallback />}>
          <SupportPage />
        </Suspense>
      </div>
    );
  }

  if (loginUnavailable) {
    return <MiniAppAccessDenied />;
  }

  return (
    <div
      className="flex h-dvh max-h-dvh flex-col overflow-hidden bg-sp-bg text-sp-text-primary"
      style={{ ["--miniapp-bottom-nav-h" as string]: "4.25rem" }}
    >
      <main
        className="min-h-0 flex-1 overflow-x-clip overflow-y-auto pb-[calc(4.25rem+env(safe-area-inset-bottom,0px))]"
        style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
      >
        <Outlet context={outletContext} />
      </main>
      <MiniAppBottomNav />
    </div>
  );
}
