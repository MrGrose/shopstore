import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

export type CatalogFilterSectionShellProps = {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  titleSuffix?: ReactNode;
};

export function CatalogFilterSectionShell({
  title,
  open,
  onToggle,
  children,
  titleSuffix,
}: CatalogFilterSectionShellProps) {
  return (
    <div className="pb-5 mb-5 border-b border-sp-border last:border-b-0 last:mb-0 last:pb-0">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between mb-3 group"
        aria-expanded={open}
      >
        <span className="text-[11px] uppercase tracking-[0.1em] font-semibold text-sp-text-muted">
          {title}
          {titleSuffix}
        </span>
        <ChevronDown
          size={16}
          className="text-sp-text-muted sp-transition"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
        />
      </button>
      {open ? children : null}
    </div>
  );
}
