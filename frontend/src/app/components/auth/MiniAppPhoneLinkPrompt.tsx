import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../../auth/AuthContext";
import { fetchIdentities, type Identity } from "../../../lib/storefront/identities";
import { isInsideTelegramWebApp, requestTelegramContact } from "../../../lib/storefront/telegramWebApp";
import { isTelegramMiniAppRoute } from "../../../lib/storefront/miniApp";

function hasPhoneIdentity(identities: Identity[] | undefined) {
  return identities?.some((item) => item.provider === "phone") ?? false;
}

// Ненавязчиво предлагает подключить телефон в Mini App.
export function MiniAppPhoneLinkPrompt() {
  const { user, refresh } = useAuth();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const userId = user?.id;
  const phoneLinked = useMemo(() => hasPhoneIdentity(user?.identities), [user?.identities]);

  useEffect(() => {
    if (!isTelegramMiniAppRoute() || !isInsideTelegramWebApp() || !userId || phoneLinked) {
      setOpen(false);
      return;
    }
    const timer = window.setTimeout(() => setOpen(true), 1200);
    return () => window.clearTimeout(timer);
  }, [phoneLinked, userId]);

  function hideForLater() {
    setOpen(false);
  }

  async function connectPhone() {
    setBusy(true);
    setError(null);
    const shared = await requestTelegramContact();
    if (!shared) {
      setBusy(false);
      setError("Контакт не отправлен.");
      return;
    }
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const identities = await fetchIdentities();
      if (hasPhoneIdentity(identities)) {
        await refresh();
        setOpen(false);
        setBusy(false);
        return;
      }
    }
    setBusy(false);
    setError("Телефон ещё не подключён. Попробуйте снова чуть позже.");
  }

  if (!open) return null;

  return (
    <div className="fixed inset-x-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom,0px))] z-40">
      <div
        className="rounded-[24px] border p-5 shadow-[0_16px_45px_rgba(0,0,0,0.14)]"
        style={{ background: "var(--sp-surface)", borderColor: "var(--sp-border)" }}
        role="dialog"
        aria-labelledby="miniapp-phone-link-title"
      >
        <h2 id="miniapp-phone-link-title" className="m-0 text-[18px] font-semibold text-sp-text-primary">
          Подключить телефон
        </h2>
        <p className="mb-4 mt-2 text-[14px] leading-5 text-sp-text-secondary">
          Подключите телефон, чтобы использовать один аккаунт на сайте и в Telegram.
        </p>
        {error ? <p className="mb-3 mt-0 text-[12px] text-[#d4183d]">{error}</p> : null}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void connectPhone()}
            className="flex-1 rounded-full px-4 py-2.5 text-[13px] font-semibold text-white disabled:opacity-60"
            style={{ background: "var(--sp-blue)" }}
          >
            {busy ? "Подключаем…" : "Подключить телефон"}
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
