import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";
import { captureReferralFromSearch } from "../../lib/storefront/referral";
import { applyPendingReferrerFromCookie } from "../../lib/storefront/referrer";
import type { StorefrontOutletContext } from "../../lib/storefront/miniApp";
import { hasAuthToken } from "../../lib/storefront/session";
import { useIsMobile } from "../components/ui/use-mobile";
import { Navbar } from "../components/Navbar";
import { Footer } from "../components/Footer";
import { MobileLegalFooter } from "../components/MobileLegalFooter";

export function StorefrontLayout() {
  const isMobile = useIsMobile();
  const { pathname, search } = useLocation();
  const isHomePage = pathname === "/";
  const outletContext: StorefrontOutletContext = { surface: "web" };

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

  if (isMobile) {
    const isCatalogHome = pathname === "/";
    return (
      <div className="flex h-dvh max-h-dvh flex-col overflow-hidden bg-sp-bg text-sp-text-primary">
        <Navbar />
        <main
          className={[
            "min-h-0 flex-1 overflow-x-clip",
            isCatalogHome ? "overflow-hidden" : "overflow-y-auto",
          ].join(" ")}
        >
          <Outlet context={outletContext} />
          <MobileLegalFooter />
        </main>
      </div>
    );
  }

  if (isHomePage) {
    return (
      <div className="relative h-dvh max-h-dvh overflow-hidden overflow-x-clip bg-sp-bg text-sp-text-primary">
        <Navbar />
        <div className="grid h-full grid-rows-[minmax(0,1fr)_auto]">
          <main className="min-h-0 overflow-hidden">
            <Outlet context={outletContext} />
          </main>
          <Footer />
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh flex-1 flex-col overflow-x-clip bg-sp-bg text-sp-text-primary">
      <Navbar />
      <main className="w-full min-w-0 shrink-0 grow-0 [scrollbar-gutter:stable]">
        <Outlet context={outletContext} />
      </main>
      <div className="mt-auto w-full shrink-0">
        <Footer />
      </div>
    </div>
  );
}
