import type { ReactNode } from "react";
import { useLocation } from "react-router";

import { type ProductPageLocationState } from "../../lib/storefront/catalogFilterParams";
import { readPdpTransitionPreviewUrl } from "../../lib/storefront/imageResolver";
import { currentStorefrontSurface } from "../../lib/storefront/miniApp";
import {
  pdpHeroFrameClassName,
  pdpHeroGridClassName,
  pdpHeroPageClassName,
  readPdpFrameCompact,
} from "../../lib/storefront/useStorefrontSurface";

export type PageRouteFallbackProps = {
  variant?: "page" | "pdp";
};

export function PdpHeroStage({
  compact,
  pagePad,
  children,
}: {
  compact: boolean;
  pagePad: string;
  children: ReactNode;
}) {
  return (
    <div className={pdpHeroPageClassName(compact, pagePad)}>
      <div className={compact ? "mb-2 h-[22px]" : "mb-4 h-6"} aria-hidden />
      <div className={pdpHeroGridClassName(compact)}>
        <div data-pdp-hero="frame" className={pdpHeroFrameClassName(compact)}>
          {children}
        </div>
      </div>
    </div>
  );
}

function PdpSuspenseHero() {
  const location = useLocation();
  const surface = currentStorefrontSurface();
  const compact = readPdpFrameCompact(surface);
  const pagePad = compact ? (surface === "miniapp" ? "pt-2" : "pt-16") : "pt-24";
  const previewImageUrl = readPdpTransitionPreviewUrl(
    (location.state as ProductPageLocationState | null)?.previewImageUrl,
  );
  return (
    <div aria-busy="true" aria-label="Загрузка товара">
      <PdpHeroStage compact={compact} pagePad={pagePad}>
        {previewImageUrl ? (
          <img
            data-pdp-hero="preview"
            src={previewImageUrl}
            alt=""
            className="absolute inset-0 h-full w-full object-cover object-center"
            loading="eager"
            fetchPriority="high"
            decoding="async"
          />
        ) : (
          <div className="h-full w-full animate-pulse bg-sp-border/40" />
        )}
      </PdpHeroStage>
    </div>
  );
}

export function PageRouteFallback({ variant = "page" }: PageRouteFallbackProps) {
  if (variant === "pdp") {
    return <PdpSuspenseHero />;
  }

  return (
    <div
      className="mx-auto w-full max-w-[1400px] bg-sp-bg px-6 pt-24 lg:px-8"
      aria-busy="true"
      aria-label="Загрузка страницы"
    >
      <div className="aspect-square w-full max-w-[640px] animate-pulse rounded-[22px] bg-sp-border/40" />
      <div className="mt-4 space-y-2">
        <div className="h-3 w-24 animate-pulse rounded bg-sp-border/40" />
        <div className="h-6 w-4/5 animate-pulse rounded bg-sp-border/40" />
        <div className="h-5 w-20 animate-pulse rounded bg-sp-border/40" />
      </div>
    </div>
  );
}
