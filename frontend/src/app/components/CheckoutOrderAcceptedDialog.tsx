import { motion, AnimatePresence } from "motion/react";
import { useStorefrontCompact, useStorefrontBottomNav } from "../../lib/storefront/useStorefrontSurface";
import { MINIAPP_BOTTOM_NAV_OFFSET } from "../../lib/storefront/miniApp";
import { miniAppPillClass } from "../../lib/storefront/miniAppUi";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  message: string;
  closeLabel?: string;
  disabledActionLabel?: string;
};

export function CheckoutOrderAcceptedDialog({
  open,
  onClose,
  title,
  message,
  closeLabel = "Понятно",
  disabledActionLabel,
}: Props) {
  const compact = useStorefrontCompact();
  const bottomNav = useStorefrontBottomNav();

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-labelledby="checkout-order-accepted-title"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className={
            compact
              ? "fixed inset-0 z-[120] flex items-end justify-center px-3"
              : "fixed inset-0 z-[120] flex items-center justify-center p-4"
          }
          style={{
            backgroundColor: "rgba(0, 0, 0, 0.4)",
            backdropFilter: "blur(6px)",
            ...(compact && bottomNav
              ? { paddingBottom: `calc(${MINIAPP_BOTTOM_NAV_OFFSET} + 0.5rem)` }
              : {}),
          }}
          onClick={onClose}
        >
          <motion.div
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 12, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className={`relative w-full border border-sp-border bg-sp-surface ${compact ? "max-w-none p-4" : "max-w-md p-6"}`}
            style={{ borderRadius: compact ? "16px" : "var(--sp-radius-card)", boxShadow: "var(--sp-shadow-hover)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3
              id="checkout-order-accepted-title"
              className={`m-0 font-semibold text-sp-text-primary ${compact ? "mb-2 text-[16px]" : "mb-3 text-[20px]"}`}
            >
              {title}
            </h3>
            <p
              className={`m-0 text-sp-text-secondary ${compact ? "mb-4 text-[13px] leading-snug" : "mb-5 text-[15px] leading-relaxed"}`}
            >
              {message}
            </p>
            {disabledActionLabel ? (
              <button
                type="button"
                disabled
                aria-disabled="true"
                className={
                  compact
                    ? `${miniAppPillClass(true)} mb-2 w-full opacity-50 cursor-not-allowed`
                    : "mb-2 w-full cursor-not-allowed py-3 font-semibold text-white sp-transition opacity-50"
                }
                style={
                  compact
                    ? undefined
                    : {
                        background: "var(--sp-blue)",
                        borderRadius: "var(--sp-radius-pill)",
                        border: "none",
                      }
                }
              >
                {disabledActionLabel}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onClose}
              className={
                compact
                  ? `${miniAppPillClass(false)} w-full border border-sp-border`
                  : "w-full cursor-pointer py-3 font-semibold sp-transition border border-sp-border text-sp-text-primary"
              }
              style={
                compact
                  ? undefined
                  : { borderRadius: "var(--sp-radius-pill)", background: "transparent" }
              }
            >
              {closeLabel}
            </button>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
