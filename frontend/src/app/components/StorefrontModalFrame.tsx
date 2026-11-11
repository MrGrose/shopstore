import { motion } from "motion/react";
import { XIcon } from "lucide-react";
import type { ReactNode } from "react";

type StorefrontModalFrameProps = {
  title: string;
  titleAddon?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  zIndex?: number;
  width?: string;
  height?: string;
  margin?: string;
};

export function StorefrontModalFrame({
  title,
  titleAddon,
  onClose,
  children,
  zIndex = 90,
  width = "min(980px, 94vw)",
  height = "min(86vh, 900px)",
  margin = "7vh auto",
}: StorefrontModalFrameProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 flex items-start justify-center bg-black/75 p-4 backdrop-blur-sm"
      style={{ zIndex }}
      onClick={onClose}
    >
      <motion.div
        initial={{ y: 18, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 18, opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="flex flex-col overflow-hidden rounded-[var(--sp-radius-card)] border border-sp-border bg-sp-surface shadow-[var(--sp-shadow-soft)]"
        style={{ width, height, margin, maxHeight: "calc(100dvh - 2rem)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-sp-border px-4 py-3 sm:px-5">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <h2 className="min-w-0 truncate text-[16px] font-semibold text-sp-text-primary sm:text-[18px]">
              {title}
            </h2>
            {titleAddon}
          </div>
          <button
            type="button"
            aria-label="Закрыть"
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-full border border-sp-border bg-sp-surface text-sp-text-primary sp-transition hover:border-sp-blue hover:text-sp-blue"
          >
            <XIcon className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 sm:px-5 sm:py-4">{children}</div>
      </motion.div>
    </motion.div>
  );
}
