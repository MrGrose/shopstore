import { useState } from "react";

import {
  sendLinkEmailCode,
  verifyLinkEmail,
} from "../../../lib/storefront/identities";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";
import { SpacedOtpInput } from "../ui/input-otp";

type EmailIdentityVerifyBlockProps = {
  email: string;
  onEmailChange: (value: string) => void;
  verified: boolean;
  onVerified: () => void | Promise<void>;
};

const fieldClassName =
  "w-[17.5rem] max-w-full shrink-0 box-border px-3 text-[14px] min-w-0";
const fieldStyle = {
  boxSizing: "border-box",
  height: "2.5rem",
  borderRadius: "0.5rem",
  borderWidth: "1.5px",
  borderStyle: "solid",
  borderColor: "var(--sp-border)",
  background: "var(--sp-bg)",
  color: "var(--sp-text-primary)",
} as const;
const rowClassName = "flex flex-wrap items-center gap-2 w-full min-w-0 max-w-full";
const actionButtonClassName =
  "shrink-0 box-border h-10 px-4 text-[13px] rounded-xl border cursor-pointer disabled:opacity-60 whitespace-nowrap";
const actionButtonStyle = {
  borderColor: "var(--sp-blue)",
  color: "var(--sp-blue)",
  background: "transparent",
} as const;

// Подтверждает email через OTP перед выбором канала уведомлений.
export function EmailIdentityVerifyBlock({
  email,
  onEmailChange,
  verified,
  onVerified,
}: EmailIdentityVerifyBlockProps) {
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (verified) {
    return null;
  }

  return (
    <div className="flex w-full min-w-0 max-w-full flex-col gap-3">
      <div className={rowClassName}>
        <input
          type="email"
          value={email}
          placeholder="you@example.com"
          onChange={(event) => {
            onEmailChange(event.target.value);
            setError(null);
          }}
          className={fieldClassName}
          style={fieldStyle}
        />
        <button
          type="button"
          disabled={sending || email.trim().length < 3}
          onClick={async () => {
            setSending(true);
            setError(null);
            try {
              await sendLinkEmailCode(email);
            } catch (sendError) {
              setError(
                userFacingApiErrorMessage(sendError, "Не удалось отправить код"),
              );
            } finally {
              setSending(false);
            }
          }}
          className={actionButtonClassName}
          style={actionButtonStyle}
        >
          {sending ? "Отправляем…" : "Получить код"}
        </button>
      </div>

      <div className="flex w-full min-w-0 max-w-full flex-col gap-1.5">
        <span className="text-[12px]" style={{ color: "var(--sp-text-muted)" }}>
          Код из письма
        </span>
        <div className={rowClassName}>
          <SpacedOtpInput
            maxLength={6}
            value={code}
            onChange={setCode}
            aria-label="Введите код из письма"
          />
          <button
            type="button"
            disabled={code.trim().length !== 6}
            onClick={async () => {
              try {
                await verifyLinkEmail(email, code);
                setError(null);
                await onVerified();
              } catch (verifyError) {
                setError(userFacingApiErrorMessage(verifyError, "Неверный код"));
              }
            }}
            className={actionButtonClassName}
            style={actionButtonStyle}
          >
            Подтвердить
          </button>
        </div>
      </div>

      {error ? (
        <p className="m-0 text-[12px] text-[#d4183d]">{error}</p>
      ) : null}
    </div>
  );
}
