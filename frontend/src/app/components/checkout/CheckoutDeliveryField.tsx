import { deliveryInputBorder } from "../../../lib/storefront/checkoutUi";

type Props = {
  label: string;
  value: string;
  placeholder: string;
  error?: string;
  compact?: boolean;
  onChange: (value: string) => void;
  inputMode?: "text" | "tel" | "numeric" | "email" | "search" | "none" | "url" | "decimal";
  autoComplete?: string;
};

export function CheckoutDeliveryField({
  label,
  value,
  placeholder,
  error,
  compact = false,
  onChange,
  inputMode,
  autoComplete,
}: Props) {
  return (
    <label className="checkout-field-label">
      <span
        className={`font-semibold uppercase tracking-[0.08em] text-sp-text-muted ${compact ? "text-[10px]" : "text-[11px]"}`}
      >
        {label}
      </span>
      <input
        className="checkout-field-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        inputMode={inputMode}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        style={{
          padding: compact ? "0.5rem 0.75rem" : "0.75rem",
          fontSize: compact ? "12px" : undefined,
          background: "var(--sp-bg)",
          border: deliveryInputBorder(Boolean(error)),
          borderRadius: compact ? "999px" : "var(--sp-radius-input)",
          color: "var(--sp-text-primary)",
        }}
      />
      {error ? (
        <span
          style={{ color: "#ff8b8b", fontSize: compact ? "0.7rem" : "0.78rem", lineHeight: 1.35 }}
          role="alert"
        >
          {error}
        </span>
      ) : null}
    </label>
  );
}
