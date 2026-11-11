import { useOutletContext } from "react-router";
import { useIsMobile } from "../../app/components/ui/use-mobile";
import {
  currentStorefrontSurface,
  type StorefrontOutletContext,
  type StorefrontSurface,
} from "./miniApp";

/** Текущая поверхность: web или miniapp (из layout outlet context). */
export function useStorefrontSurface(): StorefrontSurface {
  const ctx = useOutletContext<StorefrontOutletContext | null>();
  return ctx?.surface ?? currentStorefrontSurface();
}

/** Компактный UI как в Mini App (Telegram или мобильный браузер). */
export function useStorefrontCompact(): boolean {
  const surface = useStorefrontSurface();
  const isMobile = useIsMobile();
  return surface === "miniapp" || isMobile;
}

/** Нижняя навигация только в Telegram Mini App. */
export function useStorefrontBottomNav(): boolean {
  return useStorefrontSurface() === "miniapp";
}

/** Верхний отступ контента в компактном режиме (на вебе учитывает fixed Navbar). */
export function useStorefrontCompactPagePad(extra = ""): string {
  const surface = useStorefrontSurface();
  const compact = useStorefrontCompact();
  if (!compact) return ["pt-24", extra].filter(Boolean).join(" ");
  return [surface === "miniapp" ? "pt-2" : "pt-16", extra].filter(Boolean).join(" ");
}

/** Оболочка account/cart/checkout: pt + pb. */
export function useStorefrontPageShellPad(): string {
  const surface = useStorefrontSurface();
  const compact = useStorefrontCompact();
  if (!compact) return "pt-24 pb-20";
  return surface === "miniapp" ? "pt-6 pb-8" : "pt-16 pb-8";
}

const PDP_COMPACT_BREAKPOINT_PX = 768;

/** Sync compact for PDP fallback/first paint (no useEffect lag). */
export function readPdpFrameCompact(surface: StorefrontSurface = currentStorefrontSurface()): boolean {
  if (surface === "miniapp") return true;
  if (typeof window === "undefined") return false;
  return window.innerWidth < PDP_COMPACT_BREAKPOINT_PX;
}

export function pdpHeroPageClassName(compact: boolean, pagePad: string): string {
  return compact
    ? `bg-sp-bg px-3 ${pagePad}`
    : "mx-auto max-w-[1400px] bg-sp-bg px-6 pt-24 lg:px-8";
}

export function pdpHeroGridClassName(compact: boolean): string {
  return compact
    ? "product-pdp-grid grid grid-cols-1 gap-3 pb-0"
    : "product-pdp-grid grid gap-8 pb-4 lg:grid-cols-2 lg:gap-12 lg:items-start";
}

export function pdpHeroFrameClassName(compact: boolean): string {
  return compact
    ? "relative mx-auto aspect-square w-full max-w-[320px] overflow-hidden border border-sp-border bg-sp-bg rounded-[14px]"
    : "relative aspect-square w-full overflow-hidden border border-sp-border bg-sp-bg rounded-[22px]";
}
