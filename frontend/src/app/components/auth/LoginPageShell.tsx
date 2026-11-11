import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { storefrontHomePath } from "../../../lib/storefront/catalogNavigation";
import { motion } from "motion/react";

export const LOGIN_FONT = "'DM Sans', sans-serif";

export const loginInputStyle: CSSProperties = {
  width: "100%",
  height: "52px",
  borderRadius: "14px",
  border: "1.5px solid rgba(0,0,0,0.1)",
  background: "#ffffff",
  padding: "0 16px",
  fontFamily: LOGIN_FONT,
  fontSize: "15px",
  color: "#0e0e0e",
  outline: "none",
};

export const loginLinkButtonStyle: CSSProperties = {
  fontFamily: LOGIN_FONT,
  fontSize: "14px",
  color: "#2AABEE",
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
};

export const loginLegalLinkStyle: CSSProperties = {
  color: "#8a8a8a",
  textDecoration: "underline",
  cursor: "pointer",
  textUnderlineOffset: "2px",
  background: "none",
  border: "none",
  padding: 0,
  font: "inherit",
};

type Props = {
  hintText: string;
  statusArea: ReactNode;
  children: ReactNode;
  legalFooter: ReactNode;
};

function Benefit({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path
            d="M3 8.5L6.5 12L13 5"
            stroke="#0e0e0e"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <span style={{ fontFamily: LOGIN_FONT }} className="text-[15px] font-normal text-[#0e0e0e]">
        {text}
      </span>
    </div>
  );
}

// Обёртка страницы входа в стиле Figma.
export function LoginPageShell({ hintText, statusArea, children, legalFooter }: Props) {
  return (
    <div
      className="min-h-dvh w-full flex flex-col relative"
      style={{
        background:
          "linear-gradient(160deg, #fafafa 0%, #f5f5f3 35%, #f0f0ee 70%, #fafafa 100%)",
        fontFamily: LOGIN_FONT,
      }}
    >
      <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true" style={{ zIndex: 0 }}>
        <div
          style={{
            position: "absolute",
            top: "-10%",
            left: "50%",
            transform: "translateX(-50%)",
            width: "800px",
            height: "500px",
            background:
              "radial-gradient(ellipse at center, rgba(42,171,238,0.04) 0%, transparent 70%)",
            filter: "blur(60px)",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: "0",
            right: "-10%",
            width: "600px",
            height: "400px",
            background:
              "radial-gradient(ellipse at center, rgba(14,14,14,0.025) 0%, transparent 70%)",
            filter: "blur(80px)",
          }}
        />
      </div>

      <div
        className="relative flex flex-1 flex-col items-center justify-center w-full px-6 py-8"
        style={{ zIndex: 1 }}
      >
        <div className="flex flex-col items-center w-full" style={{ maxWidth: "480px" }}>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.25, 0.1, 0.25, 1], delay: 0.05 }}
          className="flex flex-col items-center text-center mb-12"
        >
          <Link
            to={storefrontHomePath()}
            className="no-underline"
            style={{
              fontFamily: LOGIN_FONT,
              fontWeight: 700,
              fontSize: "clamp(36px, 6vw, 52px)",
              letterSpacing: "-0.03em",
              lineHeight: 1,
            }}
          >
            <span style={{ color: "#0e0e0e" }}>SHOP</span>
            <span style={{ color: "var(--sp-cyan)", fontWeight: 600 }}>STORE</span>
          </Link>
          <div
            className="mt-[10px] flex flex-wrap items-center justify-center gap-3"
            style={{
              fontFamily: LOGIN_FONT,
              fontWeight: 400,
              fontSize: "11px",
              letterSpacing: "0.08em",
              color: "#8a8a8a",
            }}
          >
            <span className="inline-flex items-center gap-1">🎾 Теннис</span>
            <span aria-hidden="true">•</span>
            <span className="inline-flex items-center gap-1">🏓 Падел</span>
            <span aria-hidden="true">•</span>
            <span className="inline-flex items-center gap-1">🏃 Бег</span>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.25, 0.1, 0.25, 1], delay: 0.12 }}
          className="flex flex-col items-center text-center mb-6 w-full"
        >
          <h2
            style={{
              fontFamily: LOGIN_FONT,
              fontWeight: 600,
              fontSize: "clamp(26px, 5vw, 32px)",
              letterSpacing: "-0.02em",
              lineHeight: 1.2,
              color: "#0e0e0e",
              marginBottom: "12px",
            }}
          >
            Добро пожаловать
          </h2>
          <p
            style={{
              fontFamily: LOGIN_FONT,
              fontWeight: 400,
              fontSize: "15px",
              lineHeight: 1.55,
              color: "#6b6b6b",
              maxWidth: "340px",
            }}
          >
            {hintText}
          </p>
        </motion.div>

        {statusArea ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.16 }}
            className="mb-4 w-full text-center"
            style={{ maxWidth: "360px" }}
          >
            {statusArea}
          </motion.div>
        ) : null}

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, ease: [0.25, 0.1, 0.25, 1], delay: 0.2 }}
          className="w-full flex flex-col items-center mb-6"
          style={{ maxWidth: "360px" }}
        >
          {children}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.25, 0.1, 0.25, 1], delay: 0.36 }}
          className="flex w-full flex-col gap-4"
          style={{ maxWidth: "300px" }}
        >
          <Benefit text="История заказов" />
          <Benefit text="Отслеживание доставки" />
          <Benefit text="Уведомления о статусах заказа" />
        </motion.div>
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.46 }}
        className="relative shrink-0 w-full px-6 flex justify-center"
        style={{
          zIndex: 1,
          paddingBottom: "max(1.5rem, env(safe-area-inset-bottom))",
        }}
      >
        <div
          style={{
            fontFamily: LOGIN_FONT,
            fontSize: "12px",
            lineHeight: 1.6,
            color: "#b0b0b0",
            textAlign: "center",
            maxWidth: "320px",
          }}
        >
          {legalFooter}
        </div>
      </motion.div>
    </div>
  );
}

type LoginSubmitButtonProps = {
  disabled?: boolean;
  children: ReactNode;
};

// Primary CTA для OTP-форм в стиле Telegram-кнопки.
export function LoginSubmitButton({ disabled, children }: LoginSubmitButtonProps) {
  const [hover, setHover] = useState(false);

  return (
    <button
      type="submit"
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: "100%",
        height: "58px",
        borderRadius: "16px",
        border: "none",
        background: disabled ? "#2AABEE" : hover ? "#229ED9" : "#2AABEE",
        color: "#ffffff",
        fontFamily: LOGIN_FONT,
        fontWeight: 600,
        fontSize: "16px",
        letterSpacing: "-0.01em",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        boxShadow: hover && !disabled
          ? "0 8px 32px rgba(42,171,238,0.35), 0 2px 8px rgba(42,171,238,0.2)"
          : "0 4px 24px rgba(42,171,238,0.25), 0 1px 4px rgba(42,171,238,0.15)",
        transition: "all 0.2s ease",
        transform: hover && !disabled ? "translateY(-1px)" : "translateY(0)",
      }}
    >
      {children}
    </button>
  );
}
