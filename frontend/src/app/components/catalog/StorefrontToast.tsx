import { MINIAPP_TOAST_BOTTOM } from "../../../lib/storefront/miniApp";

export type StorefrontToastProps = {
  message: string;
  compact: boolean;
  bottomNav: boolean;
};

export function StorefrontToast({ message, compact, bottomNav }: StorefrontToastProps) {
  return (
    <div
      className={`fixed left-1/2 ${compact ? "z-[70]" : "bottom-6 z-[60]"}`}
      style={{
        transform: "translateX(-50%)",
        ...(compact
          ? {
              bottom: bottomNav ? MINIAPP_TOAST_BOTTOM : "1.5rem",
              padding: "0.35rem 0.75rem",
              fontSize: "12px",
              fontWeight: 500,
              letterSpacing: "0.02em",
            }
          : {
              zIndex: 60,
              padding: "0.85rem 1.1rem",
              fontFamily: "var(--font-body)",
              letterSpacing: "0.04em",
            }),
        backgroundColor: "var(--sp-surface)",
        border: "1px solid var(--sp-border)",
        color: "var(--sp-text-primary)",
        borderRadius: "var(--sp-radius-pill)",
        boxShadow: "var(--sp-shadow-hover)",
        backdropFilter: "blur(10px)",
      }}
    >
      {message}
    </div>
  );
}
