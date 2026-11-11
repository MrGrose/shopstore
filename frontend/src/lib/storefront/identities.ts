import { storefrontApiFetch } from "./api";
import type { StorefrontUser } from "./session";

export type Identity = {
  provider: string;
  provider_user_id?: string | null;
  email?: string | null;
  telegram_username?: string | null;
  created_at?: string | null;
};

// Список привязанных способов входа.
export async function fetchIdentities(): Promise<Identity[]> {
  const data = await storefrontApiFetch<Identity[]>("/users/me/identities");
  return Array.isArray(data) ? data : [];
}

// OTP для привязки email к текущему аккаунту.
export async function sendLinkEmailCode(email: string): Promise<void> {
  await storefrontApiFetch("/users/me/identities/email/send-code", {
    method: "POST",
    body: JSON.stringify({ email: email.trim() }),
  });
}

// Подтверждает OTP и привязывает email.
export async function verifyLinkEmail(
  email: string,
  code: string,
): Promise<StorefrontUser> {
  return storefrontApiFetch<StorefrontUser>("/users/me/identities/email/verify", {
    method: "POST",
    body: JSON.stringify({
      email: email.trim(),
      code: code.trim(),
    }),
  });
}

// Отправляет verification code для привязки телефона.
export async function sendLinkPhoneCode(phone: string): Promise<void> {
  await storefrontApiFetch("/users/me/identities/phone/send-code", {
    method: "POST",
    body: JSON.stringify({ phone: phone.trim() }),
  });
}

// Подтверждает код и привязывает телефон.
export async function verifyLinkPhone(
  phone: string,
  code: string,
): Promise<StorefrontUser> {
  return storefrontApiFetch<StorefrontUser>("/users/me/identities/phone/verify", {
    method: "POST",
    body: JSON.stringify({
      phone: phone.trim(),
      code: code.trim(),
    }),
  });
}

// Создаёт одноразовую ссылку для привязки Telegram к текущему аккаунту.
export async function createTelegramLink(): Promise<{
  url: string;
  expires_in: number;
}> {
  const data = await storefrontApiFetch<{ url: string; expires_in: number }>(
    "/users/me/identities/telegram/link",
    { method: "POST" },
  );
  if (!data?.url) throw new Error("Не удалось создать ссылку Telegram");
  return data;
}
