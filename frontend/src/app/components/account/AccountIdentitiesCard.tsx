import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { storefrontApiFetch } from "../../../lib/storefront/api";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";
import {
  fetchIdentities,
  sendLinkPhoneCode,
  verifyLinkPhone,
  type Identity,
} from "../../../lib/storefront/identities";
import { validateRuMobilePhone } from "../../../lib/storefront/phone";
import type { StorefrontUser } from "../../../lib/storefront/session";
import { isInsideTelegramWebApp, requestTelegramContact } from "../../../lib/storefront/telegramWebApp";
import { isTelegramMiniAppRoute } from "../../../lib/storefront/miniApp";
import { EmailIdentityVerifyBlock } from "../checkout/EmailIdentityVerifyBlock";
import { TelegramLinkAction } from "../checkout/TelegramLinkAction";

type Props = {
  user: StorefrontUser | null;
  onUpdated: () => void | Promise<void>;
};

function hasEmailIdentity(identities: Identity[]) {
  return identities.some((item) => item.provider === "email");
}

function hasTelegramIdentity(identities: Identity[]) {
  return identities.some((item) => item.provider === "telegram");
}

function hasPhoneIdentity(identities: Identity[]) {
  return identities.some((item) => item.provider === "phone");
}

function emailValue(user: StorefrontUser | null, identities: Identity[]) {
  const fromIdentity = identities.find((item) => item.provider === "email")?.email?.trim();
  if (fromIdentity) return fromIdentity;
  return user?.email?.trim() || null;
}

function telegramValue(user: StorefrontUser | null, identities: Identity[]) {
  const fromIdentity = identities.find((item) => item.provider === "telegram");
  if (fromIdentity?.telegram_username) return `@${fromIdentity.telegram_username}`;
  if (user?.telegram_username) return `@${user.telegram_username}`;
  if (user?.telegram_id) return `Telegram id ${user.telegram_id}`;
  if (fromIdentity) return "Telegram";
  return null;
}

function phoneValue(identities: Identity[]) {
  const fromIdentity = identities.find((item) => item.provider === "phone");
  return fromIdentity?.provider_user_id?.trim() || null;
}

function formatDateTime(raw?: string | null) {
  if (!raw) return "—";
  const iso = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : raw.includes("T") ? `${raw}Z` : raw;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function ProfileRow({
  label,
  children,
  last = false,
}: {
  label: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <div
      className="flex justify-between items-center gap-3 px-6 py-4"
      style={{
        borderBottom: last ? "none" : "1px solid var(--sp-border)",
      }}
    >
      <span className="text-[14px] shrink-0" style={{ color: "var(--sp-text-muted)" }}>
        {label}
      </span>
      <div className="min-w-0 text-right">{children}</div>
    </div>
  );
}

const linkButtonStyle = {
  borderColor: "var(--sp-blue)",
  color: "var(--sp-blue)",
  background: "transparent",
} as const;

export function AccountIdentitiesCard({ user, onUpdated }: Props) {
  const [identities, setIdentities] = useState<Identity[]>(user?.identities ?? []);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [phoneOtpCode, setPhoneOtpCode] = useState("");
  const [phoneOtpSent, setPhoneOtpSent] = useState(false);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [contactBusy, setContactBusy] = useState(false);
  const [verificationCodeEnabled, setVerificationCodeEnabled] = useState(false);
  const [emailLinkOpen, setEmailLinkOpen] = useState(false);
  const [phoneLinkOpen, setPhoneLinkOpen] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchIdentities();
      setIdentities(data);
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось загрузить способы входа"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.identities?.length) {
      setIdentities(user.identities);
      return;
    }
    void reload();
  }, [reload, user?.identities]);

  useEffect(() => {
    void storefrontApiFetch<{
      phone_verification_code_enabled?: boolean;
    }>("/storefront/social")
      .then((data) => {
        setVerificationCodeEnabled(data?.phone_verification_code_enabled === true);
      })
      .catch(() => undefined);
  }, []);

  const emailLinked = hasEmailIdentity(identities);
  const telegramLinked = hasTelegramIdentity(identities);
  const phoneLinked = hasPhoneIdentity(identities);
  const miniAppCanShareContact = isInsideTelegramWebApp();
  const showPhoneCodeLink = !isTelegramMiniAppRoute() && verificationCodeEnabled;
  const showPhoneActions = !phoneLinked && (showPhoneCodeLink || miniAppCanShareContact);

  const linkedEmail = emailValue(user, identities);
  const linkedTelegram = telegramValue(user, identities);
  const linkedPhone = phoneValue(identities);

  async function handleEmailVerified() {
    setError(null);
    setStatus("Email привязан.");
    setEmailLinkOpen(false);
    await reload();
    await onUpdated();
  }

  async function requestPhoneCode() {
    const phoneError = validateRuMobilePhone(phone);
    if (phoneError) {
      setError(phoneError);
      return;
    }
    setPhoneBusy(true);
    setError(null);
    setStatus(null);
    try {
      await sendLinkPhoneCode(phone);
      setPhoneOtpSent(true);
      setPhoneOtpCode("");
      setStatus("Код отправлен в Telegram.");
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось отправить код"));
    } finally {
      setPhoneBusy(false);
    }
  }

  async function handleSendPhoneCode(event: FormEvent) {
    event.preventDefault();
    await requestPhoneCode();
  }

  async function handleVerifyPhone(event: FormEvent) {
    event.preventDefault();
    setPhoneBusy(true);
    setError(null);
    setStatus(null);
    try {
      await verifyLinkPhone(phone, phoneOtpCode);
      setPhoneOtpSent(false);
      setPhoneOtpCode("");
      setStatus("Телефон привязан.");
      setPhoneLinkOpen(false);
      await reload();
      await onUpdated();
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Неверный или устаревший код"));
    } finally {
      setPhoneBusy(false);
    }
  }

  // Запрашивает собственный контакт в Telegram и ждёт обновления identity.
  async function handleShareTelegramContact() {
    setContactBusy(true);
    setError(null);
    setStatus(null);
    try {
      const shared = await requestTelegramContact();
      if (!shared) {
        setStatus("Контакт не отправлен.");
        return;
      }
      setStatus("Контакт отправлен. Ожидаем подтверждение телефона…");
      for (let attempt = 0; attempt < 10; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const next = await fetchIdentities();
        setIdentities(next);
        if (next.some((item) => item.provider === "phone")) {
          setStatus("Телефон привязан.");
          setPhoneLinkOpen(false);
          await onUpdated();
          return;
        }
      }
      setStatus("Телефон ещё не подтверждён. Обновите профиль позже.");
    } catch (e) {
      setError(userFacingApiErrorMessage(e, "Не удалось отправить контакт"));
    } finally {
      setContactBusy(false);
    }
  }

  return (
    <div
      style={{
        background: "var(--sp-surface)",
        border: "1px solid var(--sp-border)",
        borderRadius: "18px",
        overflow: "hidden",
      }}
    >
      {loading ? (
        <p className="text-[13px] m-0 px-6 py-4" style={{ color: "var(--sp-text-muted)" }}>
          Загрузка…
        </p>
      ) : (
        <>
          <ProfileRow label="Имя">
            <span className="text-[14px] font-medium" style={{ color: "var(--sp-text-primary)" }}>
              {user?.name?.trim() || "—"}
            </span>
          </ProfileRow>

          <ProfileRow label="Email">
            {emailLinked ? (
              <span className="text-[14px] font-medium truncate" style={{ color: "var(--sp-text-primary)" }}>
                {linkedEmail || "—"}
              </span>
            ) : emailLinkOpen ? (
              <button
                type="button"
                onClick={() => setEmailLinkOpen(false)}
                className="text-[13px] bg-transparent border-0 cursor-pointer p-0"
                style={{ color: "var(--sp-text-muted)" }}
              >
                Отмена
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setEmailLinkOpen(true)}
                className="text-[13px] px-4 py-2 rounded-xl border cursor-pointer"
                style={linkButtonStyle}
              >
                Подключить email
              </button>
            )}
          </ProfileRow>

          {!emailLinked && emailLinkOpen ? (
            <div
              className="min-w-0 max-w-full overflow-hidden px-6 pt-3 pb-4"
              style={{ borderBottom: "1px solid var(--sp-border)" }}
            >
              <EmailIdentityVerifyBlock
                email={email}
                onEmailChange={setEmail}
                verified={emailLinked}
                onVerified={handleEmailVerified}
              />
            </div>
          ) : null}

          <ProfileRow label="Telegram">
            {telegramLinked ? (
              <span className="text-[14px] font-medium truncate" style={{ color: "var(--sp-text-primary)" }}>
                {linkedTelegram || "—"}
              </span>
            ) : (
              <TelegramLinkAction buttonLabel="Подключить Telegram" />
            )}
          </ProfileRow>

          <ProfileRow label="Телефон">
            {phoneLinked ? (
              <span className="text-[14px] font-medium truncate" style={{ color: "var(--sp-text-primary)" }}>
                {linkedPhone || "—"}
              </span>
            ) : showPhoneActions && phoneLinkOpen ? (
              <button
                type="button"
                onClick={() => setPhoneLinkOpen(false)}
                className="text-[13px] bg-transparent border-0 cursor-pointer p-0"
                style={{ color: "var(--sp-text-muted)" }}
              >
                Отмена
              </button>
            ) : showPhoneActions ? (
              <button
                type="button"
                onClick={() => setPhoneLinkOpen(true)}
                className="text-[13px] px-4 py-2 rounded-xl border cursor-pointer"
                style={linkButtonStyle}
              >
                Подключить телефон
              </button>
            ) : (
              <span className="text-[14px] font-medium" style={{ color: "var(--sp-text-muted)" }}>
                —
              </span>
            )}
          </ProfileRow>

          {!phoneLinked && phoneLinkOpen && showPhoneActions ? (
            <div
              className="px-6 pb-4"
              style={{ borderBottom: "1px solid var(--sp-border)" }}
            >
              {showPhoneCodeLink ? (
                <form
                  className="flex flex-col gap-2 max-w-[350px]"
                  onSubmit={(event) =>
                    void (phoneOtpSent ? handleVerifyPhone(event) : handleSendPhoneCode(event))
                  }
                >
                  <input
                    type="tel"
                    autoComplete="tel"
                    placeholder="+79991234567"
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                    disabled={phoneOtpSent || phoneBusy}
                    className="w-full px-3 py-2 text-[14px] rounded-xl border"
                    style={{
                      borderColor: "var(--sp-border)",
                      background: "var(--sp-bg)",
                      color: "var(--sp-text-primary)",
                    }}
                  />
                  {phoneOtpSent ? (
                    <input
                      type="text"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      placeholder="Код из Telegram"
                      value={phoneOtpCode}
                      onChange={(event) => setPhoneOtpCode(event.target.value)}
                      disabled={phoneBusy}
                      className="w-full px-3 py-2 text-[14px] rounded-xl border"
                      style={{
                        borderColor: "var(--sp-border)",
                        background: "var(--sp-bg)",
                        color: "var(--sp-text-primary)",
                      }}
                    />
                  ) : null}
                  <button
                    type="submit"
                    disabled={phoneBusy}
                    className="text-[13px] px-4 py-2 rounded-xl border cursor-pointer disabled:opacity-60 self-start"
                    style={linkButtonStyle}
                  >
                    {phoneBusy
                      ? "Отправляем…"
                      : phoneOtpSent
                        ? "Подтвердить телефон"
                        : "Получить код в Telegram"}
                  </button>
                  {phoneOtpSent ? (
                    <button
                      type="button"
                      disabled={phoneBusy}
                      className="text-[13px] bg-transparent border-0 cursor-pointer disabled:opacity-60 p-0 self-start"
                      style={{ color: "var(--sp-blue)" }}
                      onClick={() => void requestPhoneCode()}
                    >
                      Отправить код повторно
                    </button>
                  ) : null}
                </form>
              ) : null}
              {miniAppCanShareContact ? (
                <button
                  type="button"
                  disabled={contactBusy}
                  className="text-[13px] px-4 py-2 rounded-xl border cursor-pointer disabled:opacity-60"
                  style={linkButtonStyle}
                  onClick={() => void handleShareTelegramContact()}
                >
                  {contactBusy ? "Ожидаем Telegram…" : "Подключить мой телефон"}
                </button>
              ) : null}
            </div>
          ) : null}

          <ProfileRow label="Дата регистрации" last>
            <span className="text-[14px] font-medium" style={{ color: "var(--sp-text-primary)" }}>
              {formatDateTime(user?.created_at)}
            </span>
          </ProfileRow>
        </>
      )}

      {status ? (
        <p className="text-[13px] m-0 px-6 pb-4" style={{ color: "var(--sp-cyan)" }}>
          {status}
        </p>
      ) : null}
      {error ? (
        <p className="text-[13px] m-0 px-6 pb-4" style={{ color: "#ff8b8b" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
