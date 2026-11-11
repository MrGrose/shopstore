import { checkoutCardStyle } from "../../../lib/storefront/checkoutUi";
import { EmailIdentityVerifyBlock } from "./EmailIdentityVerifyBlock";
import { TelegramLinkAction } from "./TelegramLinkAction";

type NotificationChannelPickerProps = {
  compact: boolean;
  channels: string[];
  onChannelsChange: (channels: string[]) => void;
  telegramLinked: boolean;
  email: string;
  onEmailChange: (value: string) => void;
  emailVerified: boolean;
  onEmailVerified: () => void | Promise<void>;
};

// Выбор каналов уведомлений заказа и подтверждение identity.
export function NotificationChannelPicker({
  compact,
  channels,
  onChannelsChange,
  telegramLinked,
  email,
  onEmailChange,
  emailVerified,
  onEmailVerified,
}: NotificationChannelPickerProps) {
  const hasTelegramChannel = channels.includes("telegram");
  const hasEmailChannel = channels.includes("email");

  return (
    <div className={compact ? "p-3" : "p-4"} style={checkoutCardStyle}>
      <div
        className={`mb-2 font-semibold text-sp-text-primary ${compact ? "text-[13px]" : "text-[14px]"}`}
      >
        Каналы уведомлений
      </div>
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sp-text-secondary">
          <input
            type="checkbox"
            checked={hasTelegramChannel}
            onChange={(event) =>
              onChannelsChange(
                event.target.checked
                  ? [...new Set([...channels, "telegram"])]
                  : channels.filter((item) => item !== "telegram"),
              )
            }
          />
          <span className="inline-flex items-center gap-1.5">
            Telegram
            {hasTelegramChannel && telegramLinked ? (
              <span className="text-sp-cyan" aria-label="Telegram подтверждён">
                ✓
              </span>
            ) : null}
          </span>
        </label>
        {hasTelegramChannel && !telegramLinked ? (
          <div className="mt-2">
            <TelegramLinkAction />
          </div>
        ) : null}
        <label className="flex items-center gap-2 text-sp-text-secondary">
          <input
            type="checkbox"
            checked={hasEmailChannel}
            onChange={(event) =>
              onChannelsChange(
                event.target.checked
                  ? [...new Set([...channels, "email"])]
                  : channels.filter((item) => item !== "email"),
              )
            }
          />
          <span className="inline-flex items-center gap-1.5">
            Email
            {hasEmailChannel && emailVerified ? (
              <span className="text-sp-cyan" aria-label="Email подтверждён">
                ✓
              </span>
            ) : null}
          </span>
        </label>
      </div>
      {hasEmailChannel && !emailVerified ? (
        <div className="mt-3">
          <EmailIdentityVerifyBlock
            email={email}
            onEmailChange={onEmailChange}
            verified={emailVerified}
            onVerified={onEmailVerified}
          />
        </div>
      ) : null}
    </div>
  );
}
