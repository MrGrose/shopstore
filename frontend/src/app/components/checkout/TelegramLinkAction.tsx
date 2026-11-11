import { useState } from "react";

import { createTelegramLink } from "../../../lib/storefront/identities";
import { userFacingApiErrorMessage } from "../../../lib/errorMessages";

type TelegramLinkActionProps = {
  buttonLabel?: string;
  busyLabel?: string;
};

// Открывает одноразовую ссылку для привязки Telegram к аккаунту.
export function TelegramLinkAction({
  buttonLabel = "Подключить Telegram",
  busyLabel = "Создаём ссылку…",
}: TelegramLinkActionProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div>
      <button
        type="button"
        disabled={busy}
        className="rounded-xl border border-sp-blue px-4 py-2 text-[13px] text-sp-blue disabled:opacity-60"
        onClick={() => {
          setBusy(true);
          setError(null);
          void createTelegramLink()
            .then(({ url }) => {
              window.open(url, "_blank", "noopener,noreferrer");
            })
            .catch((linkError) => {
              setError(
                userFacingApiErrorMessage(
                  linkError,
                  "Не удалось создать ссылку Telegram",
                ),
              );
            })
            .finally(() => setBusy(false));
        }}
      >
        {busy ? busyLabel : buttonLabel}
      </button>
      {error ? (
        <p className="m-0 mt-2 text-[12px] text-[#d4183d]">{error}</p>
      ) : null}
    </div>
  );
}
