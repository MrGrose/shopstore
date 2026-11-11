/** Определяет, что UI открыт как Telegram Mini App (/app). */
export function isTelegramMiniAppRoute(): boolean {
  if (typeof window === "undefined") return false;
  return window.location.pathname === "/app" || window.location.pathname.startsWith("/app/");
}

/** Basename для React Router в Mini App. */
export function storefrontBasename(): string {
  return isTelegramMiniAppRoute() ? "/app" : "";
}

/** Контекст layout: web | miniapp. */
export type StorefrontSurface = "web" | "miniapp";

export type StorefrontOutletContext = {
  surface: StorefrontSurface;
};

export function currentStorefrontSurface(): StorefrontSurface {
  return isTelegramMiniAppRoute() ? "miniapp" : "web";
}

/** Высота нижней навигации Mini App (для sticky-баров). */
export const MINIAPP_BOTTOM_NAV_OFFSET =
  "calc(4.25rem + env(safe-area-inset-bottom, 0px))";

export const MINIAPP_SCROLL_BOTTOM_WITH_ACTION =
  "calc(8.75rem + env(safe-area-inset-bottom, 0px))";

/** Нижний отступ PDP в compact: sticky-бар + (в mini-app) место над bottom nav. */
export const PDP_COMPACT_SCROLL_PAD = MINIAPP_SCROLL_BOTTOM_WITH_ACTION;

export const PDP_MINIAPP_SCROLL_PAD =
  "calc(8.75rem + 4.25rem + env(safe-area-inset-bottom, 0px))";

/** Отступ скролла под sticky «В корзину» (bottom nav уже в MiniAppLayout main). */
export const MINIAPP_STICKY_ACTION_SCROLL_PAD =
  "calc(3.5rem + 0.5rem + env(safe-area-inset-bottom, 0px))";

/** Toast над нижней навигацией Mini App. */
export const MINIAPP_TOAST_BOTTOM =
  "calc(4.25rem + env(safe-area-inset-bottom, 0px) + 0.5rem)";
