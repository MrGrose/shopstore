export const MINIAPP_PILL_BASE =
  "inline-flex items-center justify-center gap-1.5 px-3 py-1 text-[12px] font-medium sp-transition whitespace-nowrap rounded-full";

export function miniAppPillClass(active = false): string {
  return active
    ? `${MINIAPP_PILL_BASE} bg-sp-blue text-white`
    : `${MINIAPP_PILL_BASE} border border-sp-border bg-sp-surface text-sp-text-secondary`;
}

export function miniAppInputClass(): string {
  return "min-w-0 flex-1 rounded-full border border-sp-border bg-sp-surface px-3 py-1.5 text-[12px] outline-none focus:border-sp-blue";
}
