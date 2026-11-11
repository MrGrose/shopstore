import type { ReactNode } from "react";
import { XIcon } from "lucide-react";

import { miniAppPillClass } from "../../../lib/storefront/miniAppUi";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "../ui/sheet";

export type CatalogFiltersSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  compact: boolean;
  activeFilterCount: number;
  children: ReactNode;
};

export function CatalogFiltersSheet({
  open,
  onOpenChange,
  compact,
  activeFilterCount,
  children,
}: CatalogFiltersSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <button
          type="button"
          className={
            compact
              ? `${miniAppPillClass(activeFilterCount > 0)} shrink-0`
              : "w-full rounded-xl border border-sp-border bg-white px-6 py-3 font-medium text-sp-text-primary sp-transition hover:border-sp-blue"
          }
        >
          Фильтры{activeFilterCount > 0 ? ` · ${activeFilterCount}` : ""}
        </button>
      </SheetTrigger>
      <SheetContent
        side={compact ? "bottom" : "left"}
        hideClose={compact}
        className={
          compact
            ? "flex h-[min(88dvh,calc(100dvh-env(safe-area-inset-bottom)))] max-h-[min(88dvh,calc(100dvh-env(safe-area-inset-bottom)))] flex-col gap-0 overflow-hidden rounded-t-2xl border-t border-sp-border bg-sp-surface p-0"
            : "flex h-full max-h-[100dvh] w-full flex-col gap-0 overflow-hidden bg-sp-surface p-0 sm:max-w-md"
        }
      >
        {compact ? (
          <>
            <div className="shrink-0 border-b border-sp-border px-4 pb-3 pt-3">
              <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-sp-border" aria-hidden />
              <div className="flex items-center justify-between gap-3">
                <SheetTitle className="m-0 text-[14px] font-semibold text-sp-text-primary">
                  Фильтры
                </SheetTitle>
                <SheetClose className="flex size-8 shrink-0 items-center justify-center rounded-full border border-sp-border bg-white text-sp-text-primary shadow-sm sp-transition hover:opacity-80">
                  <XIcon className="size-4" />
                  <span className="sr-only">Закрыть</span>
                </SheetClose>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3">
              {children}
            </div>
          </>
        ) : (
          <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">{children}</div>
        )}
      </SheetContent>
    </Sheet>
  );
}
