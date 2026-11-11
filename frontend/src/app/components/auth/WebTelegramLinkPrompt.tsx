import { useEffect, useState } from "react";
import { useAuth } from "../../auth/AuthContext";
import {
  createTelegramLink,
  fetchIdentities,
  type Identity,
} from "../../../lib/storefront/identities";
import { isTelegramMiniAppRoute } from "../../../lib/storefront/miniApp";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";

const HIDE_FOR_MS = 7 * 24 * 60 * 60 * 1000;

function hasTelegramIdentity(identities: Identity[] | undefined) {
  return identities?.some((item) => item.provider === "telegram") ?? false;
}

function storageKey(userId: number) {
  return `sp:web:telegram-link-prompt:v1:${userId}`;
}

// Ненавязчиво предлагает подключить Telegram на обычном сайте.
export function WebTelegramLinkPrompt() {
  const { user, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const userId = user?.id;
  const telegramLinked = hasTelegramIdentity(user?.identities);

  useEffect(() => {
    if (isTelegramMiniAppRoute() || !userId || telegramLinked) {
      setOpen(false);
      return;
    }
    const hiddenAt = Number(localStorage.getItem(storageKey(userId)) ?? 0);
    if (hiddenAt && Date.now() - hiddenAt < HIDE_FOR_MS) return;
    const timer = window.setTimeout(() => setOpen(true), 1200);
    return () => window.clearTimeout(timer);
  }, [telegramLinked, userId]);

  useEffect(() => {
    if (!open) return;
    const onFocus = () => {
      void refresh().then(async () => {
        const identities = await fetchIdentities();
        if (hasTelegramIdentity(identities)) setOpen(false);
      });
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [open, refresh]);

  function hideForLater() {
    if (userId) localStorage.setItem(storageKey(userId), String(Date.now()));
    setOpen(false);
  }

  async function connectTelegram() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await createTelegramLink();
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (cause) {
      setError(userFacingApiErrorMessage(cause, "Не удалось создать ссылку"));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center px-4">
      <div
        className="w-full max-w-[390px] rounded-[24px] border p-5 shadow-[0_16px_45px_rgba(0,0,0,0.14)]"
        style={{ background: "var(--sp-surface)", borderColor: "var(--sp-border)" }}
        role="dialog"
        aria-labelledby="web-telegram-link-title"
      >
        <h2 id="web-telegram-link-title" className="m-0 text-[18px] font-semibold text-sp-text-primary">
          Подключить Telegram
        </h2>
        <p className="mb-4 mt-2 text-[14px] leading-5 text-sp-text-secondary">
          Подключите Telegram, чтобы использовать один аккаунт на сайте и в Telegram.
        </p>
        {error ? <p className="mb-3 mt-0 text-[12px] text-[#d4183d]">{error}</p> : null}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void connectTelegram()}
            className="flex-1 rounded-full px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60"
            style={{ background: "var(--sp-blue)" }}
          >
            {busy ? "Открываем…" : "Подключить Telegram"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={hideForLater}
            className="rounded-full border px-4 py-2.5 text-[13px] font-medium text-sp-text-secondary disabled:opacity-60"
            style={{ borderColor: "var(--sp-border)" }}
          >
            Не сейчас
          </button>
        </div>
      </div>
    </div>
  );
}
